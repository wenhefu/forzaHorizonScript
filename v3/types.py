from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


VISION_CLASSES = [
    "pause_story_focus",
    "pause_vehicle_focus",
    "pause_creative_hub_focus",
    "eventlab_card_focus",
    "my_cars_card_focus",
    "vehicle_mastery_focus",
    "race_menu",
    "race_result",
    "post_race_next",
    "modal_warning",
    "pause_my_horizon_focus",
    "pause_online_focus",
    "pause_store_focus",
    "design_card_focus",
    "color_select",
    "car_preview",
]

CLASS_TO_ID = {name: index for index, name in enumerate(VISION_CLASSES)}


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def clamp_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = bbox
    x1 = clamp(x1)
    y1 = clamp(y1)
    x2 = clamp(x2)
    y2 = clamp(y2)
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def bbox_xyxy_to_yolo(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = clamp_bbox(bbox)
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    return x1 + width / 2.0, y1 + height / 2.0, width, height


@dataclass
class VisionDetection:
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]
    source: str = "unknown"
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def class_id(self) -> int:
        return CLASS_TO_ID.get(self.label, -1)

    def is_trainable(self) -> bool:
        x1, y1, x2, y2 = clamp_bbox(self.bbox)
        return self.class_id >= 0 and (x2 - x1) >= 0.01 and (y2 - y1) >= 0.01

    def yolo_line(self) -> str:
        cx, cy, width, height = bbox_xyxy_to_yolo(self.bbox)
        return f"{self.class_id} {cx:.6f} {cy:.6f} {width:.6f} {height:.6f}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["class_id"] = self.class_id
        data["bbox"] = [float(v) for v in clamp_bbox(self.bbox)]
        return data


@dataclass
class OcrRegionResult:
    name: str
    bbox: tuple[float, float, float, float]
    text: str
    confidence: float = 0.0
    source: str = "ocr"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox"] = [float(v) for v in clamp_bbox(self.bbox)]
        return data


