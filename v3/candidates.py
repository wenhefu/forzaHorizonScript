from __future__ import annotations

from typing import Iterable

from v2.semantic import ForzaSemanticAnalyzer
from v3.types import VisionDetection, clamp_bbox


FOCUS_CLASS_BY_SCREEN = {
    "pause_story": "pause_story_focus",
    "pause_vehicle": "pause_vehicle_focus",
    "pause_vehicle_entry": "pause_vehicle_focus",
    "pause_creative_hub": "pause_creative_hub_focus",
    "pause_my_horizon": "pause_my_horizon_focus",
    "pause_online": "pause_online_focus",
    "pause_store": "pause_store_focus",
    "eventlab_home": "eventlab_card_focus",
    "eventlab_events": "eventlab_card_focus",
    "eventlab_favorites": "eventlab_card_focus",
    "eventlab_my_cars": "my_cars_card_focus",
    "vehicle_buy_grid": "my_cars_card_focus",
    "design_grid": "design_card_focus",
    "vehicle_mastery": "vehicle_mastery_focus",
    "post_race_next": "post_race_next",
    "controller_disconnected": "modal_warning",
    "modal_warning": "modal_warning",
    "purchase_confirm": "modal_warning",
    "eventlab_race_type": "modal_warning",
    "eventlab_filter": "modal_warning",
}

PAGE_CLASS_BY_SCREEN = {
    "race_menu": "race_menu",
    "race_hud": "race_menu",
    "race_result": "race_result",
    "post_race_next": "post_race_next",
    "controller_disconnected": "modal_warning",
    "modal_warning": "modal_warning",
    "eventlab_race_type": "modal_warning",
    "eventlab_filter": "modal_warning",
    "purchase_confirm": "modal_warning",
    "color_select": "color_select",
    "car_preview": "car_preview",
}

RACE_RESULT_KEYWORDS = ("奖励", "结算", "继续", "重开", "影响力", "REWARD", "RESULT")


def class_for_understanding(screen: str, selected_item: str = "", ocr_text: str = "") -> str:
    if screen in FOCUS_CLASS_BY_SCREEN:
        return FOCUS_CLASS_BY_SCREEN[screen]
    if _looks_like_race_result(ocr_text):
        return "race_result"
    return ""


def page_detection_for_screen(screen: str, ocr_text: str = "") -> VisionDetection | None:
    label = PAGE_CLASS_BY_SCREEN.get(screen)
    if not label and not str(screen).startswith("pause_") and _looks_like_race_result(ocr_text):
        label = "race_result"
    if not label:
        return None
    bbox = (0.18, 0.18, 0.82, 0.84)
    if label == "race_menu":
        bbox = (0.0, 0.0, 1.0, 1.0)
    return VisionDetection(label=label, confidence=0.72, bbox=bbox, source="rule-page")


def _looks_like_race_result(ocr_text: str = "") -> bool:
    upper_text = (ocr_text or "").upper()
    hits = [keyword for keyword in RACE_RESULT_KEYWORDS if keyword.upper() in upper_text]
    if len(hits) < 2:
        return False
    return any(keyword in hits for keyword in ("结算", "继续", "重开", "RESULT"))


def content_to_full(
    bbox: tuple[float, float, float, float],
    content_region: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    left, top, right, bottom = content_region
    width = max(0.001, right - left)
    height = max(0.001, bottom - top)
    x1, y1, x2, y2 = bbox
    return clamp_bbox((left + x1 * width, top + y1 * height, left + x2 * width, top + y2 * height))


def _understanding_attr(understanding, name: str, default=""):
    return getattr(understanding, name, default) if understanding is not None else default


def detect_focus_candidates(frame, understanding=None) -> list[VisionDetection]:
    analyzer = ForzaSemanticAnalyzer()
    content_region = _understanding_attr(understanding, "content_region", None)
    if not content_region:
        content_region = analyzer._detect_content_region(frame)
    screen = _understanding_attr(understanding, "screen", "")
    active_tab = _understanding_attr(understanding, "active_tab", "")
    selected_item = _understanding_attr(understanding, "selected_item", "")
    ocr_text = _understanding_attr(understanding, "ocr_text", "")
    label = class_for_understanding(screen, selected_item, ocr_text)
    if not label:
        label = {
            "我的地平线": "pause_my_horizon_focus",
            "在线": "pause_online_focus",
            "商店": "pause_store_focus",
        }.get(active_tab, "")

    detections: list[VisionDetection] = []
    if label and label.endswith("_focus"):
        components = analyzer._lime_components(
            frame,
            content_region,
            min_area=30,
            min_width=0.045,
            min_height=0.030,
        )
        if not components:
            components = analyzer._lime_components(
                frame,
                content_region,
                min_area=30,
                min_width=0.045,
                min_height=0.030,
                predicate=_lime_predicate,
            )
        for area, x1, y1, x2, y2 in components[:8]:
            full_bbox = content_to_full((x1, y1, x2, y2), content_region)
            detections.append(
                VisionDetection(
                    label=label,
                    confidence=min(0.95, 0.45 + area / 1200.0),
                    bbox=full_bbox,
                    source="rule-lime-focus",
                    meta={"area": int(area), "selected_item": selected_item},
                )
            )

    page_detection = page_detection_for_screen(screen, ocr_text)
    if page_detection:
        detections.append(page_detection)
    if not detections and label:
        detections.append(
            VisionDetection(
                label=label,
                confidence=0.42,
                bbox=(0.12, 0.20, 0.88, 0.86),
                source="rule-fallback",
                meta={"screen": screen, "selected_item": selected_item},
            )
        )
    return _dedupe_detections(detections)


def _lime_predicate(r, g, b):
    return (g >= 190) & (r >= 135) & (b <= 95) & ((g - b) >= 120)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = clamp_bbox(a)
    bx1, by1, bx2, by2 = clamp_bbox(b)
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(0.000001, area_a + area_b - inter)


def _dedupe_detections(detections: Iterable[VisionDetection]) -> list[VisionDetection]:
    ordered = sorted(detections, key=lambda item: item.confidence, reverse=True)
    kept: list[VisionDetection] = []
    for detection in ordered:
        if any(detection.label == other.label and _iou(detection.bbox, other.bbox) >= 0.55 for other in kept):
            continue
        kept.append(detection)
    return kept
