# Installed Files and Manual Cleanup

This document is a recovery reference for MedusaHC Control. It lists every
location currently created, modified or removed by `install-online.sh` and
`install.sh`, plus the printer configuration files that the running dashboard
can change only after an explicit user action.

The paths below use the normal Klipper layout. The installer detects the actual
printer user and paths, so `~` means the detected printer user's home directory,
not necessarily `/home/pi` or `/home/biqu`.

## Find the exact paths used on this printer

Before removing anything, read the installation manifest:

```bash
sudo cat /var/lib/medusahc-control/install-state.env
```

This root-owned file records the exact application, Klipper and printer
configuration paths selected during installation. It also records whether each
integration was created by the installer or already existed. Use these values
instead of assuming the default paths on a non-standard installation.

## Files and directories created by the installer

| Path | Purpose | When it is created | Normal uninstall |
| --- | --- | --- | --- |
| `~/medusahc-control/` | Complete Git clone of MedusaHC Control, including application code, web files, documentation, installer files and `.git/` metadata. Python may also create ignored `__pycache__/` files here. | Every installation. The exact path is `APP_DIR` in the manifest. | Removed. |
| `/var/lib/medusahc-control/` | Persistent state directory. | Every installation. | Kept unless uninstall is run with `--purge`. |
| `/var/lib/medusahc-control/config.json` | Dashboard port, Moonraker connection settings, safety options and paths to the database and printer configuration. | Every installation or update. | Kept unless `--purge` is used. |
| `/var/lib/medusahc-control/install-state.env` | Installation manifest used by status, update and uninstall. | Every installation or update. | Kept unless `--purge` is used. |
| `/var/lib/medusahc-control/medusahc-control.db` | SQLite database containing statistics, recent values and the customized variable-panel layout. | On the first dashboard start. | Kept unless `--purge` is used. |
| `/var/lib/medusahc-control/medusahc-control.db-journal` | Temporary SQLite rollback journal. It normally exists only during a database write, but may remain after an interrupted write. | Only when SQLite needs it. | Kept with the state directory unless `--purge` is used. |
| `/var/lib/medusahc-control/backups/install-YYYYMMDD-HHMMSS/` | Snapshot taken before installer integration changes. It always contains `printer.cfg`; depending on what exists and which options were accepted, it can also contain `moonraker.conf`, `moonraker.asvc`, `medusahc_control.cfg`, `medusahc-control-update.cfg` and `mhc_dashboard.py`. A new directory is created on each install or update. | Every installation or update. | Kept unless `--purge` is used. |
| `/var/lib/medusahc-control/backups/MHC_variables.cfg.YYYYMMDD-HHMMSS.NNNNNNNNN.bak` | Backup made immediately before **Save to config** changes `MHC_variables.cfg`. | Only after a permanent variable save from the dashboard. | Kept unless `--purge` is used. |
| `/etc/systemd/system/medusahc-control.service` | Isolated systemd service that starts the dashboard. | Every installation or update. | Removed. |
| `/etc/systemd/system/multi-user.target.wants/medusahc-control.service` | Enablement symlink created by `systemctl enable`. | Every installation. | Removed by `systemctl disable`. |
| `~/klipper/klippy/extras/mhc_dashboard.py` | Symlink to `~/medusahc-control/printer/mhc_dashboard.py`. It provides the read-only Klipper-side dashboard object and pin state. | Only if no file or symlink already exists at this path. The exact path is `ADAPTER_TARGET` in the manifest. | Removed only if the installer recorded it as managed and it is still a symlink. |
| `~/printer_data/config/medusahc_control.cfg` | Small, optional dashboard-only Klipper configuration containing `[mhc_dashboard]`. | Created when `printer.cfg` does not already contain an `[mhc_dashboard]` section, including manual printer-config mode. | Removed when it was installer-managed. |
| `~/printer_data/moonraker.asvc` | Moonraker service authorization list. If missing, it is created before the `medusahc-control` service name is added. | Only when automatic Moonraker Update Manager integration is accepted. | The file is kept; only the exact `medusahc-control` line is removed. |

