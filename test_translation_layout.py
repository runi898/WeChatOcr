import unittest

from translation_layout import layout_translation_block, layout_translation_lines


def _measure_width(text: str, font_size: int) -> int:
    units = 0
    for ch in text:
        if ch == "\n":
            continue
        units += 2 if ord(ch) > 127 else 1
    return max(1, units) * max(font_size, 1)


def _line_height(font_size: int) -> int:
    return font_size + 6


class TranslationLayoutTests(unittest.TestCase):
    def test_long_translation_reflows_without_vertical_overlap(self):
        result = layout_translation_lines(
            translated_lines=[
                "This translated sentence is intentionally long so it needs multiple wrapped lines.",
                "Second line stays readable.",
            ],
            original_lines=[
                {"text": "row1", "left": 18, "top": 10, "right": 86, "bottom": 30},
                {"text": "row2", "left": 18, "top": 36, "right": 90, "bottom": 56},
            ],
            overlay_width=260,
            overlay_height=120,
            measure_width=_measure_width,
            line_height=_line_height,
        )

        first, second = result.placements
        self.assertGreaterEqual(second.y, first.y + first.actual_height + result.vertical_gap)
        self.assertLessEqual(first.right, 260 - result.padding)
        self.assertLessEqual(second.right, 260 - result.padding)

    def test_reports_required_height_when_translation_overflows_vertically(self):
        result = layout_translation_lines(
            translated_lines=["This translated sentence is long enough to wrap into multiple lines below the selected row."],
            original_lines=[
                {"text": "row1", "left": 18, "top": 10, "right": 74, "bottom": 30},
            ],
            overlay_width=120,
            overlay_height=40,
            measure_width=_measure_width,
            line_height=_line_height,
        )

        self.assertGreater(result.required_height, 40)
        self.assertEqual(result.required_height, result.placements[0].bottom + result.padding)

    def test_right_edge_translation_uses_more_than_original_box_width(self):
        result = layout_translation_lines(
            translated_lines=["A much wider translated segment"],
            original_lines=[
                {"text": "edge", "left": 170, "top": 12, "right": 204, "bottom": 32},
            ],
            overlay_width=220,
            overlay_height=80,
            measure_width=_measure_width,
            line_height=_line_height,
        )

        placement = result.placements[0]
        self.assertGreater(placement.render_width, 34)
        self.assertLess(placement.x, 170)
        self.assertLessEqual(placement.right, 220 - result.padding)

    def test_fallback_block_layout_stays_inside_overlay(self):
        result = layout_translation_block(
            text="Merged translation output that should wrap inside the selected overlay area.",
            original_lines=[
                {"text": "a", "left": 110, "top": 14, "right": 182, "bottom": 34},
                {"text": "b", "left": 112, "top": 40, "right": 184, "bottom": 60},
            ],
            overlay_width=220,
            overlay_height=100,
            measure_width=_measure_width,
            line_height=_line_height,
        )

        placement = result.placements[0]
        self.assertLessEqual(placement.right, 220 - result.padding)
        self.assertLessEqual(placement.bottom, 100 - result.padding)
        self.assertGreater(placement.render_width, 72)


if __name__ == "__main__":
    unittest.main()
