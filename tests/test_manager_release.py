import unittest
from unittest.mock import patch

from installer import manager
from installer.manager import RELEASE_ASSET, release_asset_url


class ReleaseSelectionTests(unittest.TestCase):
    def test_selects_named_release_asset(self):
        release = {
            "tag_name": "v1",
            "assets": [
                {"name": "source.zip", "browser_download_url": "wrong"},
                {"name": RELEASE_ASSET, "browser_download_url": "https://example.invalid/right"},
            ],
        }
        self.assertEqual(release_asset_url(release), ("https://example.invalid/right", "v1"))

    def test_missing_asset_fails(self):
        with self.assertRaises(SystemExit):
            release_asset_url({"tag_name": "v1", "assets": []})


class CoreCommandTests(unittest.TestCase):
    @patch.object(manager, "require_root")
    @patch.object(manager.subprocess, "run")
    def test_install_invokes_shell_explicitly(self, run, _require_root):
        manager.core_install()
        run.assert_called_once_with(
            ["bash", str(manager.ROOT / "install.sh"), "install"], check=True
        )

    @patch.object(manager, "load_manifest", return_value={"mainsail": {"installed": False}})
    @patch.object(manager, "require_root")
    @patch.object(manager.subprocess, "run")
    def test_uninstall_invokes_shell_explicitly(self, run, _require_root, _manifest):
        manager.core_uninstall(purge=True)
        run.assert_called_once_with(
            ["bash", str(manager.ROOT / "install.sh"), "uninstall", "--purge"], check=True
        )


if __name__ == "__main__":
    unittest.main()
