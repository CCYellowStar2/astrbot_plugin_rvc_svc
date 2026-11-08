import unittest

from astrbot_plugin_rvc_svc.main import format_elapsed_seconds


class DurationTests(unittest.TestCase):
    def test_formats_seconds_below_one_minute(self):
        self.assertEqual(format_elapsed_seconds.__module__, "astrbot_plugin_rvc_svc.main")
        self.assertEqual(format_elapsed_seconds(12.4), "12 秒")

    def test_formats_minutes_and_zero_padded_seconds(self):
        self.assertEqual(format_elapsed_seconds(61.2), "1 分 01 秒")


if __name__ == "__main__":
    unittest.main()
