# MedusaHC Manager (experimental)

`manager.sh` is the local entry point for installing and removing MedusaHC
components. It does not download or publish anything by itself.

## Installation layouts

1. **MedusaHC Control only** keeps the independent interface on port 8090.
2. **Replace Mainsail** backs up the current Mainsail directory, installs the
   prepared MedusaHC Mainsail distribution in its place, and replaces the
   standard Mainsail updater entry with the MedusaHC updater entry.
3. **Parallel Mainsail** keeps the existing Mainsail untouched, installs into
   `~/mainsail-medusahc`, and creates a dedicated nginx site on port 81.

The Mainsail modes require MedusaHC Control to be installed because their tab
opens the same service running on port 8090. The service therefore remains
usable directly if Mainsail is unavailable.

## Moonraker safety

Before every Moonraker write, the manager prints the exact unified diff and
asks for a separate confirmation. There is no menu-wide “yes to everything”.
The updater block is placed directly in `moonraker.conf` between managed
markers; no include file is created.

The original configuration and Mainsail tree are backed up under
`/var/lib/medusahc-installer/backups`. Removal restores the previous tree and,
in replacement mode, the exact standard Mainsail updater section saved during
installation.

The legacy `install.sh --yes` option does not authorize Moonraker changes.
Non-interactive automation must use the explicit
`--allow-moonraker-changes` option, or leave Moonraker in manual mode.

## Preparing a pinned Mainsail build

The separate `MedusaHC-Mainsail` repository records the tested upstream
version and builds the web release artifact. From that repository:

```text
python3 build_distribution.py mainsail.zip medusahc-mainsail.zip
```

The builder in that repository writes the ZIP plus a `.build.json` file containing source and
output SHA-256 hashes. It never fetches upstream and never uploads a release.
A future `Irbis3D/MedusaHC-Mainsail` release remains a deliberate manual step
after testing. The combined installer stays in this control-panel repository.
