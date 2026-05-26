import subprocess
import sys
import unittest


class GamepadLazyImportTests(unittest.TestCase):
    def test_app_controller_import_does_not_load_vgamepad(self):
        code = "import sys; import app_controller; print('vgamepad' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "False")


if __name__ == "__main__":
    unittest.main()
