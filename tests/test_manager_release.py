import unittest

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


if __name__ == "__main__":
    unittest.main()
