#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
import urllib.request
from pathlib import Path

try:
    import pwd
except ImportError:  # Allows local Windows syntax/help checks; installation is Linux-only.
    pwd = None

try:
    from .config_edit import plan_install, plan_remove
except ImportError:
    from config_edit import plan_install, plan_remove


ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("MEDUSAHC_INSTALLER_STATE", "/var/lib/medusahc-installer"))
MANIFEST = STATE / "manifest.json"
REPOSITORY = "Irbis3D/MedusaHC-Mainsail"
PARALLEL_PORT = 81
RELEASE_ASSET = "medusahc-mainsail.zip"


def fail(message: str) -> None:
    raise SystemExit(f"[MedusaHC Manager] ERROR: {message}")


def printer_user():
    if pwd is None:
        fail("The installer can only run on Linux")
    override = os.environ.get("MEDUSAHC_USER")
    name = override or (os.environ.get("SUDO_USER") if os.environ.get("SUDO_USER") != "root" else None)
    if name:
        return pwd.getpwnam(name)
    candidates = list(Path("/home").glob("*/printer_data/config/printer.cfg"))
    if len(candidates) != 1:
        fail("Cannot uniquely detect printer user; set MEDUSAHC_USER")
    return pwd.getpwuid(candidates[0].stat().st_uid)


def paths() -> dict[str, Path]:
    user = printer_user()
    home = Path(user.pw_dir)
    return {
        "home": home,
        "moonraker": home / "printer_data/config/moonraker.conf",
        "standard": home / "mainsail",
        "parallel": home / "mainsail-medusahc",
        "nginx_available": Path("/etc/nginx/sites-available/medusahc-mainsail"),
        "nginx_enabled": Path("/etc/nginx/sites-enabled/medusahc-mainsail"),
    }


def load_manifest() -> dict:
    if not MANIFEST.is_file():
        return {"schema": 1, "mainsail": {"installed": False}, "backups": []}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def save_manifest(data: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = MANIFEST.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(MANIFEST)


def atomic_write(path: Path, content: str) -> None:
    stat = path.stat()
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, stat.st_mode)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def require_root() -> None:
    if os.geteuid() != 0:
        fail("Run installation and removal with sudo")


def confirm(prompt: str) -> bool:
    if not sys.stdin.isatty():
        fail("Interactive confirmation is required")
    return input(f"{prompt} [y/N] ").strip().lower() == "y"


def confirm_moonraker(plan, path: Path) -> None:
    print("\nMoonraker configuration change requested:\n")
    print(plan.diff(str(path)) or "(no changes)")
    print("A dated backup will be created before writing and Moonraker will be restarted.")
    if not confirm("Apply exactly this moonraker.conf change?"):
        fail("Moonraker change was not approved; nothing was installed")


def validate_target(target: Path, expected: Path) -> None:
    if target.resolve(strict=False) != expected.resolve(strict=False):
        fail(f"Refusing unexpected Mainsail target: {target}")


def release_asset_url(release: dict) -> tuple[str, str]:
    tag = str(release.get("tag_name", "")).strip()
    for asset in release.get("assets", []):
        if asset.get("name") == RELEASE_ASSET and asset.get("browser_download_url"):
            return str(asset["browser_download_url"]), tag
    fail(f"Latest {REPOSITORY} release does not contain {RELEASE_ASSET}")


def download_mainsail_release(destination: Path) -> str:
    api = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
    request = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
        url, tag = release_asset_url(release)
        with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as stream:
            shutil.copyfileobj(response, stream)
    except Exception as error:
        fail(f"Cannot download the latest MedusaHC Mainsail release: {error}")
    if not zipfile.is_zipfile(destination):
        fail("Downloaded MedusaHC Mainsail asset is not a valid ZIP archive")
    print(f"Downloaded MedusaHC Mainsail {tag or 'release'}.")
    return tag


def install_latest_mainsail(mode: str) -> None:
    with tempfile.TemporaryDirectory(prefix="medusahc-release-") as temporary:
        archive = Path(temporary) / RELEASE_ASSET
        download_mainsail_release(archive)
        install_mainsail(mode, archive)


