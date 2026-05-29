from __future__ import annotations

from v2.semantic import ForzaSemanticAnalyzer
from v3.buying_ui import (
    canonical_vehicle_name,
    detect_eventlab_filter_state,
    detect_vertical_scrollbar,
    eventlab_event_title,
    infer_manufacturer_scroll_from_text,
    merge_scroll_states,
    normalize_text,
    parse_control_hints_from_items,
)
from v3.candidates import detect_focus_candidates
from v3.focus_regions import find_lime_focus_boxes
from v3.frame_utils import crop_frame, frame_to_pil
from v3.types import ActionRecommendation, HybridUnderstanding, OcrRegionResult, VisionDetection
from v3.ui_tree import EVENTLAB_TABS, describe_ui_state
from v3.ui_names import fallback_ui_name, resolve_ui_name
from v3.yolo_detector import YoloOnnxDetector


SCREEN_BY_DETECTION = {
    "pause_story_focus": "pause_story",
    "pause_vehicle_focus": "pause_vehicle_entry",
    "pause_creative_hub_focus": "pause_creative_hub",
    "pause_my_horizon_focus": "pause_my_horizon",
    "pause_online_focus": "pause_online",
    "pause_store_focus": "pause_store",
    "design_card_focus": "design_grid",
    "eventlab_card_focus": "pause_creative_hub",
    "my_cars_card_focus": "eventlab_my_cars",
    "vehicle_mastery_focus": "vehicle_mastery",
    "race_menu": "race_menu",
    "race_result": "race_result",
    "post_race_next": "post_race_next",
    "modal_warning": "modal_warning",
}

TEXT_REGION_CLASSES = {
    "pause_story_focus",
    "pause_vehicle_focus",
    "pause_creative_hub_focus",
    "pause_my_horizon_focus",
    "pause_online_focus",
    "pause_store_focus",
    "eventlab_card_focus",
    "my_cars_card_focus",
    "design_card_focus",
    "vehicle_mastery_focus",
    "modal_warning",
}

PROBE_OCR_REGIONS = [
    ("probe_top_center", (0.25, 0.00, 0.75, 0.20)),
    ("probe_center_modal", (0.18, 0.20, 0.82, 0.78)),
    ("probe_left_title", (0.00, 0.06, 0.48, 0.32)),
    ("probe_bottom_hints", (0.00, 0.78, 1.00, 1.00)),
]


