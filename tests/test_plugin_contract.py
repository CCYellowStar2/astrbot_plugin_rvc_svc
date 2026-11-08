import unittest
from pathlib import Path


class PluginContractTests(unittest.TestCase):
    def test_plugin_exposes_separator_commands_and_forwards_uvr_choice(self):
        source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")

        self.assertIn('@filter.command("分离模型列表")', source)
        self.assertIn('@filter.command("设置分离模型")', source)
        self.assertIn("uvr_choice=self._get_active_separator_model()", source)


if __name__ == "__main__":
    unittest.main()