### Ownership and permissions set by the installer

The application repository is recursively assigned to the detected printer
user and group. The state directory is installed with mode `0750` for that user
and group. `config.json` is root-owned, group-readable (`0640`), while
`install-state.env` is root-only (`0600`). Installer backup directories are
root-only (`0700`). `medusahc_control.cfg` and `moonraker.asvc` are assigned to
the printer user and group with mode `0644`; this also changes the ownership and
mode of an existing `moonraker.asvc` when automatic integration is accepted.
The systemd unit is installed with mode `0644`.

The application clone is intentionally treated as one installation directory.
Its individual tracked files change with releases; the authoritative list for
the installed version is:

```bash
sudo -u PRINTER_USER \
  git -C /home/PRINTER_USER/medusahc-control ls-files
```

If `APP_DIR` in the manifest is not `~/medusahc-control`, substitute that exact
path in both places.

## Components the installer does not create or modify

The current installer does not create a Python virtual environment, install
APT or pip packages, modify nginx or Mainsail, replace Moonraker or Klipper, or
change the installed MedusaHC controller. It never writes `medusahc.py`,
`MHC_macros.cfg` or `MHC_variables.cfg`. It uses the host's `/usr/bin/python3`
and runs the Python package directly from the application Git clone.

## Existing files modified by the installer

### `printer.cfg`

If automatic Klipper integration is accepted, the installer inserts exactly
this marked block before Klipper's `SAVE_CONFIG` marker:

```ini
# >>> MEDUSAHC CONTROL >>>
[include medusahc_control.cfg]
# <<< MEDUSAHC CONTROL <<<
```

No existing macro is rewritten. Everything from this marker to the end of the
file is protected and checked byte for byte:

```ini
#*# <---------------------- SAVE_CONFIG ---------------------->
```

If automatic integration is declined, `printer.cfg` is not changed by the
installer. The installer prints the include line for the user to add manually.

### `moonraker.conf`

If automatic Mainsail update integration is accepted, the installer adds or
refreshes one marked block:

```ini
# >>> MEDUSAHC CONTROL UPDATE MANAGER >>>
[update_manager medusahc-control]
type: git_repo
channel: dev
path: /home/PRINTER_USER/medusahc-control
origin: https://github.com/Irbis3D/MedusaHC-Control.git
primary_branch: main
managed_services: medusahc-control klipper
info_tags:
    desc=Experimental MedusaHC control dashboard
# <<< MEDUSAHC CONTROL UPDATE MANAGER <<<
```

The `path` line contains the actual detected application path. If integration
is declined, `moonraker.conf` is not changed by the installer.

### `moonraker.asvc`

With automatic Moonraker integration, this exact service name is appended if
it is not already present:

```text
medusahc-control
```

The uninstaller removes only lines whose trimmed content is exactly that name.

## Existing files the installer can remove

These are compatibility cleanups for older test installations:

- `~/printer_data/config/medusahc-control-update.cfg` is removed when automatic
  Moonraker integration is installed and is also removed during uninstall. The
  current installer never creates this file.
- `/opt/medusahc-control/` is removed after the current per-user application
  directory is installed, but only when it is a separate legacy directory.
- If `APP_DIR` already exists and is not a Git repository, it is replaced by
  the clean application clone. A Git repository with an unexpected origin or
  local changes causes the installer to stop instead of replacing it.

The legacy `/etc/medusahc-control.json` file is only read as a migration source
when the new state configuration does not exist. The installer does not modify
or delete it.

## Temporary installation files

The one-line bootstrap creates:

```text
/tmp/medusahc-control-install.XXXXXX/
```

It contains the downloaded GitHub archive and extracted installer source. A
shell exit trap removes it after success or a normal error. It may remain after
a power loss or an uncatchable process termination and can then be removed
manually after confirming its exact name.

During a first local installation, a temporary application directory named
`APP_DIR.replacement.PROCESS_ID` can briefly exist. It is normally renamed to
`APP_DIR`; an interrupted installation can leave it behind.

The installer also uses a `mktemp` file while writing the systemd service and
removes it immediately.

