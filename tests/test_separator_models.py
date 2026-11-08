import unittest

from separator_models import (
    extract_separator_models,
    format_separator_models,
    resolve_separator_model,
)


class SeparatorModelTests(unittest.TestCase):
    def test_extracts_values_from_uvr_component(self):
        config = {
            "components": [
                {
                    "props": {
                        "label": "人声分离模型 (UVR)",
                        "choices": [
                            ["HP5", "VR-HP5 (默认)"],
                            ["MSST", "MSST BS-Roformer"],
                        ],
                    }
                }
            ]
        }

        self.assertEqual(
            extract_separator_models(config),
            ["VR-HP5 (默认)", "MSST BS-Roformer"],
        )

    def test_resolve_falls_back_to_first_available_model(self):
        self.assertEqual(
            resolve_separator_model(["VR-HP5 (默认)"], "removed model"),
            ("VR-HP5 (默认)", True),
        )

    def test_format_marks_current_model(self):
        result = format_separator_models(
            ["VR-HP5 (默认)", "MSST BS-Roformer"],
            "MSST BS-Roformer",
        )

        self.assertIn("2. MSST BS-Roformer（当前）", result)


if __name__ == "__main__":
    unittest.main()
