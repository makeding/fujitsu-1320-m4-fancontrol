#!/usr/bin/env python3
import argparse
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass


IANA_FUJITSU = [0x80, 0x28, 0x00]
OEM_NETFN = "0x2e"
OEM_CMD = "0xf5"
TEMP_RE = re.compile(r"^([^:]+):\s+\+?(-?\d+(?:\.\d+)?)\s*°C")
STOP = False


@dataclass
class TempReadings:
    temps: dict[str, float]

    def get(self, chip: str, label: str) -> float | None:
        return self.temps.get(f"{chip}:{label}")


def on_signal(signum, frame) -> None:
    global STOP
    STOP = True


def hx(value: int) -> str:
    return f"0x{value & 0xff:02x}"


def run(args: argparse.Namespace, cmd: list[str]) -> subprocess.CompletedProcess:
    if args.dry_run:
        print(" ".join(cmd), flush=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, text=True, capture_output=True)


def ipmitool_base(args: argparse.Namespace) -> list[str]:
    return [args.ipmitool, "-I", args.interface]


def set_pwm(args: argparse.Namespace, percent: int) -> None:
    percent = max(args.min_pwm, min(args.max_pwm, percent))
    payload = IANA_FUJITSU + [0x2d, ord("F"), ord("W"), 0x01, 0xff, 0x80, percent]
    cmd = ipmitool_base(args) + ["raw", OEM_NETFN, OEM_CMD] + [hx(x) for x in payload]
    proc = run(args, cmd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"ipmitool failed: {proc.returncode}")


def clear_pwm(args: argparse.Namespace) -> None:
    payload = IANA_FUJITSU + [0x2d, ord("F"), ord("W"), 0x01, 0xff, 0x00, 0x00]
    cmd = ipmitool_base(args) + ["raw", OEM_NETFN, OEM_CMD] + [hx(x) for x in payload]
    proc = run(args, cmd)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"ipmitool clear failed: {proc.returncode}")


def read_sensors(args: argparse.Namespace) -> TempReadings:
    proc = run(args, [args.sensors])
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"sensors failed: {proc.returncode}")

    temps: dict[str, float] = {}
    chip = ""
    for raw_line in proc.stdout.splitlines():
        line = raw_line.rstrip()
        if not line:
            chip = ""
            continue
        if not raw_line.startswith((" ", "\t")) and not line.startswith("Adapter:") and ":" not in line:
            chip = line
            continue
        if not chip:
            continue
        match = TEMP_RE.match(line.strip())
        if match:
            label, value = match.group(1), float(match.group(2))
            temps[f"{chip}:{label}"] = value
    return TempReadings(temps)


def ramp(temp: float | None, points: list[tuple[float, int]]) -> int:
    if temp is None:
        return 0
    if temp <= points[0][0]:
        return points[0][1]
    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        if temp <= t1:
            ratio = (temp - t0) / (t1 - t0)
            return round(p0 + ratio * (p1 - p0))
    return points[-1][1]


def choose_pwm(args: argparse.Namespace, readings: TempReadings) -> tuple[int, dict[str, float | None]]:
    mlx = readings.get(args.mlx_chip, args.mlx_label)
    mlx2 = readings.get(args.mlx2_chip, args.mlx2_label) if args.mlx2_chip else None
    cpu = readings.get(args.cpu_chip, args.cpu_label)
    pch = readings.get(args.pch_chip, args.pch_label)

    values = {"mlx": mlx, "mlx2": mlx2, "cpu": cpu, "pch": pch}
    targets = [
        ramp(mlx, [(68, 30), (75, 35), (80, 45), (85, 60), (90, 80), (95, 100)]),
        ramp(mlx2, [(68, 30), (75, 35), (80, 45), (85, 60), (90, 80), (95, 100)]),
        ramp(cpu, [(50, 30), (65, 38), (75, 50), (86, 75), (95, 100)]),
        ramp(pch, [(60, 30), (70, 38), (80, 50), (90, 75), (98, 100)]),
    ]

    wanted = max(args.min_pwm, max(targets))
    if mlx is None:
        wanted = max(wanted, args.missing_sensor_pwm)
    if cpu is None:
        wanted = max(wanted, args.missing_sensor_pwm)
    return min(args.max_pwm, wanted), values


def smooth_pwm(args: argparse.Namespace, current: int | None, wanted: int) -> int:
    if current is None:
        return wanted
    if wanted > current:
        return min(wanted, current + args.step_up)
    if wanted < current - args.down_hysteresis:
        return max(wanted, current - args.step_down)
    return current


def fmt_temp(value: float | None) -> str:
    return "NA" if value is None else f"{value:.1f}C"


def daemon(args: argparse.Namespace) -> None:
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    current: int | None = None
    last_apply = 0.0

    try:
        while not STOP:
            try:
                readings = read_sensors(args)
                wanted, values = choose_pwm(args, readings)
                next_pwm = smooth_pwm(args, current, wanted)

                now = time.monotonic()
                if current != next_pwm and now - last_apply >= args.min_apply_interval:
                    set_pwm(args, next_pwm)
                    current = next_pwm
                    last_apply = now

                print(
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    f"pwm={current if current is not None else next_pwm}%",
                    f"want={wanted}%",
                    f"mlx={fmt_temp(values['mlx'])}",
                    f"mlx2={fmt_temp(values['mlx2'])}",
                    f"cpu={fmt_temp(values['cpu'])}",
                    f"pch={fmt_temp(values['pch'])}",
                    flush=True,
                )
            except Exception as exc:
                print(time.strftime("%Y-%m-%d %H:%M:%S"), f"error: {exc}", file=sys.stderr, flush=True)
                if args.fail_pwm > 0:
                    try:
                        set_pwm(args, args.fail_pwm)
                        current = args.fail_pwm
                    except Exception as inner:
                        print(f"failed to apply fail pwm: {inner}", file=sys.stderr, flush=True)
            time.sleep(args.interval)
    finally:
        if args.clear_on_exit:
            clear_pwm(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smart fan daemon for Fujitsu iRMC S5 OEM PWM control.")
    parser.add_argument("--ipmitool", default="ipmitool")
    parser.add_argument("--sensors", default="sensors")
    parser.add_argument("-I", "--interface", default="open")
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--min-apply-interval", type=float, default=20.0)
    parser.add_argument("--min-pwm", type=int, default=30)
    parser.add_argument("--max-pwm", type=int, default=100)
    parser.add_argument("--step-up", type=int, default=20)
    parser.add_argument("--step-down", type=int, default=5)
    parser.add_argument("--down-hysteresis", type=int, default=5)
    parser.add_argument("--missing-sensor-pwm", type=int, default=60)
    parser.add_argument("--fail-pwm", type=int, default=70)
    parser.add_argument("--clear-on-exit", action="store_true")
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument("--mlx-chip", default="mlx5-pci-0200")
    parser.add_argument("--mlx-label", default="sensor0")
    parser.add_argument("--mlx2-chip", default="mlx5-pci-0201")
    parser.add_argument("--mlx2-label", default="sensor0")
    parser.add_argument("--cpu-chip", default="coretemp-isa-0000")
    parser.add_argument("--cpu-label", default="Package id 0")
    parser.add_argument("--pch-chip", default="pch_cannonlake-virtual-0")
    parser.add_argument("--pch-label", default="temp1")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.min_pwm < 0 or args.max_pwm > 100 or args.min_pwm > args.max_pwm:
        raise SystemExit("invalid PWM bounds")
    daemon(args)


if __name__ == "__main__":
    main()