class HybridVisionRecognizer:
    def __init__(self, detector: YoloOnnxDetector | None = None, ocr_reader=None, analyzer=None):
        self.detector = detector if detector is not None else YoloOnnxDetector()
        self.ocr_reader = ocr_reader
        self.analyzer = analyzer if analyzer is not None else ForzaSemanticAnalyzer()

    def analyze_frame(
        self,
        frame,
        ocr_items=None,
        run_full_ocr: bool = False,
        run_region_ocr: bool = True,
        min_confidence: float = 0.42,
    ) -> HybridUnderstanding:
        full_ocr_items = list(ocr_items or [])
        reasons: list[str] = []
        if run_full_ocr and self.ocr_reader is not None and not full_ocr_items:
            full_ocr_items = self.ocr_reader.read_frame(frame, min_confidence=min_confidence)
            reasons.append(f"Full-frame OCR fallback items={len(full_ocr_items)}")

        v2_understanding = self.analyzer.analyze(frame, full_ocr_items)
        rule_detections = detect_focus_candidates(frame, v2_understanding)
        model_detections = self.detector.predict(frame) if self.detector and self.detector.available() else []
        detections = self._merge_detections(model_detections + rule_detections)

        probe_ocr_regions: list[OcrRegionResult] = []
        if self._should_probe_ocr(v2_understanding, model_detections, full_ocr_items):
            probe_items, probe_ocr_regions = self._read_probe_regions(frame, min_confidence=min_confidence)
            if probe_items:
                full_ocr_items.extend(probe_items)
                v2_understanding = self.analyzer.analyze(frame, full_ocr_items)
                rule_detections = detect_focus_candidates(frame, v2_understanding)
                detections = self._merge_detections(model_detections + rule_detections)
                reasons.append(
                    f"Probe OCR fallback items={len(probe_items)} regions={len(probe_ocr_regions)}"
                )

        screen, confidence, screen_reason = self._fuse_screen(v2_understanding, detections)
        active_tab = getattr(v2_understanding, "active_tab", "")
        selected_hint = ""
        reasons.append(screen_reason)
        textual_pause = self._detect_textual_race_pause_menu(v2_understanding, full_ocr_items)
        if textual_pause:
            screen = "race_pause_menu"
            confidence = max(confidence, textual_pause["confidence"])
            active_tab = textual_pause.get("active_tab", active_tab)
            selected_hint = textual_pause.get("selected_item", "")
            reasons.append(textual_pause["reason"])
        visual_pause = self._detect_visual_race_pause_menu(frame, v2_understanding, detections)
        if visual_pause:
            screen = "race_pause_menu"
            confidence = max(confidence, visual_pause["confidence"])
            active_tab = visual_pause.get("active_tab", active_tab)
            selected_hint = visual_pause.get("selected_item", "")
            if visual_pause.get("focus_bbox"):
                detections = self._merge_detections(
                    detections
                    + [
                        VisionDetection(
                            label="race_pause_focus",
                            confidence=visual_pause["confidence"],
                            bbox=visual_pause["focus_bbox"],
                            source="rule-race-pause",
                        )
                    ]
                )
            reasons.append(visual_pause["reason"])
        if screen == "unknown" and self._looks_like_black_transition(frame, v2_understanding, detections):
            screen = "loading_transition"
            confidence = 0.72
            reasons.append("Frame is nearly black with no OCR/focus signal; treating as loading transition")
        if screen == "unknown" and self._looks_like_idle_showcase(frame, v2_understanding, detections):
            screen = "idle_showcase"
            confidence = 0.62
            reasons.append("No UI text/focus found, but frame looks like a nonblank showroom/idle scene")
        if model_detections:
            reasons.append(f"ONNX detections={len(model_detections)} latency={self.detector.stats.last_latency_ms:.1f}ms")
        elif self.detector and self.detector.stats.error:
            reasons.append(f"ONNX unavailable: {self.detector.stats.error}")
        else:
            reasons.append("ONNX produced no confident detections; using rule/V2 fallback")

        ocr_regions = list(probe_ocr_regions)
        if run_region_ocr:
            ocr_regions.extend(self._read_small_regions(frame, detections, min_confidence=min_confidence))
            ocr_regions.extend(
                self._read_focus_text_regions(
                    frame,
                    screen,
                    min_confidence=min_confidence,
                    ocr_items=full_ocr_items,
                )
            )
            if ocr_regions:
                reasons.append(f"Small-region OCR regions={len(ocr_regions)}")

        selected_item, selected_reason = self._fuse_selected_item(v2_understanding, detections, ocr_regions, screen)
        if selected_hint and not selected_item:
            selected_item = selected_hint
            selected_reason = "Selected item from visual race-pause lock-state rule"
        if selected_reason:
            reasons.append(selected_reason)
        control_hints = [hint.to_dict() for hint in parse_control_hints_from_items(full_ocr_items)]
        if control_hints:
            reasons.append(f"Control hints parsed={len(control_hints)}")
        scroll_state = self._scroll_state(frame, screen, getattr(v2_understanding, "ocr_text", ""))
        if scroll_state.get("visible"):
            reasons.append(
                "Scroll state "
                f"{scroll_state.get('position', 'unknown')} "
                f"up={scroll_state.get('can_scroll_up')} down={scroll_state.get('can_scroll_down')}"
            )
        filter_state = self._filter_state(frame, screen, full_ocr_items)
        if filter_state.get("visible"):
            checked = filter_state.get("favorite_checked")
            checked_text = "checked" if checked is True else "unchecked" if checked is False else "unknown"
            reasons.append(f"Filter focus {filter_state.get('focused_row') or 'unknown'} favorite={checked_text}")

        actions = self._actions(
            v2_understanding,
            screen,
            confidence,
            detections,
            selected_item,
            filter_state,
            active_tab=active_tab,
        )
        model_path = self.detector.stats.model_path if self.detector else ""
        ui_state = describe_ui_state(screen, getattr(v2_understanding, "active_tab", ""), selected_item)
        if ui_state.node_id:
            reasons.append(f"UI tree node={ui_state.node_id} path={ui_state.path_text}")
        return HybridUnderstanding(
            screen=screen,
            confidence=confidence,
            active_tab=active_tab,
            selected_item=selected_item,
            content_region=getattr(v2_understanding, "content_region", (0.0, 0.0, 1.0, 1.0)),
            detections=detections,
            ocr_regions=ocr_regions,
            actions=actions,
            reasons=reasons,
            v2_summary=v2_understanding.as_text() if v2_understanding else "",
            model_path=model_path,
            ui_node=ui_state.node_id,
            ui_title=ui_state.title,
            navigation_path=list(ui_state.path),
            tab_scope=ui_state.tab_scope,
            available_tabs=list(ui_state.tabs),
            available_options=list(ui_state.options),
            child_routes=[route.to_dict() for route in ui_state.children],
            control_hints=control_hints,
            scroll_state=scroll_state,
            filter_state=filter_state,
        )

    def _fuse_screen(self, v2_understanding, detections: list[VisionDetection]):
        v2_screen = getattr(v2_understanding, "screen", "unknown") or "unknown"
        v2_confidence = float(getattr(v2_understanding, "confidence", 0.0) or 0.0)
        best = max(detections, key=lambda item: item.confidence, default=None)
        if best and best.source == "onnx-yolo" and best.confidence >= 0.55:
            screen = self._screen_from_detection(best.label, v2_screen)
            confidence = max(v2_confidence, min(0.97, best.confidence))
            return screen, confidence, f"YOLO detection {best.label} selected screen={screen}"
        if v2_confidence >= 0.70:
            return v2_screen, v2_confidence, f"V2 semantic confidence {v2_confidence:.2f} selected screen={v2_screen}"
        if best and best.confidence >= 0.45:
            screen = self._screen_from_detection(best.label, v2_screen)
            return screen, min(0.78, best.confidence), f"Rule/model candidate {best.label} selected screen={screen}"
        return "unknown", 0.0, "No confident V2 or model signal"

    def _detect_textual_race_pause_menu(self, v2_understanding, ocr_items) -> dict:
        """Detect race pause pages from unmistakable restart/quit-event text."""
        v2_screen = str(getattr(v2_understanding, "screen", "") or "")
        if v2_screen not in ("unknown", "pause_story", "pause_creative_hub", "eventlab_home", "modal_warning"):
            return {}
        raw_text = " | ".join(str(getattr(item, "text", "") or "") for item in (ocr_items or []))
        text = normalize_text(raw_text)
        if not text:
            return {}

        restart_tokens = (
            "重新开始赛事",
            "重新开始比赛",
            "重开赛事",
            "RESTARTEVENT",
            "RESTARTRACE",
        )
        exit_tokens = (
            "退出赛事",
            "退出比赛",
            "返回比赛",
            "返回漫游模式",
            "返回自由漫游",
            "QUITEVENT",
            "RETURNTOFREEROAM",
            "RETURNTOFREEROAMMODE",
            "RESUMEEVENT",
        )
        restart_seen = any(normalize_text(token) in text for token in restart_tokens)
        if not restart_seen and normalize_text("重新开始") in text and (
            normalize_text("赛事") in text or normalize_text("比赛") in text
        ):
            restart_seen = True
        if not restart_seen:
            return {}
        if not any(normalize_text(token) in text for token in exit_tokens):
            return {}
        return {
            "confidence": 0.90,
            "active_tab": "赛事暂停",
            "selected_item": str(getattr(v2_understanding, "selected_item", "") or "赛事暂停菜单"),
            "reason": (
                "Race pause text detected: restart/quit-event controls are visible; "
                "treating this as active race pause instead of normal pause_story."
            ),
        }

    def _screen_from_detection(self, label: str, v2_screen: str) -> str:
        if v2_screen in {"upgrade_menu"} and label.startswith("pause_"):
            return v2_screen
        if label == "eventlab_card_focus" and (
            v2_screen == "pause_creative_hub" or str(v2_screen).startswith("eventlab")
        ):
            return v2_screen
        if label == "my_cars_card_focus" and v2_screen in ("vehicle_buy_grid", "eventlab_my_cars", "garage_my_cars"):
            return v2_screen
        if label == "modal_warning" and v2_screen in (
            "purchase_confirm",
            "controller_disconnected",
            "eventlab_filter",
            "eventlab_race_type",
            "skill_points_exhausted",
        ):
            return v2_screen
        return SCREEN_BY_DETECTION.get(label, v2_screen)

    def _detect_visual_race_pause_menu(self, frame, v2_understanding, detections: list[VisionDetection]) -> dict:
        """Detect the in-race pause menu when OCR is unavailable.

        During an active EventLab/race, the pause menu can show normal top tabs
        but most tiles are locked. OCR may return nothing on these muted teal
        panels, so this visual fallback prevents the frame from being treated as
        a harmless idle showroom.
        """
        if frame is None:
            return {}
        v2_screen = str(getattr(v2_understanding, "screen", "") or "")
        if v2_screen not in ("unknown", "pause_creative_hub", "eventlab_home"):
            return {}
        try:
            import numpy as np

            image = frame_to_pil(frame).convert("RGB")
            arr = np.asarray(image)
            height, width = arr.shape[:2]
            nav = arr[int(height * 0.14) : int(height * 0.30), int(width * 0.08) : int(width * 0.92)]
            body = arr[int(height * 0.25) : int(height * 0.86), int(width * 0.08) : int(width * 0.92)]
            if nav.size == 0 or body.size == 0:
                return {}
            nav_white = float(((nav[:, :, 0] > 220) & (nav[:, :, 1] > 220) & (nav[:, :, 2] > 220)).mean())
            nav_dark = float(((nav[:, :, 0] < 45) & (nav[:, :, 1] < 45) & (nav[:, :, 2] < 45)).mean())
            body_bright = float(((body[:, :, 0] > 210) & (body[:, :, 1] > 210) & (body[:, :, 2] > 210)).mean())
            body_max = body.max(axis=2).astype(float)
            body_min = body.min(axis=2).astype(float)
            body_saturation = float((body_max - body_min).mean())
            body_gray = float(
                (
                    (abs(body[:, :, 0].astype(int) - body[:, :, 1].astype(int)) <= 35)
                    & (abs(body[:, :, 1].astype(int) - body[:, :, 2].astype(int)) <= 35)
                    & (body[:, :, 0] >= 70)
                    & (body[:, :, 0] <= 185)
                ).mean()
            )
            body_muted_teal = float(
                (
                    (body[:, :, 1] >= 65)
                    & (body[:, :, 1] <= 175)
                    & (body[:, :, 0] <= 145)
                    & (body[:, :, 2] <= 155)
                    & (body[:, :, 1].astype(int) >= body[:, :, 0].astype(int) + 8)
                ).mean()
            )
            body_std = float(body.std())
        except Exception:
            return {}

        focus_boxes = find_lime_focus_boxes(
            frame,
            (0.20, 0.24, 0.90, 0.88),
            min_width=0.08,
            min_height=0.030,
            max_height=0.36,
            min_aspect=0.85,
            max_fill_ratio=0.70,
            max_boxes=3,
        )
        focus_box = focus_boxes[0].bbox if focus_boxes else None
        has_focus = bool(focus_box)
        locked_body = (
            body_bright <= 0.095
            and body_std >= 22.0
            and (
                (body_saturation <= 82.0 and body_gray >= 0.006)
                or body_muted_teal >= 0.28
            )
        )
        if (
            nav_white >= 0.10
            and nav_dark >= 0.035
            and locked_body
            and has_focus
        ):
            return {
                "confidence": 0.78,
                "active_tab": "赛事暂停",
                "selected_item": "赛事暂停菜单（带锁功能）",
                "focus_bbox": focus_box,
                "reason": (
                    "Visual locked pause-menu layout detected: top pause tabs plus locked/dimmed tiles; "
                    "treating as in-race pause instead of EventLab home or idle showcase"
                ),
            }
        return {}

    def _fuse_selected_item(
        self,
        v2_understanding,
        detections: list[VisionDetection],
        ocr_regions: list[OcrRegionResult],
        screen: str = "",
    ) -> tuple[str, str]:
        v2_selected = str(getattr(v2_understanding, "selected_item", "") or "")
        v2_screen = str(screen or getattr(v2_understanding, "screen", "") or "")
        for region_name in ("modal_button_focus", "manufacturer_focus", "vehicle_grid_focus", "autoshow_menu_focus", "generic_focus_text"):
            region = next((item for item in ocr_regions if item.name == region_name), None)
            if region:
                item = self._primary_region_text(
                    region.text,
                    allow_short=(region_name == "modal_button_focus"),
                    region_name=region.name,
                )
                if item:
                    return item, f"Selected item from focused UI OCR region {region.name}: {item}"
        best_text_detection = None
        for detection in detections:
            if detection.source == "rule-fallback":
                continue
            if detection.label in TEXT_REGION_CLASSES:
                best_text_detection = detection
                break
        if best_text_detection:
            matching_region = self._matching_ocr_region(best_text_detection, ocr_regions)
            if matching_region:
                if (
                    best_text_detection.label == "eventlab_card_focus"
                    and v2_screen in ("eventlab_events", "eventlab_favorites")
                ):
                    event_title = eventlab_event_title(matching_region.text)
                    if event_title:
                        return event_title, f"Selected EventLab event title from card OCR: {event_title}"
                item = self._primary_region_text(matching_region.text, region_name=matching_region.name)
                if item:
                    return item, f"Selected item from small OCR region {matching_region.name}: {item}"
        return v2_selected, ""

    def _matching_ocr_region(self, detection: VisionDetection, regions: list[OcrRegionResult]) -> OcrRegionResult | None:
        best_region = None
        best_score = 0.0
        for region in regions:
            if region.name != detection.label:
                continue
            score = _iou(region.bbox, detection.bbox)
            if score > best_score:
                best_region = region
                best_score = score
        return best_region

    def _primary_region_text(self, text: str, allow_short: bool = False, region_name: str = "") -> str:
        if region_name in ("my_cars_card_focus", "vehicle_grid_focus"):
            name = canonical_vehicle_name(text)
            if name:
                return name
        official = resolve_ui_name(region_name, text)
        if official:
            return official
        return fallback_ui_name(text, allow_short=allow_short)

    def _should_probe_ocr(self, v2_understanding, model_detections, full_ocr_items) -> bool:
        if self.ocr_reader is None or full_ocr_items:
            return False
        v2_screen = getattr(v2_understanding, "screen", "unknown") or "unknown"
        v2_confidence = float(getattr(v2_understanding, "confidence", 0.0) or 0.0)
        return v2_screen == "unknown" or (v2_confidence < 0.55 and not model_detections)

    def _looks_like_black_transition(self, frame, v2_understanding, detections: list[VisionDetection]) -> bool:
        if frame is None or any(detection.confidence >= 0.45 for detection in detections):
            return False
        if int(getattr(v2_understanding, "item_count", 0) or 0) > 1:
            return False
        try:
            import numpy as np

            image = frame_to_pil(frame).convert("RGB")
            arr = np.asarray(image, dtype=np.float32)
            return float(arr.mean()) <= 8.0 and float(arr.std()) <= 8.0
        except Exception:
            return False

    def _looks_like_idle_showcase(self, frame, v2_understanding, detections: list[VisionDetection]) -> bool:
        if frame is None or any(detection.confidence >= 0.45 for detection in detections):
            return False
        # Showroom/idle frames can still OCR tiny logo/license fragments.  Treat
        # a few sparse items as no actionable UI.
        if int(getattr(v2_understanding, "item_count", 0) or 0) > 6:
            return False
        if find_lime_focus_boxes(
            frame,
            (0.0, 0.0, 1.0, 1.0),
            min_width=0.08,
            min_height=0.035,
            max_boxes=1,
        ):
            return False
        try:
            import numpy as np

            image = frame_to_pil(frame).convert("RGB")
            w, h = image.size
            crop = image.crop((int(w * 0.08), int(h * 0.18), int(w * 0.92), int(h * 0.88)))
            arr = np.asarray(crop, dtype=np.float32)
            mean = float(arr.mean())
            std = float(arr.std())
            bright = float((arr > 235).mean())
        except Exception:
            return False
        return 20.0 <= mean <= 225.0 and std >= 15.0 and bright <= 0.48

    def _read_probe_regions(self, frame, min_confidence: float):
        if self.ocr_reader is None:
            return [], []
        translated_items = []
        regions: list[OcrRegionResult] = []
        for name, bbox in PROBE_OCR_REGIONS:
            cropped = crop_frame(frame, bbox, pad=0.0)
            items = self.ocr_reader.read_frame(cropped, min_confidence=min_confidence)
            if not items:
                continue
            translated_items.extend(self._translate_ocr_items(items, bbox, frame.width, frame.height))
            text = " | ".join(getattr(item, "text", "") for item in items)
            confidence = max([float(getattr(item, "confidence", 0.0) or 0.0) for item in items] or [0.0])
            regions.append(OcrRegionResult(name=name, bbox=bbox, text=text, confidence=confidence, source="probe-ocr"))
        return translated_items, regions

    def _translate_ocr_items(self, items, bbox, frame_width: int, frame_height: int):
        from ocr_engine import OcrItem
        from v3.types import clamp_bbox

        left, top, right, bottom = clamp_bbox(bbox)
        width = max(0.0001, right - left)
        height = max(0.0001, bottom - top)
        translated = []
        for item in items:
            nx1 = left + float(getattr(item, "nx1", 0.0) or 0.0) * width
            ny1 = top + float(getattr(item, "ny1", 0.0) or 0.0) * height
            nx2 = left + float(getattr(item, "nx2", 0.0) or 0.0) * width
            ny2 = top + float(getattr(item, "ny2", 0.0) or 0.0) * height
            ncx = left + float(getattr(item, "ncx", 0.0) or 0.0) * width
            ncy = top + float(getattr(item, "ncy", 0.0) or 0.0) * height
            translated.append(
                OcrItem(
                    text=str(getattr(item, "text", "") or ""),
                    confidence=float(getattr(item, "confidence", 0.0) or 0.0),
                    box=getattr(item, "box", None),
                    x1=nx1 * frame_width,
                    y1=ny1 * frame_height,
                    x2=nx2 * frame_width,
                    y2=ny2 * frame_height,
                    cx=ncx * frame_width,
                    cy=ncy * frame_height,
                    nx1=nx1,
                    ny1=ny1,
                    nx2=nx2,
                    ny2=ny2,
                    ncx=ncx,
                    ncy=ncy,
                )
            )
        return translated

    def _read_focus_text_regions(
        self,
        frame,
        screen: str,
        min_confidence: float,
        ocr_items=None,
    ) -> list[OcrRegionResult]:
        regions: list[OcrRegionResult] = []
        targets = []
        if screen == "modal_warning":
            regions.extend(self._modal_button_regions_from_ocr(frame, ocr_items or []))
            boxes = find_lime_focus_boxes(
                frame,
                (0.16, 0.38, 0.84, 0.82),
                min_width=0.10,
                min_height=0.014,
                max_height=0.09,
                min_aspect=2.2,
                max_fill_ratio=0.46,
                max_boxes=3,
            )
            for box in boxes[:2]:
                if not any(_iou(box.bbox, region.bbox) > 0.40 for region in regions):
                    targets.append(("modal_button_focus", box.bbox))
        elif screen == "autoshow_buy_sell":
            boxes = find_lime_focus_boxes(
                frame,
                (0.00, 0.38, 0.42, 0.92),
                min_width=0.07,
                min_height=0.018,
                max_height=0.10,
                min_aspect=2.0,
                max_fill_ratio=0.45,
                max_boxes=3,
            )
            targets.extend(("autoshow_menu_focus", box.bbox) for box in boxes[:1])
        elif screen == "manufacturer_grid":
            boxes = find_lime_focus_boxes(
                frame,
                (0.08, 0.14, 0.93, 0.90),
                min_width=0.06,
                min_height=0.018,
                max_height=0.09,
                min_aspect=2.0,
                max_fill_ratio=0.50,
                max_boxes=2,
            )
            targets.extend(("manufacturer_focus", box.bbox) for box in boxes[:1])
        elif screen in ("vehicle_buy_grid", "eventlab_my_cars", "garage_my_cars"):
            boxes = find_lime_focus_boxes(
                frame,
                (0.12, 0.12, 0.94, 0.90),
                min_width=0.08,
                min_height=0.05,
                max_height=0.30,
                min_aspect=0.8,
                max_fill_ratio=0.34,
                max_boxes=2,
            )
            targets.extend(("vehicle_grid_focus", box.bbox) for box in boxes[:1])
        elif screen in ("unknown", "external_overlay", "settings_menu", "online_player_list", "world_map"):
            boxes = find_lime_focus_boxes(
                frame,
                (0.00, 0.12, 1.00, 0.92),
                min_width=0.06,
                min_height=0.016,
                max_height=0.14,
                min_aspect=1.5,
                max_fill_ratio=0.45,
                max_boxes=1,
            )
            targets.extend(("generic_focus_text", box.bbox) for box in boxes[:1])

        if self.ocr_reader is None:
            return regions
        for name, bbox in targets:
            region = self._read_region_text(frame, name, bbox, min_confidence, source="focus-ocr")
            if region:
                regions.append(region)
        return regions

    def _modal_button_regions_from_ocr(self, frame, ocr_items) -> list[OcrRegionResult]:
        candidates = []
        for item in ocr_items or []:
            text = str(getattr(item, "text", "") or "").strip()
            if not resolve_ui_name("modal_button_focus", text):
                continue
            cx = float(getattr(item, "ncx", 0.5) or 0.5)
            cy = float(getattr(item, "ncy", 0.5) or 0.5)
            if not (0.30 <= cx <= 0.72 and 0.38 <= cy <= 0.78):
                continue
            width = max(0.20, float(getattr(item, "nx2", cx) or cx) - float(getattr(item, "nx1", cx) or cx) + 0.22)
            height = max(0.034, float(getattr(item, "ny2", cy) or cy) - float(getattr(item, "ny1", cy) or cy) + 0.030)
            bbox = (cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)
            score = self._lime_border_score(frame, bbox)
            if score >= 0.010:
                candidates.append(
                    OcrRegionResult(
                        name="modal_button_focus",
                        bbox=bbox,
                        text=text,
                        confidence=min(0.96, 0.70 + score * 5.0),
                        source="focus-ocr:full-ocr-border",
                    )
                )
        candidates.sort(key=lambda item: item.confidence, reverse=True)
        return candidates[:1]

    def _lime_border_score(self, frame, bbox) -> float:
        from v3.types import clamp_bbox

        x1, y1, x2, y2 = clamp_bbox(bbox)
        thickness = max(0.003, min(0.012, (y2 - y1) * 0.30))
        bands = [
            (x1, y1, x2, min(y2, y1 + thickness)),
            (x1, max(y1, y2 - thickness), x2, y2),
            (x1, y1, min(x2, x1 + thickness), y2),
            (max(x1, x2 - thickness), y1, x2, y2),
        ]

        def limeish(r, g, b):
            return g >= 180 and r >= 110 and b <= 145 and (g - b) >= 55

        try:
            return sum(frame.ratio(band, limeish, step=2) for band in bands) / len(bands)
        except Exception:
            return 0.0

    def _read_region_text(self, frame, name: str, bbox, min_confidence: float, source: str) -> OcrRegionResult | None:
        cropped = crop_frame(frame, bbox, pad=0.008)
        items = self.ocr_reader.read_frame(cropped, min_confidence=min_confidence)
        text = " | ".join(getattr(item, "text", "") for item in items)
        confidence = max([float(getattr(item, "confidence", 0.0) or 0.0) for item in items] or [0.0])
        if not text:
            return None
        return OcrRegionResult(name=name, bbox=bbox, text=text, confidence=confidence, source=source)

    def _read_small_regions(self, frame, detections: list[VisionDetection], min_confidence: float) -> list[OcrRegionResult]:
        if self.ocr_reader is None:
            return []
        regions: list[OcrRegionResult] = []
        for detection in detections:
            if detection.source == "rule-fallback":
                continue
            if detection.label not in TEXT_REGION_CLASSES:
                continue
            cropped = crop_frame(frame, detection.bbox, pad=0.015)
            items = self.ocr_reader.read_frame(cropped, min_confidence=min_confidence)
            text = " | ".join(getattr(item, "text", "") for item in items)
            confidence = max([float(getattr(item, "confidence", 0.0) or 0.0) for item in items] or [0.0])
            regions.append(
                OcrRegionResult(
                    name=detection.label,
                    bbox=detection.bbox,
                    text=text,
                    confidence=confidence,
                    source=f"small-ocr:{detection.source}",
                )
            )
            if len(regions) >= 6:
                break
        return regions

    def _actions(
        self,
        v2_understanding,
        screen: str,
        confidence: float,
        detections: list[VisionDetection],
        selected_item: str = "",
        filter_state: dict | None = None,
        active_tab: str = "",
    ):
        actions: list[ActionRecommendation] = []
        v2_screen = str(getattr(v2_understanding, "screen", "") or "")
        for action in getattr(v2_understanding, "actions", []) or []:
            verify = str(getattr(action, "verify", "") or "").strip()
            if not verify:
                continue
            actions.append(
                ActionRecommendation(
                    button=str(getattr(action, "button", "") or ""),
                    reason=str(getattr(action, "reason", "") or ""),
                    verify=verify,
                    confidence=float(getattr(action, "confidence", 0.0) or 0.0),
                    name=str(getattr(action, "name", "V2 action") or "V2 action"),
                )
            )
        if screen == "eventlab_filter":
            return self._eventlab_filter_actions(confidence, filter_state or {})

        if screen in ("eventlab_events", "eventlab_favorites"):
            return self._eventlab_event_actions(
                confidence,
                selected_item,
                active_tab,
                getattr(v2_understanding, "eventlab_tabs", []) or [],
            )

        if screen == "eventlab_my_cars":
            return self._eventlab_my_cars_actions(confidence, selected_item)

        if actions and screen != "idle_showcase" and self._can_reuse_v2_actions(v2_screen, screen):
            return actions

        if screen == "idle_showcase":
            return self._wake_probe_actions(confidence)

        if screen == "race_pause_menu":
            return [
                ActionRecommendation(
                    button="B",
                    reason="当前是赛事/活动中的暂停菜单，带锁卡片不应继续进入；优先返回当前比赛。",
                    verify="按后必须重新识别到 race_hud、race_menu、idle_showcase 或明确的比赛/自由漫游状态。",
                    confidence=max(0.72, min(0.90, confidence)),
                    name="返回当前比赛",
                )
            ]

        if screen == "loading_transition":
            return [
                ActionRecommendation(
                    button="",
                    reason="画面是黑屏/加载过渡帧，没有可验证 UI。",
                    verify="等待下一帧重新识别，直到出现 idle_showcase、purchase_confirm、vehicle_buy_grid、pause_* 或 HUD。",
                    confidence=confidence,
                    name="等待加载完成",
                )
            ]

        if confidence < 0.55 or screen == "unknown":
            return [
                ActionRecommendation(
                    button="",
                    reason="识别置信度不足，V3 不建议盲按。",
                    verify="等待下一帧重新识别，或保存样本补充训练。",
                    confidence=max(0.0, min(confidence, 0.50)),
                    name="等待重新识别",
                )
            ]
        if screen == "post_race_next":
            return [
                ActionRecommendation(
                    button="B",
                    reason="识别到赛后下一站页，需先返回自由漫游再打开暂停菜单。",
                    verify="按后应不再出现“下一站”大卡片；下一帧应是自由漫游 HUD 或可按 Menu 打开暂停菜单。",
                    confidence=confidence,
                    name="离开下一站页",
                )
            ]
        if screen == "modal_warning":
            return [
                ActionRecommendation(
                    button="",
                    reason="检测到弹窗/警告，但文字尚未确认。",
                    verify="先用小区域 OCR 确认弹窗语义，再决定 A 或 B。",
                    confidence=confidence,
                    name="弹窗等待确认",
                )
            ]
        if screen in ("vehicle_buy_grid", "manufacturer_grid"):
            return [
                ActionRecommendation(
                    button="",
                    reason="当前买车/制造商页面结构已识别；V3 只给状态，不盲目购买或选择品牌。",
                    verify="如果上层要移动焦点或选择，必须一步一识别，确认焦点车辆/品牌和滚动状态按预期变化。",
                    confidence=confidence,
                    name="买车页面结构已识别",
                )
            ]
        return [
            ActionRecommendation(
                button="",
                reason="当前识别只确认页面结构，未确认下一步目标。",
                verify="根据目标状态机选择一步按键后，必须重新识别页面语义。",
                confidence=confidence,
                name="结构已识别",
            )
        ]

    def _eventlab_filter_actions(self, confidence: float, filter_state: dict) -> list[ActionRecommendation]:
        focused = str(filter_state.get("focused_row") or "")
        checked = filter_state.get("favorite_checked")
        if focused == "收藏" and checked is False:
            return [
                ActionRecommendation(
                    button="A",
                    reason="筛选弹窗焦点在“收藏”，而且复选框未勾选；只允许按一次来打开收藏筛选。",
                    verify="按后必须重新识别 eventlab_filter，且筛选状态显示 收藏=已勾选；确认后下一步才按 B 返回。",
                    confidence=max(0.70, min(0.90, confidence)),
                    name="勾选收藏筛选",
                )
            ]
        if focused == "收藏" and checked is True:
            return [
                ActionRecommendation(
                    button="B",
                    reason="“收藏”已经勾选，继续按 A 会取消勾选；应该返回我的车辆列表。",
                    verify="按后必须重新识别到 eventlab_my_cars，并且目标车辆必须是 IMPREZA 22B-STI VERSION 后才允许选择。",
                    confidence=max(0.76, min(0.92, confidence)),
                    name="收藏已勾选，返回车辆列表",
                )
            ]
        if focused and focused != "收藏":
            return [
                ActionRecommendation(
                    button="DPadUp",
                    reason=f"筛选弹窗焦点在“{focused}”，目标是顶部“收藏”；先移动焦点，不切换复选框。",
                    verify="按后必须重新识别 eventlab_filter，且焦点行变成 收藏。",
                    confidence=max(0.58, min(0.75, confidence)),
                    name="移动到收藏筛选",
                )
            ]
        return [
            ActionRecommendation(
                button="",
                reason="识别到筛选弹窗，但还没确认焦点行或收藏勾选状态，不能盲按 A。",
                verify="补采样本或重新识别，必须看到 焦点=收藏 且 收藏=未勾选/已勾选 后再决定 A 或 B。",
                confidence=max(0.0, min(confidence, 0.60)),
                name="等待筛选状态确认",
            )
        ]

    def _eventlab_event_actions(
        self,
        confidence: float,
        selected_item: str,
        active_tab: str = "",
        tabs=None,
    ) -> list[ActionRecommendation]:
        normalized = normalize_text(selected_item)
        if "SPFARM" in normalized and ("SKILLPOINT" in normalized or "10" in normalized):
            return [
                ActionRecommendation(
                    button="A",
                    reason="当前收藏赛事卡片已识别为 SP Farm / 24 second race = 10 skillpoints。",
                    verify="按后必须重新识别到 eventlab_race_type、eventlab_my_cars 或 race_menu；如果仍在赛事列表，不连续盲按。",
                    confidence=max(0.78, min(0.90, confidence)),
                    name="选择目标刷分赛事",
                )
            ]
        target_tab = "我的收藏"
        if active_tab and normalize_text(active_tab) != normalize_text(target_tab):
            button, detail = self._eventlab_tab_move(active_tab, target_tab, tabs or [])
            if button:
                return [
                    ActionRecommendation(
                        button=button,
                        reason=(
                            f"当前 EventLab 顶部分页是“{active_tab}”，目标赛事优先在“{target_tab}”。"
                            f"{detail}只按一次 {button} 后复核；Y 只切换当前赛事收藏，不进入收藏分页。"
                        ),
                        verify=(
                            "按后必须重新识别顶栏 active_tab；若到达“我的收藏”，再检查选中赛事标题是否为 "
                            "SP Farm / 24 second race = 10 skillpoints。"
                        ),
                        confidence=max(0.64, min(0.84, confidence)),
                        name="切到我的收藏分页",
                    )
                ]
        if not active_tab:
            return [
                ActionRecommendation(
                    button="",
                    reason="当前在 EventLab 赛事列表，但顶部分页焦点还没确认；先不要按 A/Y，避免误进赛事或误切收藏状态。",
                    verify="重新识别或保存样本，必须确认顶栏 active_tab 是“我的收藏”或能判断 LB/RB 方向后再操作。",
                    confidence=max(0.50, min(0.70, confidence)),
                    name="等待顶栏分页确认",
                )
            ]
        return [
            ActionRecommendation(
                button="",
                reason="当前在 EventLab 赛事列表；顶栏分页已到目标范围，但选中赛事标题还不是目标赛事。Y 只是切换当前赛事收藏状态，不是进入收藏页。",
                verify="移动分页/焦点后必须重新识别选中赛事标题，目标应包含 SP Farm / 24 second race = 10 skillpoints。",
                confidence=max(0.55, min(0.78, confidence)),
                name="等待目标赛事",
            )
        ]

    def _eventlab_tab_move(self, active_tab: str, target_tab: str, tabs) -> tuple[str, str]:
        active_norm = normalize_text(active_tab)
        target_norm = normalize_text(target_tab)
        active_candidate = None
        target_candidate = None
        for tab in tabs:
            label_norm = normalize_text(getattr(tab, "label", "") or "")
            if label_norm == active_norm and active_candidate is None:
                active_candidate = tab
            if label_norm == target_norm and target_candidate is None:
                target_candidate = tab
        if active_candidate is not None and target_candidate is not None:
            if float(getattr(target_candidate, "x", 0.0) or 0.0) > float(getattr(active_candidate, "x", 0.0) or 0.0):
                return "RB", "顶栏里已经看到“我的收藏”在当前分页右侧，"
            return "LB", "顶栏里已经看到“我的收藏”在当前分页左侧，"

        order = list(EVENTLAB_TABS)
        try:
            current_index = next(index for index, label in enumerate(order) if normalize_text(label) == active_norm)
            target_index = next(index for index, label in enumerate(order) if normalize_text(label) == target_norm)
        except StopIteration:
            return "", ""
        if current_index == target_index:
            return "", ""
        if target_index > current_index:
            return "RB", f"按逻辑分页顺序还差约 {target_index - current_index} 步，"
        return "LB", f"按逻辑分页顺序还差约 {current_index - target_index} 步，"

    def _eventlab_my_cars_actions(self, confidence: float, selected_item: str) -> list[ActionRecommendation]:
        normalized = normalize_text(selected_item)
        if "22B" in normalized and ("IMPREZA" in normalized or "MPREZA" in normalized):
            return [
                ActionRecommendation(
                    button="A",
                    reason="EventLab 选车页已确认焦点车辆是 IMPREZA 22B-STI VERSION。",
                    verify="按后必须重新识别到 race_menu；若仍在 eventlab_my_cars，则只允许重新确认焦点后再决定是否补按。",
                    confidence=max(0.78, min(0.90, confidence)),
                    name="选择 22B 参赛",
                )
            ]
        return [
            ActionRecommendation(
                button="",
                reason="当前是 EventLab 我的车辆页，但焦点车辆不是 22B 或无法确认；不能进入比赛。",
                verify="先用 Y 打开筛选并确认 收藏=已勾选，返回后必须识别到 IMPREZA 22B-STI VERSION 被选中。",
                confidence=max(0.50, min(0.76, confidence)),
                name="等待选中 22B",
            )
        ]

    def _can_reuse_v2_actions(self, v2_screen: str, fused_screen: str) -> bool:
        if v2_screen == fused_screen:
            return True
        if fused_screen.startswith("pause_") and v2_screen == "pause_menu":
            return True
        if fused_screen.startswith("eventlab") and v2_screen.startswith("eventlab"):
            return True
        if fused_screen in ("vehicle_buy_grid", "manufacturer_grid") and v2_screen == fused_screen:
            return True
        return False

    def _scroll_state(self, frame, screen: str, ocr_text: str) -> dict:
        if screen not in ("manufacturer_grid", "vehicle_buy_grid", "eventlab_my_cars", "garage_my_cars"):
            return {}
        visual = detect_vertical_scrollbar(frame)
        if screen == "manufacturer_grid":
            return merge_scroll_states(visual, infer_manufacturer_scroll_from_text(ocr_text)).to_dict()
        return visual.to_dict() if visual.visible else {}

    def _filter_state(self, frame, screen: str, ocr_items) -> dict:
        if screen != "eventlab_filter":
            return {}
        return detect_eventlab_filter_state(frame, ocr_items)

    def _wake_probe_actions(self, confidence: float) -> list[ActionRecommendation]:
        base_verify = (
            "按后必须重新截图识别；只有出现 modal_warning、autoshow_buy_sell、pause_*、"
            "free_roam_hud 或明确菜单文字时才允许继续，否则等待或换下一个唤醒键。"
        )
        return [
            ActionRecommendation(
                button="A",
                reason="当前像车辆展示/待机页，没有可操作 UI；A 常用于唤醒或显示当前上下文 UI。",
                verify=base_verify,
                confidence=max(0.50, min(0.68, confidence)),
                name="唤醒待机 UI",
            ),
            ActionRecommendation(
                button="B",
                reason="如果 A 没有唤醒 UI，B 常用于返回上一层或让底部提示重新出现。",
                verify=base_verify,
                confidence=max(0.45, min(0.60, confidence - 0.04)),
                name="返回/唤醒待机 UI",
            ),
            ActionRecommendation(
                button="Menu",
                reason="如果目标是回到暂停菜单，Menu 是比随机方向键更明确的唤醒/开菜单探针。",
                verify="按后必须识别到 pause_*、pause_menu 或 free_roam_hud；未变化则不要连续盲按。",
                confidence=max(0.42, min(0.58, confidence - 0.06)),
                name="打开暂停菜单探针",
            ),
        ]

    def _merge_detections(self, detections: list[VisionDetection]) -> list[VisionDetection]:
        kept: list[VisionDetection] = []
        for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
            if any(detection.label == other.label and _iou(detection.bbox, other.bbox) >= 0.60 for other in kept):
                continue
            kept.append(detection)
        return kept


def _iou(a, b) -> float:
    from v3.types import clamp_bbox

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
