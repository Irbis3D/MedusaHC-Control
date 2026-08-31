# MedusaHC Control

> [!IMPORTANT]
> **[Installation, updates, removal, and manual setup](INSTALLATION.md)**

MedusaHC Control is a local web control panel for a MedusaHC toolchanger. It
runs on the printer host next to Klipper, Moonraker and Mainsail and opens on a
separate port. It does not replace Mainsail: the panel provides one place for
the MedusaHC controls, tool states, settings and calibration commands that are
otherwise spread across macros and configuration files.

MedusaHC Control is part of the [MedusaHC project](https://github.com/Irbis3D/MedusaHC).

## Support the project

https://irbis3d.xyz/

If this project is useful to you, you can support its continued development
through [Patreon](https://patreon.com/Irbis3D), make a one-time contribution at
[Buy Me a Coffee](https://buymeacoffee.com/Irbis3D), or use YouTube Super Thanks
on the [Irbis3D channel](https://youtube.com/@Irbis3D). Support helps fund parts,
testing hardware and the time needed to maintain the project.

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
`_GLOBAL_STATE.variable_max_tool` or the legacy
`GLOBAL_STATE.variable_max_tool` each time it starts and creates the required
tool cards and settings automatically.

Support for different printers and MedusaHC layouts is still being developed.
The panel expects an already installed and working MedusaHC configuration. It
does not yet provide the complete setup wizard planned for future versions.

There is one MedusaHC Control edition. It supports the current Python-based
controller and remains backward compatible with the frozen macro controller.
Hidden configuration macros are detected automatically; users do not need to
rename existing sections. The panel never installs, replaces, or removes the
controller, `MHC_macros.cfg`, or `MHC_variables.cfg`.

## What it can do

- Show the active tool, dock sensors, feeder state and connection state.
- Select and park tools and open or close the feeder.
- Run the configured `TEST_TOOLS` rack test from the manual control panel.
- Set individual tool temperatures and cool tools down.
- Show the Moonraker camera stream.
- Home and move the printer axes.
- Run MedusaHC cleaning, priming and calibration macros.
- Run Z Tilt and common bed calibration commands.
- Change tool offsets and MedusaHC motion, cleaning and priming variables.
- Discover numeric variables from the installed MedusaHC variables file instead
  of requiring one fixed configuration version.
- Start with a ready-to-use layout for the current MedusaHC configuration, then
  hide, add or reorder variables without changing the printer configuration.
- Use comments immediately above variable declarations as descriptions, with
  optional local descriptions in the panel.
- Keep expected settings visible but disabled when a variable is missing,
  instead of failing to load the settings page.
- Apply supported values temporarily during the current Klipper session.
- Convert MedusaHC motion values from mm/s to Klipper feedrates automatically
  when the installed configuration exposes the corresponding runtime variables.
- Restore a temporarily changed value from its current saved configuration.
- Save supported values permanently to the appropriate configuration file
  after a warning and confirmation.
- Keep the ten most recent values entered for each supported setting.
- Keep variables below a `Do not change` marker out of the automatic layout,
  while leaving them available in the variable customizer for advanced use.
- Count tool pickups, parking operations and failed changes during printing.
- Restart Klipper, restart the firmware or reboot the printer host.
- Switch between monitoring mode and active control mode.

Permanent configuration editing is still experimental. Every permanent write
creates a timestamped backup, but you should also keep your own known-good
printer backup.

## Requirements

- An existing Linux Klipper installation with Moonraker and MedusaHC.
- Python 3.9 or newer.
- A working `_GLOBAL_STATE` or legacy `GLOBAL_STATE` MedusaHC macro.
- SSH access with `sudo` permission for installation.

The installer detects common CB2 and Raspberry Pi installations instead of
using paths tied to the `biqu` user.

## Install

MedusaHC Control requires an installed and configured MedusaHC Core. The
installer checks that dependency and stops with a clear message if it is
missing. Install the standalone panel with:

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

## License

Copyright (C) 2026 Irbis3D.

This project is licensed under the GNU General Public License version 3
(GPLv3), the same license as the main MedusaHC project. You may use, modify and
share it, but you must keep the copyright and license notices, provide the
corresponding source code when required, license distributed derivative work
under GPLv3 and state significant changes.

See [LICENSE](LICENSE) for the complete license text.
