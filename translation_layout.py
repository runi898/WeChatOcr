from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

MeasureWidth = Callable[[str, int], int]
LineHeight = Callable[[int], int]


@dataclass(frozen=True)
class TextPlacement:
    text: str
    x: int
    y: int
    font_size: int
    render_width: int
    actual_width: int
    actual_height: int
    anchor: str
    wrapped: bool
    source_box: tuple[int, int, int, int]
    original_text: str = ""

    @property
    def right(self) -> int:
        return self.x + self.actual_width

    @property
    def bottom(self) -> int:
        return self.y + self.actual_height


@dataclass(frozen=True)
class LayoutResult:
    placements: list[TextPlacement]
    padding: int
    vertical_gap: int

    @property
    def content_bottom(self) -> int:
        return max((placement.bottom for placement in self.placements), default=self.padding)

    @property
    def required_height(self) -> int:
        return self.content_bottom + self.padding


@dataclass(frozen=True)
class _SourceLine:
    left: int
    top: int
    right: int
    bottom: int
    width: int
    height: int
    original_text: str


@dataclass(frozen=True)
class _MeasuredBlock:
    width: int
    height: int
    line_count: int


DEFAULT_PADDING = 8
DEFAULT_VERTICAL_GAP = 4
MIN_FONT = 9
MAX_FONT = 28


def layout_translation_lines(
    translated_lines: Sequence[str],
    original_lines: Sequence[dict],
    overlay_width: int,
    overlay_height: int,
    measure_width: MeasureWidth,
    line_height: LineHeight,
    dpi_scale: tuple[float, float] = (1.0, 1.0),
    padding: int = DEFAULT_PADDING,
    vertical_gap: int = DEFAULT_VERTICAL_GAP,
    min_font: int = MIN_FONT,
    max_font: int = MAX_FONT,
) -> LayoutResult:
    sources = _normalize_lines(original_lines, dpi_scale)
    placements: list[TextPlacement] = []
    next_y = padding

    for index, source in enumerate(sources):
        text = translated_lines[index].strip()
        placement = _layout_line(
            text=text,
            source=source,
            next_source_top=sources[index + 1].top if index + 1 < len(sources) else None,
            next_y=next_y,
            overlay_width=overlay_width,
            overlay_height=overlay_height,
            measure_width=measure_width,
            line_height=line_height,
            padding=padding,
            vertical_gap=vertical_gap,
            min_font=min_font,
            max_font=max_font,
        )
        placements.append(placement)
        next_y = placement.bottom + vertical_gap

    return LayoutResult(placements=placements, padding=padding, vertical_gap=vertical_gap)


def layout_translation_block(
    text: str,
    original_lines: Sequence[dict],
    overlay_width: int,
    overlay_height: int,
    measure_width: MeasureWidth,
    line_height: LineHeight,
    dpi_scale: tuple[float, float] = (1.0, 1.0),
    padding: int = DEFAULT_PADDING,
    vertical_gap: int = DEFAULT_VERTICAL_GAP,
    min_font: int = MIN_FONT,
    max_font: int = 24,
) -> LayoutResult:
    sources = _normalize_lines(original_lines, dpi_scale)
    left = min(line.left for line in sources)
    top = min(line.top for line in sources)
    right = max(line.right for line in sources)
    bottom = max(line.bottom for line in sources)
    width = max(right - left, 100)
    avg_height = int(sum(line.height for line in sources) / max(len(sources), 1))
    font_size = _clamp(int(avg_height * 0.65), 6, max_font)

    placement = _layout_text(
        text=text,
        preferred_x=left,
        preferred_top=top,
        overlay_width=overlay_width,
        overlay_height=overlay_height,
        measure_width=measure_width,
        line_height=line_height,
        padding=padding,
        min_font=min_font,
        max_font=font_size,
        preferred_width=width,
        max_bottom=overlay_height - padding,
        source_box=(left, top, right, bottom),
    )
    return LayoutResult(placements=[placement], padding=padding, vertical_gap=vertical_gap)


def _layout_line(
    text: str,
    source: _SourceLine,
    next_source_top: int | None,
    next_y: int,
    overlay_width: int,
    overlay_height: int,
    measure_width: MeasureWidth,
    line_height: LineHeight,
    padding: int,
    vertical_gap: int,
    min_font: int,
    max_font: int,
) -> TextPlacement:
    row_font = _clamp(int(source.height * 0.75), min_font, max_font)
    max_bottom = overlay_height - padding
    if next_source_top is not None:
        max_bottom = min(max_bottom, max(next_source_top - vertical_gap, source.top + source.height))

    return _layout_text(
        text=text,
        preferred_x=source.left,
        preferred_top=max(source.top, next_y),
        overlay_width=overlay_width,
        overlay_height=overlay_height,
        measure_width=measure_width,
        line_height=line_height,
        padding=padding,
        min_font=min_font,
        max_font=row_font,
        preferred_width=source.width,
        max_bottom=max_bottom,
        source_box=(source.left, source.top, source.right, source.bottom),
        original_text=source.original_text,
        center_single_line=source.height >= line_height(row_font),
        original_mid_y=(source.top + source.bottom) // 2,
    )


