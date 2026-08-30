import unittest

from installer.manager import (
    NGINX_BEGIN,
    RELEASE_ASSET,
    add_panel_proxy,
    release_asset_url,
    remove_panel_proxy,
)


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

    def test_panel_proxy_round_trip(self):
        original = "server {\n    listen 80;\n    location / { try_files $uri /index.html; }\n}\n"
        installed = add_panel_proxy(original, 8090)
        self.assertIn(NGINX_BEGIN, installed)
        self.assertIn("proxy_pass http://127.0.0.1:8090;", installed)
        self.assertEqual(add_panel_proxy(installed, 8090), installed)
        self.assertEqual(remove_panel_proxy(installed), original)


if __name__ == "__main__":
    unittest.main()
