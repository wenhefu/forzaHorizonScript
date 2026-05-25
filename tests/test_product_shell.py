import unittest

from modes import MODE_BACKGROUND, MODE_COMBO, MODE_FOREGROUND, MODE_SKILL_POINTS, debug_modes, product_modes
from settings import RuntimeSettings


class ProductShellTests(unittest.TestCase):
    def test_product_modes_do_not_expose_debug_modes(self):
        product_ids = [mode.mode_id for mode in product_modes()]
        debug_ids = [mode.mode_id for mode in debug_modes()]

        self.assertIn(MODE_SKILL_POINTS, product_ids)
        self.assertIn(MODE_COMBO, product_ids)
        self.assertNotIn(MODE_FOREGROUND, product_ids)
        self.assertNotIn(MODE_BACKGROUND, product_ids)
        self.assertEqual([MODE_FOREGROUND, MODE_BACKGROUND], debug_ids)

    def test_runtime_settings_freezes_total_seconds(self):
        settings = RuntimeSettings(
            mode_id=MODE_COMBO,
            startup_delay=5.0,
            drive_seconds=180.0,
            total_minutes=1.5,
            keep_active=False,
            auto_focus=True,
            no_activate=True,
            require_foreground=True,
            resume_after_focus=False,
        )

        self.assertEqual(90.0, settings.total_seconds)
        self.assertIsNone(
            RuntimeSettings(
                mode_id=MODE_COMBO,
                startup_delay=5.0,
                drive_seconds=180.0,
                total_minutes=0.0,
                keep_active=False,
                auto_focus=True,
                no_activate=True,
                require_foreground=True,
                resume_after_focus=False,
            ).total_seconds
        )


if __name__ == "__main__":
    unittest.main()
