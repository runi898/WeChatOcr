from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class OcrPostprocessResult:
    lines: list[dict]
    text: str


@dataclass
class _LineCluster:
    items: list[dict]
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> int:
        return max(1, self.bottom - self.top)

    def add(self, item: dict) -> None:
        self.items.append(item)
        self.left = min(self.left, item["left"])
        self.top = min(self.top, item["top"])
        self.right = max(self.right, item["right"])
        self.bottom = max(self.bottom, item["bottom"])


def postprocess_ocr_items(items: Iterable[dict]) -> OcrPostprocessResult:
    normalized = _normalize_items(items)
    if not normalized:
        return OcrPostprocessResult(lines=[], text="")

    clusters: list[_LineCluster] = []
    for item in sorted(normalized, key=lambda value: (value["top"], value["left"], value["bottom"], value["right"])):
        cluster = _find_cluster(clusters, item)
        if cluster is None:
            clusters.append(
                _LineCluster(
                    items=[item],
                    left=item["left"],
                    top=item["top"],
                    right=item["right"],
                    bottom=item["bottom"],
                )
            )
        else:
            cluster.add(item)

    merged_lines = [_merge_cluster(cluster) for cluster in sorted(clusters, key=lambda line: (line.top, line.left))]
    merged_text = "\n".join(line["text"] for line in merged_lines if line["text"])
    return OcrPostprocessResult(lines=merged_lines, text=merged_text)


def _normalize_items(items: Iterable[dict]) -> list[dict]:
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        normalized.append(
            {
                "text": text,
                "left": int(item.get("left", 0)),
                "top": int(item.get("top", 0)),
                "right": int(item.get("right", 0)),
                "bottom": int(item.get("bottom", 0)),
            }
        )
    return normalized


def _find_cluster(clusters: list[_LineCluster], item: dict) -> _LineCluster | None:
    best: _LineCluster | None = None
    best_distance: float | None = None
    item_center = (item["top"] + item["bottom"]) / 2
    item_height = max(1, item["bottom"] - item["top"])

    for cluster in clusters:
        overlap = min(cluster.bottom, item["bottom"]) - max(cluster.top, item["top"])
        overlap_ratio = overlap / min(cluster.height, item_height) if overlap > 0 else 0
        center_distance = abs(cluster.center_y - item_center)
        threshold = max(8, min(cluster.height, item_height) * 0.45)
        horizontal_gap = _horizontal_gap(cluster, item)
        horizontal_limit = max(24, int(min(cluster.height, item_height) * 2.5))
        if horizontal_gap > horizontal_limit:
            continue
        if overlap_ratio >= 0.45 or center_distance <= threshold:
            if best is None or center_distance < best_distance:
                best = cluster
                best_distance = center_distance
    return best


def _horizontal_gap(cluster: _LineCluster, item: dict) -> int:
    if item["left"] > cluster.right:
        return item["left"] - cluster.right
    if cluster.left > item["right"]:
        return cluster.left - item["right"]
    return 0


def _merge_cluster(cluster: _LineCluster) -> dict:
    items = sorted(cluster.items, key=lambda item: (item["left"], item["top"]))
    parts: list[str] = []
    previous: dict | None = None
    for item in items:
        if previous is not None and _needs_space(previous, item, cluster.height):
            parts.append(" ")
        parts.append(item["text"])
        previous = item

    return {
        "text": "".join(parts).strip(),
        "left": min(item["left"] for item in items),
        "top": min(item["top"] for item in items),
        "right": max(item["right"] for item in items),
        "bottom": max(item["bottom"] for item in items),
    }


def _needs_space(previous: dict, current: dict, line_height: int) -> bool:
    prev_char = _last_visible_char(previous["text"])
    curr_char = _first_visible_char(current["text"])
    if not prev_char or not curr_char:
        return False
    if _is_cjk(prev_char) or _is_cjk(curr_char):
        return False
    if curr_char in ",.;:!?)]}%" or prev_char in "([{#$@/":
        return False

    gap = current["left"] - previous["right"]
    if prev_char.isalnum() and curr_char.isalnum():
        return True
    return gap >= max(4, int(line_height * 0.15))


def _first_visible_char(text: str) -> str:
    for char in text:
        if not char.isspace():
            return char
    return ""


def _last_visible_char(text: str) -> str:
    for char in reversed(text):
        if not char.isspace():
            return char
    return ""


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )
