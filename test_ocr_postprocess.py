import unittest

from ocr_postprocess import postprocess_ocr_items


class OcrPostprocessTests(unittest.TestCase):
    def test_merges_english_fragments_with_space(self):
        items = [
            {"text": "Hello", "left": 10, "top": 10, "right": 48, "bottom": 28},
            {"text": "world", "left": 58, "top": 11, "right": 104, "bottom": 28},
        ]

        result = postprocess_ocr_items(items)

        self.assertEqual([line["text"] for line in result.lines], ["Hello world"])
        self.assertEqual(result.text, "Hello world")

    def test_merges_chinese_fragments_without_space(self):
        items = [
            {"text": "微信", "left": 10, "top": 10, "right": 38, "bottom": 30},
            {"text": "截图", "left": 42, "top": 11, "right": 70, "bottom": 30},
        ]

        result = postprocess_ocr_items(items)

        self.assertEqual([line["text"] for line in result.lines], ["微信截图"])
        self.assertEqual(result.text, "微信截图")

    def test_keeps_distant_columns_separate_on_same_row(self):
        items = [
            {"text": "Growth Hacker", "left": 66, "top": 39, "right": 224, "bottom": 61},
            {"text": "Rapid user acquisition, viral loops", "left": 354, "top": 19, "right": 711, "bottom": 44},
            {"text": "experiments", "left": 354, "top": 57, "right": 490, "bottom": 81},
            {"text": "Explosive growth, user acquisition", "left": 809, "top": 22, "right": 1170, "bottom": 44},
            {"text": "conversion optimization", "left": 809, "top": 57, "right": 1070, "bottom": 80},
        ]

        result = postprocess_ocr_items(items)

        self.assertEqual(
            [line["text"] for line in result.lines],
            [
                "Rapid user acquisition, viral loops",
                "Explosive growth, user acquisition",
                "Growth Hacker",
                "experiments",
                "conversion optimization",
            ],
        )

    def test_sorts_lines_top_to_bottom_and_left_to_right(self):
        items = [
            {"text": "second", "left": 80, "top": 42, "right": 132, "bottom": 60},
            {"text": "row", "left": 10, "top": 41, "right": 40, "bottom": 60},
            {"text": "first", "left": 12, "top": 12, "right": 48, "bottom": 30},
        ]

        result = postprocess_ocr_items(items)

        self.assertEqual([line["text"] for line in result.lines], ["first", "row second"])
        self.assertEqual(result.text, "first\nrow second")


if __name__ == "__main__":
    unittest.main()
