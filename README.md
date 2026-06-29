# Fujitsu TX1320 M4 Fan Control

Small helper for controlling fan PWM on a Fujitsu PRIMERGY TX1320 M4 through local iRMC S5 IPMI OEM commands.

Tested environment:

- FUJITSU PRIMERGY TX1320 M4
- iRMC S5 Firmware Revision 3.31P (1.00)
- SDR 3.40

Other iRMC firmware versions and other PRIMERGY models are not guaranteed.

## Dependencies

Runtime tools:

- Python 3.10+
- `ipmitool`
- `lm_sensors` / `sensors` for daemon mode

Debian / Ubuntu:

```bash
apt install git python3 python3-venv ipmitool lm-sensors
sensors-detect
```

NixOS:

```nix
environment.systemPackages = with pkgs; [
  python3
  ipmitool
  lm_sensors
];
```

## Install

Recommended system install on Debian / Ubuntu:

```bash
git clone https://github.com/makeding/fujitsu-1320-m4-fancontrol.git
cd fujitsu-1320-m4-fancontrol
sh scripts/install-system.sh
```

This creates a venv under `/opt/fujitsu-1320-m4-fancontrol` and symlinks commands to `/usr/local/bin`.

Manual venv install without cloning:

```bash
python3 -m venv /opt/fujitsu-1320-m4-fancontrol
/opt/fujitsu-1320-m4-fancontrol/bin/python -m pip install \
  git+https://github.com/makeding/fujitsu-1320-m4-fancontrol.git
ln -sf /opt/fujitsu-1320-m4-fancontrol/bin/irmc-fan /usr/local/bin/irmc-fan
ln -sf /opt/fujitsu-1320-m4-fancontrol/bin/irmc-fan-daemon /usr/local/bin/irmc-fan-daemon
```

Do not use system-wide `pip install` on Debian-like systems with PEP 668 enabled unless you intentionally pass `--break-system-packages`.

## Manual Control

Set all PWM channels to 40%:

```bash
irmc-fan set 40
```

Show fan SDR readings:

```bash
irmc-fan sdr
```

Clear forced PWM and return to iRMC automatic control:

```bash
irmc-fan clear
```

Read force slots:

```bash
irmc-fan read
```

The raw command uses Fujitsu IANA `0x002880`, encoded little-endian as `80 28 00`.

## Smart Daemon

The daemon watches `sensors` output and adjusts PWM automatically. By default it watches:

- `mlx5-pci-0200:sensor0`
- `mlx5-pci-0201:sensor0`
- `coretemp-isa-0000:Package id 0`
- `pch_cannonlake-virtual-0:temp1`

Run manually:

```bash
irmc-fan-daemon --interval 10
```

Example output:

```text
2026-06-30 02:04:25 pwm=45% want=45% mlx=81.0C mlx2=81.0C cpu=41.0C pch=59.0C
```

If your sensor names differ:

```bash
irmc-fan-daemon \
  --mlx-chip mlx5-pci-0200 \
  --mlx-label sensor0
```

## systemd

Install as root, then copy the unit:

```bash
cp systemd/irmc-fan-daemon.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now irmc-fan-daemon.service
journalctl -u irmc-fan-daemon.service -f
```

If `pip` installs scripts somewhere other than `/usr/local/bin`, adjust `ExecStart`.

## Safety

This tool forces PWM directly; it is not changing the official iRMC fan curve. Start with 40% or 35%, watch temperatures, and keep an easy way to run:

```bash
irmc-fan clear
```