def backup(paths_: dict[str, Path], target: Path, mode: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    directory = STATE / "backups" / f"mainsail-{mode}-{stamp}"
    directory.mkdir(parents=True, mode=0o700)
    if target.exists():
        with tarfile.open(directory / "mainsail.tar.gz", "w:gz") as archive:
            archive.add(target, arcname="mainsail", recursive=True)
    shutil.copy2(paths_["moonraker"], directory / "moonraker.conf")
    return directory


def unpack_archive(archive: Path, destination: Path) -> Path:
    staging = destination / "web"
    staging.mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            resolved = (staging / member.filename).resolve()
            if staging.resolve() not in resolved.parents and resolved != staging.resolve():
                fail("Mainsail archive contains an unsafe path")
        package.extractall(staging)
    candidates = [staging] + [item for item in staging.iterdir() if item.is_dir()]
    root = next((item for item in candidates if (item / "index.html").is_file()), None)
    if root is None or not (root / "mainsail-medusahc.js").is_file():
        fail("Archive is not a MedusaHC Mainsail distribution")
    return root


def install_tree(archive: Path, target: Path) -> None:
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="medusahc-install-", dir=parent) as temporary:
        root = unpack_archive(archive, Path(temporary))
        replacement = parent / f".{target.name}.replacement-{os.getpid()}"
        if replacement.exists():
            shutil.rmtree(replacement)
        shutil.copytree(root, replacement)
        if target.exists():
            shutil.rmtree(target)
        replacement.replace(target)


def write_nginx_parallel(target: Path, available: Path, enabled: Path) -> None:
    config = f"""# Managed by MedusaHC Manager
server {{
    listen {PARALLEL_PORT};
    server_name _;
    root {target};
    index index.html;
    location / {{ try_files $uri $uri/ /index.html; }}
    location /websocket {{
        proxy_pass http://127.0.0.1:7125/websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
    location ~ ^/(printer|api|access|machine|server)/ {{
        proxy_pass http://127.0.0.1:7125;
    }}
}}
"""
    if available.exists() and available.read_text(encoding="utf-8") != config:
        fail(f"Refusing to overwrite unrelated nginx configuration: {available}")
    available.write_text(config, encoding="utf-8")
    if enabled.exists() or enabled.is_symlink():
        if enabled.resolve() != available.resolve():
            fail(f"Refusing to replace unrelated nginx entry: {enabled}")
    else:
        enabled.symlink_to(available)
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)


def install_mainsail(mode: str, archive: Path) -> None:
    require_root()
    if mode not in {"replace", "parallel"}:
        fail("Mode must be replace or parallel")
    if not archive.is_file():
        fail(f"Archive not found: {archive}")
    p = paths()
    existing = load_manifest().get("mainsail", {})
    if existing.get("installed"):
        fail("MedusaHC Mainsail is already installed; remove it before changing installation mode")
    if not (p["home"] / "medusahc-control").is_dir():
        fail("Install MedusaHC Control first; the Mainsail tab connects to its web service")
    if not p["moonraker"].is_file():
        fail(f"moonraker.conf not found: {p['moonraker']}")
    target = p["standard"] if mode == "replace" else p["parallel"]
    validate_target(target, p["standard"] if mode == "replace" else p["parallel"])
    moonraker_text = p["moonraker"].read_text(encoding="utf-8")
    plan = plan_install(moonraker_text, mode=mode, path=str(target), repository=REPOSITORY)
    confirm_moonraker(plan, p["moonraker"])
    summary = (
        f"Install MedusaHC Mainsail in {mode} mode at {target}. "
        f"{'Configure nginx port 81.' if mode == 'parallel' else 'Replace the main Mainsail files.'}"
    )
    if not confirm(summary):
        fail("Installation cancelled")
    backup_dir = backup(p, target, mode)
    moonraker_changed = False
    try:
        install_tree(archive.resolve(), target)
        if mode == "parallel":
            write_nginx_parallel(target, p["nginx_available"], p["nginx_enabled"])
        atomic_write(p["moonraker"], plan.updated)
        moonraker_changed = True
        subprocess.run(["systemctl", "restart", "moonraker"], check=True)
    except Exception:
        if mode == "parallel":
            remove_parallel_nginx(p, reload=False)
        restore_tree(backup_dir, target)
        if moonraker_changed:
            atomic_write(p["moonraker"], (backup_dir / "moonraker.conf").read_text(encoding="utf-8"))
            subprocess.run(["systemctl", "restart", "moonraker"], check=False)
        raise
    manifest = load_manifest()
    manifest["mainsail"] = {
        "installed": True,
        "mode": mode,
        "path": str(target),
        "archive": str(archive.resolve()),
        "backup": str(backup_dir),
        "standard_updater": plan.removed_standard_updater,
        "parallel_port": PARALLEL_PORT if mode == "parallel" else None,
    }
    manifest.setdefault("backups", []).append(str(backup_dir))
    save_manifest(manifest)
    print(f"MedusaHC Mainsail installed in {mode} mode.")


