# MedusaHC Control

MedusaHC Control is a local web control panel for a MedusaHC toolchanger. It
runs on the printer host next to Klipper, Moonraker and Mainsail and opens on a
separate port. It does not replace Mainsail: the panel provides one place for
the MedusaHC controls, tool states, settings and calibration commands that are
otherwise spread across macros and configuration files.

MedusaHC Control is part of the [MedusaHC project](https://github.com/Irbis3D/MedusaHC).

> [!WARNING]
> This project is experimental and is not yet intended for unattended use. It
> was created with extensive AI assistance ("vibe coding") and has not been
> tested on every printer configuration. Use it at your own risk. Keep a
> working backup, keep Mainsail available and stay near the printer when
> testing motion or tool changes. I cannot guarantee that the current version
> will not cause configuration errors or unexpected printer behavior.

## Current stage

This is an early working prototype. It has been tested on a DuCR10 with six
rear-mounted MedusaHC tools, but the interface itself is not limited to six
tools. It reads the configured tool count from
`GLOBAL_STATE.variable_max_tool` each time it starts and creates the required
tool cards and settings automatically.

Support for different printers and MedusaHC layouts is still being developed.
The panel expects an already installed and working MedusaHC configuration. It
does not yet provide the complete setup wizard planned for future versions.

## What it can do

- Show the active tool, dock sensors, feeder state and connection state.
- Select and park tools and open or close the feeder.
- Set individual tool temperatures and cool tools down.
- Show the Moonraker camera stream.
- Home and move the printer axes.
- Run MedusaHC cleaning, priming and calibration macros.
- Run Z Tilt and common bed calibration commands.
- Change tool offsets and MedusaHC motion, cleaning and priming variables.
- Apply supported values temporarily during the current Klipper session.
- Save supported values permanently to the appropriate configuration file
  after a warning and confirmation.
- Keep the ten most recent values entered for each supported setting.
- Count tool pickups, parking operations and failed changes during printing.
- Restart Klipper, restart the firmware or reboot the printer host.
- Switch between monitoring mode and active control mode.

Permanent configuration editing is still experimental. Every permanent write
creates a timestamped backup, but you should also keep your own known-good
printer backup.

## Requirements

- An existing Linux Klipper installation with Moonraker and MedusaHC.
- Python 3.9 or newer.
- A working `GLOBAL_STATE` MedusaHC macro.
- SSH access with `sudo` permission for installation.

The installer detects common CB2 and Raspberry Pi installations instead of
using paths tied to the `biqu` user.

## Install

Open an SSH terminal on the printer and run:

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash
```

The installer finds the Klipper and `printer_data` directories and creates a
backup. It asks which web interface port to use; press Enter to use the default
port `8090`, or enter another port. It then asks before adding the MedusaHC
Control include to `printer.cfg` and before adding the project to Moonraker
Update Manager. If you decline either configuration change, it prints the lines
and commands required to finish that part manually.

The installer never intentionally writes inside Klipper's generated
`SAVE_CONFIG` section. It checks that the complete section remains unchanged
before saving `printer.cfg`.

After installation, open:

```text
http://PRINTER_IP:SELECTED_PORT
```

Start with monitoring mode and check that the number of tools, temperatures and
sensor states are correct before enabling control.

## Update

If Moonraker integration was enabled during installation, update **MedusaHC
Control** from the normal Update Manager page in Mainsail.

The SSH update command is also available:

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- update
```

Updates keep the panel configuration, statistics, recent setting values and
installer backups.

## Uninstall

To remove the panel and all data created by it:

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- uninstall --purge
```

The uninstaller removes the service, application files and installer-managed
Klipper and Moonraker entries. Values deliberately saved into the user's own
MedusaHC configuration remain user configuration and are not silently rolled
back.

More installation, manual configuration and recovery commands are described in
[INSTALLER.md](INSTALLER.md).

## Run on a computer without a printer

The built-in simulator can be used for interface development:

```text
python -m medusahc_control --simulate --port 8090
```

Then open `http://127.0.0.1:8090`.

## Support the projects

- [Patreon](https://patreon.com/Irbis3D)
- [Buy Me a Coffee](https://buymeacoffee.com/Irbis3D)
- [YouTube](https://youtube.com/@Irbis3D)

## License

Copyright (C) 2026 Irbis3D.

This project is licensed under the GNU General Public License version 3
(GPLv3), the same license as the main MedusaHC project. You may use, modify and
share it, but you must keep the copyright and license notices, provide the
corresponding source code when required, license distributed derivative work
under GPLv3 and state significant changes.

See [LICENSE](LICENSE) for the complete license text.
