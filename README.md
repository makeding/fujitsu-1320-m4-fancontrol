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
apt install git python3 ipmitool lm-sensors
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

System install:

```bash
git clone https://github.com/makeding/fujitsu-1320-m4-fancontrol.git
cd fujitsu-1320-m4-fancontrol
install -m 0755 irmc_fan.py /usr/local/sbin/irmc_fan.py
install -m 0755 irmc_fan_daemon.py /usr/local/sbin/irmc_fan_daemon.py
install -m 0644 systemd/irmc-fan-daemon.service /etc/systemd/system/irmc-fan-daemon.service
```

No pip, no venv, no Python package install. The project is just two standalone scripts.

## Manual Control

Set all PWM channels to 40%:

```bash
/usr/local/sbin/irmc_fan.py set 40
```

Show fan SDR readings:

```bash
/usr/local/sbin/irmc_fan.py sdr
```

Clear forced PWM and return to iRMC automatic control:

```bash
/usr/local/sbin/irmc_fan.py clear
```

Read force slots:

```bash
/usr/local/sbin/irmc_fan.py read
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
/usr/local/sbin/irmc_fan_daemon.py --interval 10
```

Example output:

```text
2026-06-30 02:04:25 pwm=45% want=45% mlx=81.0C mlx2=81.0C cpu=41.0C pch=59.0C
```

If your sensor names differ:

```bash
/usr/local/sbin/irmc_fan_daemon.py \
  --mlx-chip mlx5-pci-0200 \
  --mlx-label sensor0
```

## systemd

Install as root, then enable the unit:

```bash
systemctl daemon-reload
systemctl enable --now irmc-fan-daemon.service
journalctl -u irmc-fan-daemon.service -f
```

If you install the scripts somewhere else, adjust `ExecStart`.

## Safety

This tool forces PWM directly; it is not changing the official iRMC fan curve. Start with 40% or 35%, watch temperatures, and keep an easy way to run:

```bash
/usr/local/sbin/irmc_fan.py clear
```