@dataclass
class ActionRecommendation:
    button: str
    reason: str
    verify: str
    confidence: float
    name: str = "wait"

    def safe(self) -> bool:
        return bool(self.verify.strip()) and 0.0 <= self.confidence <= 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HybridUnderstanding:
    screen: str
    confidence: float
    active_tab: str = ""
    selected_item: str = ""
    content_region: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    detections: list[VisionDetection] = field(default_factory=list)
    ocr_regions: list[OcrRegionResult] = field(default_factory=list)
    actions: list[ActionRecommendation] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    v2_summary: str = ""
    model_path: str = ""
    ui_node: str = ""
    ui_title: str = ""
    navigation_path: list[str] = field(default_factory=list)
    tab_scope: str = ""
    available_tabs: list[str] = field(default_factory=list)
    available_options: list[str] = field(default_factory=list)
    child_routes: list[dict[str, Any]] = field(default_factory=list)
    control_hints: list[dict[str, Any]] = field(default_factory=list)
    scroll_state: dict[str, Any] = field(default_factory=dict)
    filter_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "screen": self.screen,
            "confidence": float(self.confidence),
            "active_tab": self.active_tab,
            "selected_item": self.selected_item,
            "content_region": [float(v) for v in clamp_bbox(self.content_region)],
            "detections": [detection.to_dict() for detection in self.detections],
            "ocr_regions": [region.to_dict() for region in self.ocr_regions],
            "actions": [action.to_dict() for action in self.actions],
            "reasons": list(self.reasons),
            "v2_summary": self.v2_summary,
            "model_path": self.model_path,
            "ui_node": self.ui_node,
            "ui_title": self.ui_title,
            "navigation_path": list(self.navigation_path),
            "tab_scope": self.tab_scope,
            "available_tabs": list(self.available_tabs),
            "available_options": list(self.available_options),
            "child_routes": list(self.child_routes),
            "control_hints": list(self.control_hints),
            "scroll_state": dict(self.scroll_state),
            "filter_state": dict(self.filter_state),
        }

    def as_text(self) -> str:
        lines = [
            f"V3 页面: {self.screen}  confidence={self.confidence:.2f}",
            f"UI节点: {self.ui_title or '未知'}" + (f" ({self.ui_node})" if self.ui_node else ""),
            f"导航路径: {' > '.join(self.navigation_path) if self.navigation_path else '未知'}",
            f"分页域: {self.tab_scope or '未知'}",
            f"分页: {self.active_tab or '未知'}",
            f"焦点/选中: {self.selected_item or '未知'}",
            f"模型: {self.model_path or '未加载'}",
            "内容区域: "
            f"{self.content_region[0]:.3f}, {self.content_region[1]:.3f}, "
            f"{self.content_region[2]:.3f}, {self.content_region[3]:.3f}",
        ]
        if self.available_tabs:
            lines.append("本层分页: " + " | ".join(self.available_tabs))
        if self.available_options:
            lines.append("本层选项: " + " | ".join(self.available_options[:18]))
        if self.child_routes:
            lines.append("可进入子页:")
            for route in self.child_routes[:12]:
                lines.append(
                    f"- {route.get('trigger', '')} -> {route.get('target', '')} "
                    f"({route.get('button', '') or '状态变化'})"
                )
        if self.control_hints:
            lines.append("底部按钮提示:")
            for hint in self.control_hints[:12]:
                buttons = "/".join(hint.get("buttons", []) or [])
                lines.append(f"- {hint.get('label', '')}: {buttons or hint.get('action', '')}")
        if self.scroll_state and self.scroll_state.get("visible"):
            lines.append(
                "滚动条: "
                f"{self.scroll_state.get('position', 'unknown')} "
                f"up={bool(self.scroll_state.get('can_scroll_up'))} "
                f"down={bool(self.scroll_state.get('can_scroll_down'))}"
            )
        if self.filter_state and self.filter_state.get("visible"):
            checked = self.filter_state.get("favorite_checked")
            if checked is True:
                checked_text = "已勾选（有白色对勾）"
            elif checked is False:
                checked_text = "未勾选（空框）"
            else:
                checked_text = "未知"
            lines.append(
                "筛选状态: "
                f"焦点={self.filter_state.get('focused_row') or '未知'} "
                f"收藏={checked_text}"
            )
            evidence = self.filter_state.get("checkbox_evidence") or {}
            if evidence:
                lines.append(
                    "筛选复选框证据: "
                    f"source={evidence.get('source', 'unknown')} "
                    f"interior_pixels={evidence.get('interior_pixels', 0)}"
                )
        if self.detections:
            lines.append("")
            lines.append("视觉检测:")
            for detection in self.detections[:30]:
                x1, y1, x2, y2 = detection.bbox
                lines.append(
                    f"- {detection.label} {detection.confidence:.2f} "
                    f"[{x1:.3f},{y1:.3f},{x2:.3f},{y2:.3f}] {detection.source}"
                )
        if self.ocr_regions:
            lines.append("")
            lines.append("OCR 小区域:")
            for region in self.ocr_regions:
                lines.append(f"- {region.name}: {region.text or '(空)'} conf={region.confidence:.2f}")
        if self.actions:
            lines.append("")
            lines.append("动作建议（只展示，不执行）:")
            for action in self.actions:
                lines.append(
                    f"- {action.name}: {action.button or '不按键'} "
                    f"confidence={action.confidence:.2f}"
                )
                lines.append(f"  原因: {action.reason}")
                lines.append(f"  验证: {action.verify}")
        if self.reasons:
            lines.append("")
            lines.append("融合依据:")
            for reason in self.reasons:
                lines.append(f"- {reason}")
        if self.v2_summary:
            lines.append("")
            lines.append("V2 基线摘要:")
            lines.append(self.v2_summary[:1200])
        return "\n".join(lines)
