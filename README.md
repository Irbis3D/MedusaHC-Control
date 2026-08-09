# MedusaHC Control

Experimental local control, calibration and diagnostics dashboard for
MedusaHC, Klipper and Moonraker. It runs beside Mainsail on a separate port and
keeps its statistics locally in SQLite.

The dashboard is independent of printer size, rack side and tool count. In live
mode it reads the number of tools from `GLOBAL_STATE.variable_max_tool` and
builds the rack, heaters, sensors, settings and statistics dynamically.

Nothing is uploaded by the service. Simulation mode is enabled by default.

## Current prototype features

- Dynamic front/rear dock rack for the configured tool count.
- Active, parked, released and ambiguous tool sensor states.
- Tool selection, parking, cleaning and feeder controls.
- Individual tool temperatures and cooldown.
- XYZ, tap Z, Z Tilt and bed calibration functions.
- Moonraker camera stream next to the dynamically sized live tool rack.
- Per-tool priming, cleaning and offset controls with runtime application,
  confirmed permanent configuration writes and ten-value local history.
- Local print-only tool pickup, parking and failed-change statistics with a
  resettable counting period.
- Conservative movement interlocks while printing or in a sensor error state.
- Optional control token for command endpoints.

## Run locally in simulation mode

Python 3.9 or newer is the only requirement.

```text
python -m medusahc_control --simulate --port 8090
```

Open `http://127.0.0.1:8090`.

## Linux installation

Open an SSH terminal on the CB2 or Raspberry Pi and run:

```text
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash
```

The installer detects the existing Klipper and `printer_data` paths, creates a
backup and asks one question before changing `printer.cfg`. It then adds the
read-only sensor adapter, starts the isolated dashboard service and connects it
to the local Moonraker instance. See `INSTALLER.md` for update, status and
uninstall commands.

## Update

```text
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- update
```

The update keeps the dashboard configuration, statistics, setting history and
installer backups, replaces the application code and restarts the service.

## Uninstall completely

```text
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- uninstall --purge
```

The uninstaller asks for confirmation, removes all installer-owned files and
Klipper integration, purges dashboard data and restarts Klipper. Values that a
user deliberately saved into their own MedusaHC configuration remain user data
and are not reverted automatically.

## Safety status

This is an experimental prototype. Keep Mainsail open, remain near the printer
and test read-only state reporting before enabling any motion. MedusaHC Control
does not replace Klipper's own safety checks or the printer's emergency stop.