def _layout_text(
    text: str,
    preferred_x: int,
    preferred_top: int,
    overlay_width: int,
    overlay_height: int,
    measure_width: MeasureWidth,
    line_height: LineHeight,
    padding: int,
    min_font: int,
    max_font: int,
    preferred_width: int,
    max_bottom: int,
    source_box: tuple[int, int, int, int],
    original_text: str = "",
    center_single_line: bool = False,
    original_mid_y: int | None = None,
) -> TextPlacement:
    content_limit = max(40, overlay_width - padding * 2)
    target_top = _clamp(preferred_top, padding, overlay_height - padding)
    chosen: TextPlacement | None = None

    for font_size in range(max_font, min_font - 1, -1):
        single = _measure_block(text, font_size, None, measure_width, line_height)
        if single.width <= content_limit:
            single_x = _fit_x(preferred_x, single.width, overlay_width, padding)
            single_y = target_top
            if center_single_line and original_mid_y is not None:
                centered_top = original_mid_y - (single.height // 2)
                single_y = max(target_top, centered_top)
            if single_y + single.height <= max_bottom:
                chosen = TextPlacement(
                    text=text,
                    x=single_x,
                    y=single_y,
                    font_size=font_size,
                    render_width=single.width,
                    actual_width=single.width,
                    actual_height=single.height,
                    anchor="w" if center_single_line else "nw",
                    wrapped=False,
                    source_box=source_box,
                    original_text=original_text,
                )
                if center_single_line:
                    return chosen

        wrap_width = max(preferred_width, min(content_limit, max(preferred_width, single.width)))
        wrapped = _measure_block(text, font_size, wrap_width, measure_width, line_height)
        wrapped_x = _fit_x(preferred_x, min(wrap_width, wrapped.width), overlay_width, padding)
        wrapped_y = target_top
        candidate = TextPlacement(
            text=text,
            x=wrapped_x,
            y=wrapped_y,
            font_size=font_size,
            render_width=wrap_width,
            actual_width=min(wrap_width, wrapped.width),
            actual_height=wrapped.height,
            anchor="nw",
            wrapped=True,
            source_box=source_box,
            original_text=original_text,
        )
        if wrapped_y + wrapped.height <= max_bottom:
            return candidate

        chosen = _pick_better_candidate(chosen, candidate, max_bottom)

    if chosen is not None:
        return chosen

    fallback = _measure_block(text, min_font, content_limit, measure_width, line_height)
    fallback_x = _fit_x(preferred_x, min(content_limit, fallback.width), overlay_width, padding)
    return TextPlacement(
        text=text,
        x=fallback_x,
        y=target_top,
        font_size=min_font,
        render_width=content_limit,
        actual_width=min(content_limit, fallback.width),
        actual_height=fallback.height,
        anchor="nw",
        wrapped=True,
        source_box=source_box,
        original_text=original_text,
    )


def _pick_better_candidate(
    current: TextPlacement | None,
    candidate: TextPlacement,
    max_bottom: int,
) -> TextPlacement:
    if current is None:
        return candidate

    current_overflow = max(0, current.bottom - max_bottom)
    candidate_overflow = max(0, candidate.bottom - max_bottom)
    if candidate_overflow != current_overflow:
        return candidate if candidate_overflow < current_overflow else current
    if candidate.actual_height != current.actual_height:
        return candidate if candidate.actual_height < current.actual_height else current
    return candidate if candidate.font_size < current.font_size else current


def _measure_block(
    text: str,
    font_size: int,
    wrap_width: int | None,
    measure_width: MeasureWidth,
    line_height: LineHeight,
) -> _MeasuredBlock:
    wrapped_lines: list[str] = []
    for raw_line in text.split("\n"):
        wrapped_lines.extend(_wrap_line(raw_line, font_size, wrap_width, measure_width))

    if not wrapped_lines:
        wrapped_lines = [""]

    width = 0
    for line in wrapped_lines:
        width = max(width, measure_width(line, font_size) if line else 0)

    return _MeasuredBlock(
        width=width,
        height=max(1, len(wrapped_lines)) * line_height(font_size),
        line_count=len(wrapped_lines),
    )


def _wrap_line(
    text: str,
    font_size: int,
    wrap_width: int | None,
    measure_width: MeasureWidth,
) -> list[str]:
    if wrap_width is None or not text:
        return [text]
    if measure_width(text, font_size) <= wrap_width:
        return [text]

    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if current and measure_width(candidate, font_size) > wrap_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [text]


def _normalize_lines(original_lines: Sequence[dict], dpi_scale: tuple[float, float]) -> list[_SourceLine]:
    dpi_sx, dpi_sy = dpi_scale
    sources: list[_SourceLine] = []
    for item in original_lines:
        left = int(int(item["left"]) / dpi_sx)
        top = int(int(item["top"]) / dpi_sy)
        right = int(int(item["right"]) / dpi_sx)
        bottom = int(int(item["bottom"]) / dpi_sy)
        sources.append(
            _SourceLine(
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                width=max(right - left, 30),
                height=max(bottom - top, 1),
                original_text=item.get("text", ""),
            )
        )
    return sources


def _fit_x(preferred_x: int, actual_width: int, overlay_width: int, padding: int) -> int:
    return _clamp(preferred_x, padding, max(padding, overlay_width - padding - actual_width))


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(value, upper))
