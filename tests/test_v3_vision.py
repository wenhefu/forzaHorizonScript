from types import SimpleNamespace

from v3.candidates import detect_focus_candidates, page_detection_for_screen
from v3.buying_ui import (
    _checkbox_is_checked,
    canonical_vehicle_name,
    detect_eventlab_filter_state,
    eventlab_event_title,
    parse_control_hints,
)
from v3.focus_regions import find_lime_focus_boxes
from v3.frame_utils import load_frame_from_image, pil_to_frame
from v3.hybrid import HybridVisionRecognizer
from v3.types import VISION_CLASSES, ActionRecommendation, OcrRegionResult, VisionDetection
from v3.ui_tree import describe_ui_state
from v3.ui_names import fallback_ui_name, resolve_ui_name
from v3.yolo_detector import YoloOnnxDetector, resolve_asset_path


def _dummy_understanding():
    return SimpleNamespace(
        screen="pause_vehicle_entry",
        confidence=0.92,
        active_tab="车辆",
        selected_item="更换车辆",
        content_region=(0.0, 0.0, 1.0, 1.0),
        ocr_text="车辆 更换车辆",
        actions=[],
        as_text=lambda: "dummy",
    )


class _DetectorStats:
    model_path = "fake.onnx"
    last_latency_ms = 1.0
    error = ""


class _FakeDetector:
    stats = _DetectorStats()

    def __init__(self, detections):
        self._detections = detections

    def available(self):
        return True

    def predict(self, frame):
        return list(self._detections)


def test_vision_classes_cover_required_labels():
    assert VISION_CLASSES == [
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


def test_detection_yolo_line_is_normalized():
    detection = VisionDetection("pause_vehicle_focus", 0.8, (0.1, 0.2, 0.5, 0.6), "test")
    line = detection.yolo_line()
    assert line.startswith("1 ")
    assert "0.300000 0.400000 0.400000 0.400000" in line


def test_action_requires_verify_condition():
    assert not ActionRecommendation("A", "reason", "", 0.9).safe()
    assert ActionRecommendation("A", "reason", "重新识别页面", 0.9).safe()


def test_hybrid_falls_back_to_wait_when_uncertain():
    from PIL import Image

    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    frame = pil_to_frame(Image.new("RGBA", (640, 360), (38, 42, 44, 255)))
    understanding = recognizer.analyze_frame(frame, ocr_items=[], run_full_ocr=False, run_region_ocr=False)
    assert understanding.actions
    assert understanding.actions[0].button == ""
    assert understanding.actions[0].verify


def test_hybrid_idle_showcase_suggests_wake_probe_actions():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (900, 500), (28, 28, 32, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 900, 55], fill=(2, 2, 2, 255))
    draw.rectangle([0, 445, 900, 500], fill=(2, 2, 2, 255))
    draw.rectangle([80, 190, 820, 360], fill=(92, 86, 80, 255))
    draw.ellipse([260, 260, 360, 360], fill=(115, 38, 155, 255))
    draw.ellipse([560, 260, 660, 360], fill=(115, 38, 155, 255))
    frame = pil_to_frame(image)
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))

    understanding = recognizer.analyze_frame(frame, ocr_items=[], run_full_ocr=False, run_region_ocr=False)

    assert understanding.screen == "idle_showcase"
    assert [action.button for action in understanding.actions[:3]] == ["A", "B", "Menu"]
    assert all(action.verify for action in understanding.actions)


