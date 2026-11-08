import unittest
from pathlib import Path


class DurationContractTests(unittest.TestCase):
    def test_plugin_measures_and_reports_successful_cover_duration(self):
        source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")

        self.assertIn("import time", source)
        self.assertIn("started_at = time.perf_counter()", source)
        self.assertIn("format_elapsed_seconds(time.perf_counter() - started_at)", source)
        self.assertIn("✅ 翻唱完成，总用时：", source)

    def test_plugin_sends_duration_before_background_audio_upload(self):
        source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")

        duration_position = source.index('await event.send(event.plain_result(f"✅ 翻唱完成，总用时：{elapsed}"))')
        background_position = source.index("asyncio.create_task(self._send_result_audio(")
        self.assertLess(duration_position, background_position)
        self.assertIn("self._background_tasks", source)


if __name__ == "__main__":
    unittest.main()
