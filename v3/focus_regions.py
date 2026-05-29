from __future__ import annotations

from dataclasses import dataclass

from v3.frame_utils import frame_to_pil
from v3.types import clamp_bbox


@dataclass
class FocusBox:
    bbox: tuple[float, float, float, float]
    confidence: float
    fill_ratio: float
    area: int


def find_lime_focus_boxes(
    frame,
    search_region: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    *,
    min_width: float = 0.04,
    min_height: float = 0.012,
    max_height: float = 0.25,
    min_aspect: float = 1.2,
    max_fill_ratio: float = 0.55,
    max_boxes: int = 8,
) -> list[FocusBox]:
    """Find yellow-green Forza focus outlines in a normalized frame region."""
    try:
        import numpy as np
    except Exception:
        return []
    try:
        import cv2
    except Exception:
        cv2 = None

    image = frame_to_pil(frame).convert("RGB")
    arr = np.asarray(image)
    height, width = arr.shape[:2]
    rx1, ry1, rx2, ry2 = clamp_bbox(search_region)
    px1 = max(0, min(width - 1, int(rx1 * width)))
    py1 = max(0, min(height - 1, int(ry1 * height)))
    px2 = max(px1 + 1, min(width, int(rx2 * width)))
    py2 = max(py1 + 1, min(height, int(ry2 * height)))
    crop = arr[py1:py2, px1:px2]
    if crop.size == 0:
        return []

    r = crop[:, :, 0]
    g = crop[:, :, 1]
    b = crop[:, :, 2]
    mask = ((g >= 185) & (r >= 120) & (b <= 130) & ((g.astype("int16") - b.astype("int16")) >= 70)).astype("uint8")
    if not int(mask.sum()):
        return []

    if cv2 is not None:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        merged = cv2.dilate(mask, kernel, iterations=1)
        num, _labels, stats, _centroids = cv2.connectedComponentsWithStats(merged, 8)
        component_stats = [tuple(stats[index]) for index in range(1, num)]
    else:
        component_stats = _connected_component_stats(_dilate_mask(mask))
    boxes: list[FocusBox] = []
    crop_h, crop_w = mask.shape[:2]
    for x, y, box_w, box_h, area in component_stats:
        if area < 20:
            continue
        full_x1 = (px1 + x) / float(width)
        full_y1 = (py1 + y) / float(height)
        full_x2 = (px1 + x + box_w) / float(width)
        full_y2 = (py1 + y + box_h) / float(height)
        norm_w = box_w / float(width)
        norm_h = box_h / float(height)
        if norm_w < min_width or norm_h < min_height or norm_h > max_height:
            continue
        aspect = norm_w / max(norm_h, 0.0001)
        if aspect < min_aspect:
            continue
        raw_area = int(mask[y : y + box_h, x : x + box_w].sum())
        fill_ratio = raw_area / float(max(1, box_w * box_h))
        if fill_ratio > max_fill_ratio:
            continue
        confidence = min(0.96, 0.48 + min(0.40, norm_w * 1.2) + min(0.08, raw_area / 2200.0))
        boxes.append(
            FocusBox(
                bbox=clamp_bbox((full_x1, full_y1, full_x2, full_y2)),
                confidence=confidence,
                fill_ratio=fill_ratio,
                area=int(area),
            )
        )
    boxes.sort(key=lambda item: (item.confidence, item.area), reverse=True)
    return boxes[:max_boxes]


def _dilate_mask(mask):
    import numpy as np

    source = mask.astype(bool)
    height, width = source.shape[:2]
    padded = np.pad(source, ((1, 1), (2, 2)), mode="constant", constant_values=False)
    merged = np.zeros_like(source, dtype=bool)
    for dy in range(3):
        for dx in range(5):
            merged |= padded[dy : dy + height, dx : dx + width]
    return merged.astype("uint8")


def _connected_component_stats(mask):
    import numpy as np

    active = mask.astype(bool)
    height, width = active.shape[:2]
    visited = np.zeros_like(active, dtype=bool)
    stats = []
    starts = np.column_stack(np.nonzero(active))
    for start_y, start_x in starts:
        start_y = int(start_y)
        start_x = int(start_x)
        if visited[start_y, start_x]:
            continue
        stack = [(start_x, start_y)]
        visited[start_y, start_x] = True
        min_x = max_x = start_x
        min_y = max_y = start_y
        area = 0
        while stack:
            x, y = stack.pop()
            area += 1
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    if not visited[ny, nx] and active[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((nx, ny))
        stats.append((min_x, min_y, max_x - min_x + 1, max_y - min_y + 1, area))
    return stats