def test_hybrid_visual_locked_pause_menu_is_not_idle_showcase():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (900, 500), (35, 135, 122, 255))
    draw = ImageDraw.Draw(image)
    # Pause top navigation: white tabs plus a black active tab.
    draw.rectangle([110, 90, 790, 118], fill=(245, 245, 245, 255))
    draw.rectangle([510, 90, 600, 118], fill=(5, 5, 5, 255))
    draw.rectangle([510, 116, 600, 119], fill=(190, 255, 0, 255))
    for x in range(110, 790, 115):
        draw.line([x, 90, x, 118], fill=(80, 80, 80, 255), width=2)

    # Locked/dimmed creative-hub-like tiles.
    for box in ([115, 140, 255, 420], [255, 140, 650, 270], [255, 270, 560, 430], [650, 140, 790, 420]):
        draw.rectangle(box, fill=(22, 89, 78, 255), outline=(40, 126, 112, 255), width=2)
    draw.ellipse([310, 285, 410, 385], outline=(120, 150, 145, 255), width=8)
    draw.rectangle([350, 338, 374, 368], fill=(120, 150, 145, 255))
    draw.arc([348, 315, 376, 350], 180, 360, fill=(120, 150, 145, 255), width=8)
    draw.rectangle([252, 268, 562, 432], outline=(190, 255, 0, 255), width=5)
    draw.rectangle([30, 455, 90, 478], fill=(8, 20, 18, 255))
    draw.rectangle([35, 459, 58, 474], fill=(255, 255, 255, 255))

    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    understanding = recognizer.analyze_frame(pil_to_frame(image), ocr_items=[], run_full_ocr=False, run_region_ocr=False)

    assert understanding.screen == "race_pause_menu"
    assert understanding.actions[0].button == "B"
    assert "带锁" in understanding.actions[0].reason


def test_hybrid_visual_locked_pause_menu_tolerates_one_bright_selected_tile():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (1200, 700), (35, 135, 122, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([150, 165, 1050, 205], fill=(245, 245, 245, 255))
    draw.rectangle([690, 165, 810, 205], fill=(5, 5, 5, 255))
    draw.rectangle([690, 202, 810, 207], fill=(190, 255, 0, 255))
    for box in ([150, 230, 330, 590], [330, 230, 860, 410], [330, 410, 730, 600], [860, 230, 1050, 590]):
        draw.rectangle(box, fill=(22, 89, 78, 255), outline=(40, 126, 112, 255), width=3)
    draw.ellipse([545, 445, 670, 570], outline=(120, 150, 145, 255), width=10)
    draw.rectangle([592, 512, 625, 560], fill=(120, 150, 145, 255))
    draw.arc([590, 480, 628, 525], 180, 360, fill=(120, 150, 145, 255), width=10)
    draw.rectangle([870, 500, 1050, 545], fill=(250, 250, 250, 255))
    draw.rectangle([328, 408, 732, 604], outline=(190, 255, 0, 255), width=6)

    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    understanding = recognizer.analyze_frame(pil_to_frame(image), ocr_items=[], run_full_ocr=False, run_region_ocr=False)

    assert understanding.screen == "race_pause_menu"


def test_hybrid_textual_race_pause_story_is_not_normal_pause_story():
    from PIL import Image

    def ocr(text, x1, y1, x2, y2):
        return SimpleNamespace(
            text=text,
            confidence=0.93,
            nx1=x1,
            ny1=y1,
            nx2=x2,
            ny2=y2,
            ncx=(x1 + x2) / 2.0,
            ncy=(y1 + y2) / 2.0,
        )

    frame = pil_to_frame(Image.new("RGBA", (900, 500), (35, 135, 122, 255)))
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    understanding = recognizer.analyze_frame(
        frame,
        ocr_items=[
            ocr("剧情", 0.30, 0.12, 0.36, 0.17),
            ocr("世界地图", 0.34, 0.30, 0.55, 0.44),
            ocr("重新开始赛事", 0.12, 0.46, 0.28, 0.58),
            ocr("退出赛事", 0.74, 0.46, 0.88, 0.58),
            ocr("返回漫游模式", 0.74, 0.74, 0.90, 0.82),
        ],
        run_full_ocr=False,
        run_region_ocr=False,
    )

    assert understanding.screen == "race_pause_menu"
    assert understanding.actions[0].button == "B"
    assert any("Race pause text detected" in reason for reason in understanding.reasons)


def test_hybrid_black_frame_is_loading_transition_wait():
    from PIL import Image

    frame = pil_to_frame(Image.new("RGBA", (900, 500), (0, 0, 0, 255)))
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))

    understanding = recognizer.analyze_frame(frame, ocr_items=[], run_full_ocr=False, run_region_ocr=False)

    assert understanding.screen == "loading_transition"
    assert understanding.actions[0].button == ""
    assert "下一帧" in understanding.actions[0].verify


def test_hybrid_uses_fused_modal_actions_instead_of_stale_v2_unknown():
    from PIL import Image

    frame = pil_to_frame(Image.new("RGBA", (900, 500), (35, 36, 38, 255)))
    detector = _FakeDetector([VisionDetection("modal_warning", 0.91, (0.28, 0.20, 0.72, 0.44), "onnx-yolo")])
    recognizer = HybridVisionRecognizer(detector=detector)

    understanding = recognizer.analyze_frame(frame, ocr_items=[], run_full_ocr=False, run_region_ocr=False)

    assert understanding.screen == "modal_warning"
    assert understanding.actions[0].confidence >= 0.9


def test_rule_candidates_return_trainable_detection_for_known_screen():
    frame = load_frame_from_image("assets/prep/pause_home.png", max_width=640)
    detections = detect_focus_candidates(frame, _dummy_understanding())
    assert detections
    assert all(detection.is_trainable() for detection in detections)


def test_page_detections_cover_race_menu_and_result():
    race_menu = page_detection_for_screen("race_menu")
    race_result = page_detection_for_screen("race_result")

    assert race_menu is not None
    assert race_menu.label == "race_menu"
    assert race_result is not None
    assert race_result.label == "race_result"


def test_hybrid_selected_item_prefers_small_region_ocr():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    detection = VisionDetection("eventlab_card_focus", 0.95, (0.12, 0.24, 0.28, 0.79), "rule-lime-focus")
    region = OcrRegionResult("eventlab_card_focus", detection.bbox, "地产 | 浏览地产", 0.76)
    selected, reason = recognizer._fuse_selected_item(_dummy_understanding(), [detection], [region])

    assert selected == "地产"
    assert "small OCR" in reason


def test_hybrid_selected_item_resolves_eventlab_official_name():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    detection = VisionDetection("eventlab_card_focus", 0.98, (0.27, 0.24, 0.73, 0.53), "onnx-yolo")
    region = OcrRegionResult(
        "eventlab_card_focus",
        detection.bbox,
        "HORIZON | eventlab | BFGoodrich | ALUMICRAFT | CR | 创建并浏览赛事",
        0.87,
    )
    selected, reason = recognizer._fuse_selected_item(_dummy_understanding(), [detection], [region])

    assert selected == "eventlab"
    assert "small OCR" in reason


def test_eventlab_favorites_selected_item_uses_event_title_not_logo():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    v2 = SimpleNamespace(screen="eventlab_favorites", selected_item="EventLab")
    detection = VisionDetection("eventlab_card_focus", 0.98, (0.25, 0.17, 0.49, 0.85), "onnx-yolo")
    region = OcrRegionResult(
        "eventlab_card_focus",
        detection.bbox,
        "我的收藏 | AMMAGEDON79 | 巨献 | ANYTHING | GOES | EventLab | 1.3千米 | SPFarm/24 second | 18205,385 | 207,915 | race = 10 skillpoints | HORZON",
        0.91,
    )

    selected, reason = recognizer._fuse_selected_item(v2, [detection], [region], "eventlab_favorites")

    assert selected == "SP Farm / 24 second race = 10 skillpoints"
    assert "EventLab event title" in reason


def test_canonical_vehicle_name_recovers_cropped_22b_title():
    assert canonical_vehicle_name("ERSION | IMPREZA | 1998 SUBARU | owned | B600") == "IMPREZA 22B-STI VERSION"
    assert canonical_vehicle_name("VERSION | IMPREZ | 1998斯巴鲁 | 传奇 | 600") == "IMPREZA 22B-STI VERSION"


def test_hybrid_selected_item_resolves_split_vehicle_name():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    detection = VisionDetection("pause_vehicle_focus", 0.94, (0.10, 0.30, 0.46, 0.58), "onnx-yolo")
    region = OcrRegionResult("pause_vehicle_focus", detection.bbox, "更换 | 车辆 | 已拥有505辆车 | 10", 0.85)
    selected, reason = recognizer._fuse_selected_item(_dummy_understanding(), [detection], [region])

    assert selected == "更换车辆"
    assert "small OCR" in reason


def test_hybrid_does_not_let_broad_rule_fallback_ocr_override_v2_focus():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    v2 = SimpleNamespace(selected_item="收集簿")
    detection = VisionDetection(
        "pause_story_focus",
        0.42,
        (0.12, 0.20, 0.88, 0.86),
        "rule-fallback",
    )
    region = OcrRegionResult(
        "pause_story_focus",
        detection.bbox,
        "festival | playlist | 世界地图 | 收集簿 | 推荐内容 | 退出游戏",
        0.80,
    )

    selected, reason = recognizer._fuse_selected_item(v2, [detection], [region])

    assert selected == "收集簿"
    assert reason == ""


def test_ui_name_rules_ignore_decorative_tokens_before_official_name():
    assert (
        resolve_ui_name(
            "eventlab_card_focus",
            "HORIZON | eventlab | BFGoodrich | ALUMICRAFT | CR | 创建并浏览赛事",
        )
        == "eventlab"
    )
    assert (
        resolve_ui_name("pause_online_focus", "HORIZON | PLAY! | 与其他玩家互相比拼")
        == "Horizon Play"
    )
    assert (
        resolve_ui_name("pause_store_focus", "《极限竞速：地平线 | 高级版升级捆绑包")
        == "高级版升级捆绑包"
    )


def test_ui_name_rules_cover_common_pause_focus_variants():
    assert (
        resolve_ui_name("pause_story_focus", "festival | playlist | 欢迎来到 | 日本")
        == "Festival Playlist / 欢迎来到日本"
    )
    assert resolve_ui_name("pause_story_focus", "下一 | 推荐内容") == "下一站"
    assert resolve_ui_name("pause_my_horizon_focus", "HORIZON | SUPEX | wheelspin | 超级 | 0 可用") == "超级抽奖"
    assert resolve_ui_name("pause_online_focus", "hyobeech | 社交 | 在线好友") == "在线好友"
    assert resolve_ui_name("pause_creative_hub_focus", "道具预制件 | 排名1") == "道具预制件"


def test_fallback_ui_name_skips_parenthesized_decorative_horizon():
    assert fallback_ui_name("(HORIZON | wheelspin | 抽奖 | 0 可用") == "wheelspin"


def test_eventlab_card_detection_keeps_v2_eventlab_screen_family():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    v2 = SimpleNamespace(screen="eventlab_home", confidence=0.74)
    detection = VisionDetection("eventlab_card_focus", 0.98, (0.27, 0.24, 0.73, 0.53), "onnx-yolo")

    screen, confidence, reason = recognizer._fuse_screen(v2, [detection])

    assert screen == "eventlab_home"
    assert confidence == 0.97
    assert "eventlab_card_focus" in reason


def test_hybrid_selected_item_reads_modal_button_focus():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    region = OcrRegionResult("modal_button_focus", (0.32, 0.58, 0.68, 0.64), "不", 0.88)
    selected, reason = recognizer._fuse_selected_item(_dummy_understanding(), [], [region])

    assert selected == "不"
    assert "focused UI OCR" in reason


def test_modal_button_focus_can_be_derived_from_full_ocr_and_border():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (800, 450), (25, 40, 38, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([250, 245, 550, 270], fill=(240, 240, 240, 255))
    draw.rectangle([250, 286, 550, 310], outline=(190, 255, 0, 255), width=4)
    frame = pil_to_frame(image)
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    items = [
        SimpleNamespace(text="嗯", confidence=0.90, nx1=0.49, ny1=0.55, nx2=0.51, ny2=0.57, ncx=0.50, ncy=0.56),
        SimpleNamespace(text="不", confidence=0.91, nx1=0.49, ny1=0.65, nx2=0.51, ny2=0.67, ncx=0.50, ncy=0.66),
    ]

    regions = recognizer._read_focus_text_regions(frame, "modal_warning", 0.42, ocr_items=items)

    assert regions
    assert regions[0].name == "modal_button_focus"
    assert regions[0].text == "不"


def test_ui_tree_distinguishes_autoshow_tabs_from_pause_tabs():
    state = describe_ui_state("autoshow_buy_sell", active_tab="剧情", selected_item="车展")

    assert state.title == "购买与出售"
    assert state.tab_scope == "购买与出售顶部分页"
    assert state.path == ("暂停菜单", "暂停菜单 / 车辆", "购买与出售")
    assert "车展" in state.options
    assert any(route.target == "autoshow_showroom" for route in state.children)


def test_v2_autoshow_defaults_to_child_tab_scope_not_pause_story():
    from v2.semantic import ForzaSemanticAnalyzer

    analyzer = ForzaSemanticAnalyzer()
    items = [
        SimpleNamespace(text="剧情", confidence=0.9, nx1=0.08, ny1=0.16, nx2=0.12, ny2=0.18, ncx=0.10, ncy=0.17),
        SimpleNamespace(text="购买与出售", confidence=0.9, nx1=0.14, ny1=0.16, nx2=0.25, ny2=0.18, ncx=0.20, ncy=0.17),
        SimpleNamespace(text="车辆", confidence=0.9, nx1=0.30, ny1=0.16, nx2=0.34, ny2=0.18, ncx=0.32, ncy=0.17),
        SimpleNamespace(text="角色", confidence=0.9, nx1=0.38, ny1=0.16, nx2=0.42, ny2=0.18, ncx=0.40, ncy=0.17),
        SimpleNamespace(text="车展", confidence=0.9, nx1=0.08, ny1=0.62, nx2=0.12, ny2=0.64, ncx=0.10, ncy=0.63),
        SimpleNamespace(text="拍卖场", confidence=0.9, nx1=0.08, ny1=0.70, nx2=0.14, ny2=0.72, ncx=0.11, ncy=0.71),
    ]

    understanding = analyzer.analyze(None, items)

    assert understanding.screen == "autoshow_buy_sell"
    assert understanding.active_tab == "购买与出售"
    assert [tab.label for tab in understanding.autoshow_tabs] == ["剧情", "购买与出售", "车辆", "角色"]


def test_v2_vehicle_buy_grid_is_not_autoshow_menu():
    from v2.semantic import ForzaSemanticAnalyzer

    analyzer = ForzaSemanticAnalyzer()
    items = [
        SimpleNamespace(text="购买车辆", confidence=0.9, nx1=0.05, ny1=0.10, nx2=0.18, ny2=0.13, ncx=0.11, ncy=0.12),
        SimpleNamespace(text="IMPREZA 22B-STI VERSION", confidence=0.9, nx1=0.62, ny1=0.20, nx2=0.82, ny2=0.24, ncx=0.72, ncy=0.22),
        SimpleNamespace(text="1998 斯巴鲁", confidence=0.9, nx1=0.65, ny1=0.24, nx2=0.77, ny2=0.27, ncx=0.71, ncy=0.255),
        SimpleNamespace(text="Space 购买车展车辆票券", confidence=0.9, nx1=0.30, ny1=0.91, nx2=0.45, ny2=0.94, ncx=0.37, ncy=0.925),
        SimpleNamespace(text="Backspace 前往制造商", confidence=0.9, nx1=0.46, ny1=0.91, nx2=0.62, ny2=0.94, ncx=0.54, ncy=0.925),
        SimpleNamespace(text="X 排序", confidence=0.9, nx1=0.15, ny1=0.91, nx2=0.20, ny2=0.94, ncx=0.17, ncy=0.925),
        SimpleNamespace(text="Y 筛选", confidence=0.9, nx1=0.22, ny1=0.91, nx2=0.27, ny2=0.94, ncx=0.245, ncy=0.925),
        SimpleNamespace(text="P 切换详情", confidence=0.9, nx1=0.63, ny1=0.91, nx2=0.72, ny2=0.94, ncx=0.67, ncy=0.925),
        SimpleNamespace(text="L 切换数据", confidence=0.9, nx1=0.73, ny1=0.91, nx2=0.82, ny2=0.94, ncx=0.77, ncy=0.925),
    ]

    understanding = analyzer.analyze(None, items)

    assert understanding.screen == "vehicle_buy_grid"
    assert understanding.active_tab == "购买车辆"
    assert "Back/View" in understanding.hints
    assert "Space" in understanding.hints


def test_v2_manufacturer_grid_is_named_page():
    from v2.semantic import ForzaSemanticAnalyzer

    analyzer = ForzaSemanticAnalyzer()
    items = [
        SimpleNamespace(text="制造商", confidence=0.9, nx1=0.45, ny1=0.12, nx2=0.55, ny2=0.16, ncx=0.50, ncy=0.14),
        SimpleNamespace(text="ABARTH", confidence=0.9, nx1=0.15, ny1=0.20, nx2=0.20, ny2=0.23, ncx=0.175, ncy=0.215),
        SimpleNamespace(text="ALUMICRAFT", confidence=0.9, nx1=0.30, ny1=0.20, nx2=0.38, ny2=0.23, ncx=0.34, ncy=0.215),
        SimpleNamespace(text="AMG TRANSPORT DYNAMICS", confidence=0.9, nx1=0.45, ny1=0.20, nx2=0.60, ny2=0.23, ncx=0.52, ncy=0.215),
        SimpleNamespace(text="ARIEL", confidence=0.9, nx1=0.66, ny1=0.20, nx2=0.72, ny2=0.23, ncx=0.69, ncy=0.215),
        SimpleNamespace(text="A 选择", confidence=0.9, nx1=0.05, ny1=0.92, nx2=0.11, ny2=0.95, ncx=0.08, ncy=0.935),
        SimpleNamespace(text="B 取消", confidence=0.9, nx1=0.12, ny1=0.92, nx2=0.18, ny2=0.95, ncx=0.15, ncy=0.935),
    ]

    understanding = analyzer.analyze(None, items)

    assert understanding.screen == "manufacturer_grid"
    assert understanding.active_tab == "制造商"


def test_v2_buy_flow_design_preview_and_purchase_confirm_pages():
    from v2.semantic import ForzaSemanticAnalyzer

    analyzer = ForzaSemanticAnalyzer()
    design_items = [
        SimpleNamespace(text="推荐设计", confidence=0.9, nx1=0.05, ny1=0.12, nx2=0.20, ny2=0.16, ncx=0.12, ncy=0.14),
        SimpleNamespace(text="出厂颜色", confidence=0.9, nx1=0.22, ny1=0.18, nx2=0.34, ny2=0.24, ncx=0.28, ncy=0.21),
        SimpleNamespace(text="Enter 选择", confidence=0.9, nx1=0.04, ny1=0.91, nx2=0.10, ny2=0.94, ncx=0.07, ncy=0.925),
        SimpleNamespace(text="Y 颜色", confidence=0.9, nx1=0.18, ny1=0.91, nx2=0.24, ny2=0.94, ncx=0.21, ncy=0.925),
        SimpleNamespace(text="Backspace 搜寻", confidence=0.9, nx1=0.25, ny1=0.91, nx2=0.36, ny2=0.94, ncx=0.30, ncy=0.925),
    ]
    preview_items = [
        SimpleNamespace(text="1998 斯巴鲁 Impreza 22B-STI Version", confidence=0.9, nx1=0.08, ny1=0.04, nx2=0.30, ny2=0.07, ncx=0.19, ncy=0.055),
        SimpleNamespace(text="CR 86,000", confidence=0.9, nx1=0.04, ny1=0.84, nx2=0.18, ny2=0.88, ncx=0.11, ncy=0.86),
        SimpleNamespace(text="Enter 选择", confidence=0.9, nx1=0.04, ny1=0.91, nx2=0.10, ny2=0.94, ncx=0.07, ncy=0.925),
        SimpleNamespace(text="X 更改视角", confidence=0.9, nx1=0.18, ny1=0.91, nx2=0.28, ny2=0.94, ncx=0.23, ncy=0.925),
    ]
    color_items = [
        SimpleNamespace(text="出厂颜色", confidence=0.9, nx1=0.04, ny1=0.13, nx2=0.20, ny2=0.17, ncx=0.12, ncy=0.15),
        SimpleNamespace(text="Enter 确定", confidence=0.9, nx1=0.04, ny1=0.91, nx2=0.10, ny2=0.94, ncx=0.07, ncy=0.925),
        SimpleNamespace(text="Esc 返回", confidence=0.9, nx1=0.12, ny1=0.91, nx2=0.20, ny2=0.94, ncx=0.16, ncy=0.925),
    ]
    confirm_items = [
        SimpleNamespace(text="购买车辆", confidence=0.9, nx1=0.43, ny1=0.38, nx2=0.57, ny2=0.42, ncx=0.50, ncy=0.40),
        SimpleNamespace(text="是否要花费 86,000 CR 购买此车辆？", confidence=0.9, nx1=0.36, ny1=0.46, nx2=0.64, ny2=0.50, ncx=0.50, ncy=0.48),
        SimpleNamespace(text="购买", confidence=0.9, nx1=0.45, ny1=0.52, nx2=0.55, ny2=0.56, ncx=0.50, ncy=0.54),
        SimpleNamespace(text="Enter 选择", confidence=0.9, nx1=0.04, ny1=0.91, nx2=0.10, ny2=0.94, ncx=0.07, ncy=0.925),
    ]

    design = analyzer.analyze(None, design_items)
    color = analyzer.analyze(None, color_items)
    preview = analyzer.analyze(None, preview_items)
    confirm = analyzer.analyze(None, confirm_items)

    assert design.screen == "design_grid"
    assert "Y" in design.hints
    assert color.screen == "color_select"
    assert color.selected_item == "出厂颜色"
    assert "A" in color.hints
    assert preview.screen == "car_preview"
    assert preview.selected_item == "IMPREZA 22B-STI VERSION"
    assert "X" in preview.hints
    assert confirm.screen == "purchase_confirm"
    assert confirm.selected_item == "购买"


def test_control_hint_parser_covers_buy_vehicle_bottom_bar():
    hints = parse_control_hints(
        "A 选择  B 返回  X 排序  Y 筛选  Space 购买车展车辆票券  Backspace 前往制造商  P 切换详情  L 切换数据"
    )

    actions = {hint.action for hint in hints}
    assert {"select", "back", "sort", "filter", "buy_voucher", "manufacturer", "toggle_details", "toggle_data"} <= actions


def test_control_hint_parser_marks_event_favorite_as_toggle_not_page():
    hints = parse_control_hints("A 选择 B 返回 X 创建者信息 Y 最爱的赛事 Menu 赛事选项 R 查看赛事信息")
    actions = {hint.action for hint in hints}

    assert "favorite_event" in actions
    assert "creator_info" in actions
    assert "event_options" in actions


def test_eventlab_event_title_extracts_title_lines_after_logo_words():
    assert (
        eventlab_event_title(
            "ANYTHING | GOES | EventLab | 1.3千米 | SPFarm/24 second | 18205,385 | race = 10 skillpoints | HORZON"
        )
        == "SP Farm / 24 second race = 10 skillpoints"
    )


def test_eventlab_filter_state_reads_favorite_checkbox():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (1000, 600), (30, 30, 30, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([320, 145, 680, 178], fill=(0, 0, 0, 255), outline=(190, 255, 0, 255), width=4)
    draw.rectangle([646, 152, 668, 174], outline=(245, 245, 245, 255), width=3)
    unchecked = detect_eventlab_filter_state(pil_to_frame(image), [])
    assert unchecked["focused_row"] == "收藏"
    assert unchecked["favorite_checked"] is False

    draw.line([651, 163, 657, 170, 665, 155], fill=(245, 245, 245, 255), width=4)
    checked = detect_eventlab_filter_state(pil_to_frame(image), [])
    assert checked["favorite_checked"] is True


def test_checkbox_detection_ignores_empty_border_and_requires_tick():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (1000, 600), (30, 30, 30, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([646, 152, 668, 174], outline=(245, 245, 245, 255), width=3)
    bbox = (646 / 1000, 152 / 600, 668 / 1000, 174 / 600)

    assert _checkbox_is_checked(pil_to_frame(image), bbox) is False

    draw.line([651, 163, 657, 170, 665, 155], fill=(245, 245, 245, 255), width=4)
    assert _checkbox_is_checked(pil_to_frame(image), bbox) is True


def test_hybrid_eventlab_filter_actions_toggle_once_then_return():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))

    unchecked = recognizer._actions(
        SimpleNamespace(actions=[]),
        "eventlab_filter",
        0.96,
        [],
        "",
        {"visible": True, "focused_row": "收藏", "favorite_checked": False},
    )
    checked = recognizer._actions(
        SimpleNamespace(actions=[]),
        "eventlab_filter",
        0.96,
        [],
        "",
        {"visible": True, "focused_row": "收藏", "favorite_checked": True},
    )

    assert unchecked[0].button == "A"
    assert checked[0].button == "B"
    assert "取消勾选" in checked[0].reason


def test_hybrid_eventlab_actions_require_target_event_and_22b():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))

    event_actions = recognizer._actions(
        SimpleNamespace(actions=[]),
        "eventlab_favorites",
        0.97,
        [],
        "SP Farm / 24 second race = 10 skillpoints",
        {},
    )
    wrong_event = recognizer._actions(
        SimpleNamespace(actions=[]),
        "eventlab_favorites",
        0.97,
        [],
        "Wakoku Drift Circuit",
        {},
    )
    car_actions = recognizer._actions(
        SimpleNamespace(actions=[]),
        "eventlab_my_cars",
        0.93,
        [],
        "IMPREZA 22B-STI VERSION",
        {},
    )

    assert event_actions[0].button == "A"
    assert wrong_event[0].button == ""
    assert car_actions[0].button == "A"


