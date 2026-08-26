import unittest

from installer.config_edit import BEGIN, END, plan_install, plan_remove


BASE = """[server]
host: 0.0.0.0

[update_manager mainsail]
type: web
channel: stable
repo: mainsail-crew/mainsail
path: /home/pi/mainsail
"""


class InstallerConfigTests(unittest.TestCase):
    def test_parallel_preserves_standard_updater(self):
        plan = plan_install(BASE, mode="parallel", path="/home/pi/mainsail-medusahc", repository="owner/repo")
        self.assertIn("[update_manager mainsail]", plan.updated)
        self.assertIn("[update_manager medusahc-mainsail]", plan.updated)
        self.assertEqual(plan.removed_standard_updater, "")
        removed = plan_remove(plan.updated)
        self.assertNotIn(BEGIN, removed.updated)
        self.assertIn("[update_manager mainsail]", removed.updated)

    def test_replace_restores_standard_updater(self):
        plan = plan_install(BASE, mode="replace", path="/home/pi/mainsail", repository="owner/repo")
        self.assertNotIn("[update_manager mainsail]", plan.updated)
        self.assertIn("repo: mainsail-crew/mainsail", plan.removed_standard_updater)
        restored = plan_remove(plan.updated, standard_updater=plan.removed_standard_updater)
        self.assertIn("[update_manager mainsail]", restored.updated)
        self.assertNotIn("[update_manager medusahc-mainsail]", restored.updated)

    def test_replanning_replaces_one_managed_block(self):
        first = plan_install(BASE, mode="parallel", path="/old", repository="owner/repo")
        second = plan_install(first.updated, mode="parallel", path="/new", repository="owner/repo")
        self.assertEqual(second.updated.count(BEGIN), 1)
        self.assertEqual(second.updated.count(END), 1)
        self.assertIn("path: /new", second.updated)
        self.assertNotIn("path: /old", second.updated)

    def test_broken_markers_are_rejected(self):
        with self.assertRaises(ValueError):
            plan_install(BASE + BEGIN + "\n", mode="parallel", path="/x", repository="owner/repo")

    def test_unmanaged_medusahc_section_is_rejected(self):
        text = BASE + "\n[update_manager medusahc-mainsail]\ntype: web\n"
        with self.assertRaises(ValueError):
            plan_install(text, mode="parallel", path="/x", repository="owner/repo")


if __name__ == "__main__":
    unittest.main()
