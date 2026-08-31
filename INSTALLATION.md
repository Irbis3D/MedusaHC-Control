# MedusaHC Control installation

MedusaHC Control is an optional standalone web panel. It requires an installed
and configured MedusaHC Core. MedusaHC Mainsail is optional and is installed
separately.

> [!WARNING]
> Do not install, update, remove, or restart printer services during a print.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash
```

The installer:

1. Detects the printer user, Klipper, and `printer_data` paths.
2. Verifies the MedusaHC Core dependency.
3. Installs the panel application under the printer user's home directory.
4. Installs and starts the `medusahc-control` systemd service.
5. Installs the Klipper dashboard adapter.
6. Asks before adding the panel include to `printer.cfg`.
7. Separately asks before adding its Update Manager block directly to
   `moonraker.conf`.
8. Asks which web port to use; the default is `8090`.

Changes to printer and Moonraker configuration are marked and backed up. The
installer does not install or modify MedusaHC Mainsail.

## Status

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- status
```

## Update

The preferred method is the normal Mainsail/Fluidd Update Manager. A manual
update is also available:

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- update
```

Panel configuration, statistics, saved settings, and installer backups are
preserved.

## Uninstall and keep data

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- uninstall
```

This removes the service, application, Klipper adapter, and installer-managed
configuration entries. Panel data in `/var/lib/medusahc-control` is preserved
so the panel can be reinstalled without losing its state. User values written
to the MedusaHC configuration are not rolled back.

MedusaHC Mainsail must be removed first. The uninstaller refuses to leave its
embedded panel tab pointing to a removed service.

## Complete removal

```bash
curl -fsSL https://raw.githubusercontent.com/Irbis3D/MedusaHC-Control/main/install-online.sh | sudo bash -s -- uninstall --purge
```

In addition to normal removal, `--purge` deletes panel-owned persistent data,
including statistics, settings, and installer state. This does not delete
MedusaHC Core or its printer configuration.

## Local installation and overrides

From a clone:

```bash
sudo bash install.sh install
```

Common overrides are `MEDUSAHC_USER`, `MEDUSAHC_CONFIG_DIR`,
`MEDUSAHC_KLIPPER_DIR`, and `MEDUSAHC_PORT`. Advanced options and recovery
details are documented in [INSTALLER.md](INSTALLER.md).