## Files changed only by an explicit dashboard action

These are user configuration changes, not automatic installer changes. They
are deliberately not reverted by uninstall.

- **Save to config** for normal MedusaHC variables rewrites the selected value
  in `MHC_variables.cfg`. Before writing, the dashboard creates the timestamped
  backup listed above. An interrupted atomic write may leave a hidden
  `.MHC_variables.cfg.*` temporary file in the same configuration directory.
- **Save to config** for tool offsets sends Klipper's `SAVE_VARIABLE` command.
  Klipper then updates the file configured by the printer's `[save_variables]`
  section. The filename is printer-specific and is not selected by this
  installer.
- **Apply** sends runtime G-code only. It does not edit a configuration file.

If the dashboard was used to save permanent values, restoring or deleting the
panel does not undo those values. Restore the required backup manually or edit
the printer configuration intentionally.

## What a normal uninstall leaves behind

`sudo ./install.sh uninstall` removes the service, application clone, managed
Klipper adapter and managed configuration integration. It intentionally keeps:

```text
/var/lib/medusahc-control/config.json
/var/lib/medusahc-control/install-state.env
/var/lib/medusahc-control/medusahc-control.db
/var/lib/medusahc-control/backups/
```

This allows statistics, panel layout, history, selected port and backups to
survive a reinstall. `sudo ./install.sh uninstall --purge` removes the entire
`/var/lib/medusahc-control/` directory as well.

Neither form reverts permanent changes made from **Save to config**.

## Manual removal after a broken installation

Use this only when the normal uninstaller cannot run. Read the manifest and
copy any required backups off the printer before deleting the state directory.

1. Stop and disable the service:

   ```bash
   sudo systemctl disable --now medusahc-control.service
   ```

2. In the exact `PRINTER_CFG` recorded by the manifest, remove only the block
   between `# >>> MEDUSAHC CONTROL >>>` and
   `# <<< MEDUSAHC CONTROL <<<`. Do not edit anything at or below Klipper's
   `SAVE_CONFIG` marker.

3. Remove `medusahc_control.cfg` only if the manifest says it was managed by
   this installation or its contents are the installer-created section shown
   below:

   ```ini
   # Managed by MedusaHC Control. Remove through: sudo ./install.sh uninstall
   [mhc_dashboard]
   pin_watch: pin_watch io
   ```

4. Remove `ADAPTER_TARGET` only after verifying it is a symlink to this
   installation:

   ```bash
   readlink -f /home/PRINTER_USER/klipper/klippy/extras/mhc_dashboard.py
   ```

   Its resolved path must be
   `/home/PRINTER_USER/medusahc-control/printer/mhc_dashboard.py`. Never delete
   an unrelated regular file at that location.

5. In the exact `MOONRAKER_CFG` recorded by the manifest, remove only the block
   between `# >>> MEDUSAHC CONTROL UPDATE MANAGER >>>` and
   `# <<< MEDUSAHC CONTROL UPDATE MANAGER <<<`.

6. In the exact `MOONRAKER_ASVC` file, remove only the line whose complete
   content is `medusahc-control`. Do not delete the whole file because it can
   authorize other services. If the matching pre-install backup directory has
   no `moonraker.asvc` and the current file has no other entries, the installer
   created it and the now-empty file can also be removed.

7. Remove the service definition and reload systemd:

   ```bash
   sudo rm -f /etc/systemd/system/medusahc-control.service
   sudo systemctl daemon-reload
   ```

8. Remove only the exact `APP_DIR` from the manifest. The default is
   `/home/PRINTER_USER/medusahc-control`; verify the resolved path before using
   a recursive removal command.

9. Restart Klipper and, if the Moonraker files were changed, Moonraker:

   ```bash
   sudo systemctl restart klipper.service
   sudo systemctl restart moonraker.service
   ```

10. After confirming that no backups, statistics or saved panel settings are
    needed, remove `/var/lib/medusahc-control/` to complete a manual purge.

System journal entries from earlier dashboard runs are part of the normal host
logging system. The installer and uninstaller do not erase or manage the
systemd journal.