def safe_extract_tar(package: tarfile.TarFile, destination: Path) -> None:
    destination_resolved = destination.resolve()
    for member in package.getmembers():
        resolved = (destination / member.name).resolve()
        if destination_resolved not in resolved.parents and resolved != destination_resolved:
            fail("Backup archive contains an unsafe path")
        if member.issym() or member.islnk():
            fail("Backup archive contains a link and cannot be restored safely")
    package.extractall(destination)


def restore_tree(backup_dir: Path, target: Path) -> None:
    archive = backup_dir / "mainsail.tar.gz"
    if target.exists():
        shutil.rmtree(target)
    if archive.is_file():
        with tarfile.open(archive) as package:
            safe_extract_tar(package, target.parent)
        extracted = target.parent / "mainsail"
        if extracted != target:
            extracted.replace(target)


def remove_parallel_nginx(p: dict[str, Path], *, reload: bool = True) -> None:
    available = p["nginx_available"]
    enabled = p["nginx_enabled"]
    if enabled.is_symlink() and enabled.resolve() == available.resolve():
        enabled.unlink()
    if available.is_file():
        text = available.read_text(encoding="utf-8")
        if not text.startswith("# Managed by MedusaHC Manager\n"):
            fail(f"Refusing to remove unrelated nginx configuration: {available}")
        available.unlink()
    if reload:
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)


def uninstall_mainsail() -> None:
    require_root()
    manifest = load_manifest()
    item = manifest.get("mainsail", {})
    if not item.get("installed"):
        fail("MedusaHC Mainsail is not installed according to the manifest")
    p = paths()
    mode = item["mode"]
    target = Path(item["path"])
    expected = p["standard"] if mode == "replace" else p["parallel"]
    validate_target(target, expected)
    plan = plan_remove(
        p["moonraker"].read_text(encoding="utf-8"),
        standard_updater=item.get("standard_updater", ""),
    )
    confirm_moonraker(plan, p["moonraker"])
    if not confirm(f"Remove MedusaHC Mainsail from {target} and restore its backup?"):
        fail("Removal cancelled")
    if mode == "parallel":
        remove_parallel_nginx(p)
    restore_tree(Path(item["backup"]), target)
    atomic_write(p["moonraker"], plan.updated)
    subprocess.run(["systemctl", "restart", "moonraker"], check=True)
    manifest["mainsail"] = {"installed": False}
    save_manifest(manifest)
    print("MedusaHC Mainsail removed and the previous state restored.")


def core_install() -> None:
    require_root()
    subprocess.run(["bash", str(ROOT / "install.sh"), "install"], check=True)


def core_uninstall(purge: bool = False) -> None:
    require_root()
    manifest = load_manifest()
    if manifest.get("mainsail", {}).get("installed"):
        fail("Remove MedusaHC Mainsail before removing MedusaHC Control")
    command = ["bash", str(ROOT / "install.sh"), "uninstall"]
    if purge:
        command.append("--purge")
    subprocess.run(command, check=True)


def status() -> None:
    p = paths()
    manifest = load_manifest()
    print("MedusaHC Control:", "installed" if (p["home"] / "medusahc-control").is_dir() else "not installed")
    print("Standard Mainsail:", "present" if p["standard"].is_dir() else "not present")
    print("MedusaHC Mainsail:", json.dumps(manifest.get("mainsail", {}), indent=2))


def menu() -> None:
    while True:
        print("""
MedusaHC Manager
1) Install MedusaHC Control
2) Replace main Mainsail with MedusaHC Mainsail
3) Install MedusaHC Mainsail in parallel
4) Status
5) Remove MedusaHC Mainsail
6) Remove MedusaHC Control (keep data)
7) Exit
""")
        choice = input("Select: ").strip()
        if choice == "1":
            core_install()
        elif choice in {"2", "3"}:
            install_latest_mainsail("replace" if choice == "2" else "parallel")
        elif choice == "4":
            status()
        elif choice == "5":
            uninstall_mainsail()
        elif choice == "6":
            core_uninstall()
        elif choice == "7":
            return
        else:
            print("Unknown selection.")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("status")
    install = sub.add_parser("install-mainsail")
    install.add_argument("--mode", required=True, choices=("replace", "parallel"))
    install.add_argument("--archive", type=Path)
    sub.add_parser("uninstall-mainsail")
    args = parser.parse_args()
    if args.action is None:
        menu()
    elif args.action == "status":
        status()
    elif args.action == "install-mainsail":
        if args.archive:
            install_mainsail(args.mode, args.archive)
        else:
            install_latest_mainsail(args.mode)
    elif args.action == "uninstall-mainsail":
        uninstall_mainsail()


if __name__ == "__main__":
    main()