def test_hybrid_eventlab_actions_use_top_nav_before_event_card():
    recognizer = HybridVisionRecognizer(detector=YoloOnnxDetector(model_path="missing.onnx"))
    v2 = SimpleNamespace(
        actions=[],
        eventlab_tabs=[
            SimpleNamespace(label="热门", x=0.42),
            SimpleNamespace(label="我的收藏", x=0.82),
        ],
    )

    actions = recognizer._actions(
        v2,
        "eventlab_events",
        0.88,
        [],
        "dao ju4",
        {},
        active_tab="热门",
    )

    assert actions[0].button == "RB"
    assert "Y" in actions[0].reason
    assert "active_tab" in actions[0].verify


def test_ui_tree_has_vehicle_buy_and_manufacturer_nodes():
    vehicle = describe_ui_state("vehicle_buy_grid", active_tab="购买车辆", selected_item="IMPREZA 22B-STI VERSION")
    manufacturer = describe_ui_state("manufacturer_grid", active_tab="制造商", selected_item="斯巴鲁")
    design = describe_ui_state("design_grid", active_tab="购买车辆", selected_item="出厂颜色")
    color = describe_ui_state("color_select", active_tab="购买车辆", selected_item="出厂颜色")
    preview = describe_ui_state("car_preview", active_tab="购买车辆", selected_item="IMPREZA 22B-STI VERSION")

    assert vehicle.title == "购买车辆网格"
    assert "前往制造商" in vehicle.options
    assert any(route.target == "manufacturer_grid" for route in vehicle.children)
    assert manufacturer.title == "制造商选择列表"
    assert manufacturer.path[-2:] == ("购买车辆网格", "制造商选择列表")
    assert design.path[-2:] == ("购买车辆网格", "推荐设计")
    assert color.children[0].target == "car_preview"
    assert preview.children[0].target == "purchase_confirm"


def test_lime_focus_boxes_find_wide_button_outline():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (800, 450), (8, 32, 30, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([250, 260, 550, 295], outline=(190, 255, 0, 255), width=4)
    frame = pil_to_frame(image)

    boxes = find_lime_focus_boxes(
        frame,
        (0.20, 0.45, 0.80, 0.75),
        min_width=0.20,
        min_height=0.03,
        max_height=0.12,
        min_aspect=4.0,
    )

    assert boxes
    x1, y1, x2, y2 = boxes[0].bbox
    assert x1 < 0.34 < x2
    assert y1 < 0.62 < y2


def test_relative_model_path_resolves_from_workspace():
    resolved = resolve_asset_path("v3/models/forza_ui_yolo.onnx")

    assert resolved.exists()
