# MedusaHC Control installer

The dashboard is packaged as an isolated local service. It does not modify
Mainsail, nginx or existing MedusaHC macros. With permission, it adds one marked
block directly to `moonraker.conf` so the dashboard appears in the standard
Update Manager.

## Install on an existing working MedusaHC printer

Open an SSH terminal on the printer and run one command:

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash
```

The system may request the normal sudo password. This installer downloads the
Python-controller edition of the panel and never installs, replaces or removes
the MedusaHC controller or its macros.

The installer asks for the web interface port. Press Enter to use `8090`,
or enter another port. It also asks two independent questions: whether it may add its marked include
to `printer.cfg`, and whether it may register the project in `moonraker.conf`
for Mainsail updates. Press Enter to accept each default automatic integration,
or answer `n` to receive the exact manual instructions instead.

After installation, open `http://PRINTER_IP:SELECTED_PORT`.

The installer detects the printer user, `printer_data`, Klipper and the number
of tools. It refuses to continue during an active or paused print. Before
editing either main configuration file, it asks separately whether each managed
include may be added automatically.

Updates reuse the saved port without asking again. For unattended installation,
`--yes` uses port `8090`, and `MEDUSAHC_PORT` selects a different port.

The installer treats everything from Klipper's `SAVE_CONFIG` marker to the end
of `printer.cfg` as protected calibration data. Automatic install and uninstall
verify that this tail remains byte-for-byte identical and abort before writing
if it changes.

The application directory is a clean Git clone owned by the printer user. If
Update Manager integration is accepted, Moonraker manages it as a `git_repo`
extension and restarts both `medusahc-control` and Klipper after an update.

Tool count is never hard-coded by the installer or dashboard. The running panel
reads `GLOBAL_STATE.variable_max_tool` and dynamically creates T0 through the
last configured tool, including heaters, sensors, dock coordinates, tuning
fields, offsets and statistics.

If permission is declined, installation continues in manual mode. The
installer creates `medusahc_control.cfg` and prints the exact include line and
Klipper restart command without changing `printer.cfg`.

For local development packages, extract the archive and run
`sudo bash install.sh`; it uses the same single-question flow.

## Testing from a private repository

Private GitHub repositories require a fine-grained token with read-only
`Contents` permission for this repository. Enter it without storing it in shell
history, then fetch the private bootstrap script through the GitHub API:

```bash
read -rsp "GitHub token: " GH_TOKEN; echo
curl -fsSL \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github.raw+json" \
  "https://api.github.com/repos/Irbis3D/MedusaHC-Control/contents/install-online.sh?ref=main" \
  | sudo env GH_TOKEN="$GH_TOKEN" bash
unset GH_TOKEN
```

The token is used only for the two GitHub downloads performed by this command;
the installer does not write it to the printer configuration or service. Once
the repository becomes public, use the normal token-free installation command.

## Other commands

```bash
./install.sh status
sudo ./install.sh update
sudo ./install.sh uninstall
sudo ./install.sh uninstall --purge
sudo ./install.sh --dry-run
sudo ./install.sh --manual-config
sudo ./install.sh --manual-moonraker
```

Normal uninstall removes the application and its Klipper integration but keeps
local statistics and installer backups. `--purge` removes those persistent
files as well.

The public one-command equivalents are:

```bash
# Update while preserving settings and statistics
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- update

# Remove the application, integration and all dashboard-owned persistent data
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- uninstall --purge
```

## Files owned by the installer

For the complete file-by-file inventory, conditional changes, persistent data,
legacy cleanup and manual recovery procedure, see
[`FILES_AND_MANUAL_CLEANUP.md`](FILES_AND_MANUAL_CLEANUP.md).

- `~/medusahc-control` — clean application Git repository owned by the printer user.
- `/var/lib/medusahc-control` — configuration, statistics, manifest and backups.
- `/etc/systemd/system/medusahc-control.service` — one isolated service.
- `klippy/extras/mhc_dashboard.py` — a symlink to the read-only sensor adapter.
- `printer_data/config/medusahc_control.cfg` — one small Klipper section.
- One marked include block in `printer.cfg`, always inserted before
  `SAVE_CONFIG` and removed by the uninstaller.
- One marked `[update_manager medusahc-control]` block directly in
  `moonraker.conf` and one exact service entry in `printer_data/moonraker.asvc`,
  both removed by the uninstaller.

Permanent changes made through **Save to config** are user data and are not
reverted by uninstall. Each such change has its own timestamped backup in the
dashboard data directory.
