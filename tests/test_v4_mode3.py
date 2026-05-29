from types import SimpleNamespace
import threading
import time

from v4.decision import (
    RouteContext,
    decide_mode3_navigation,
    is_22b,
    is_target_event,
    normalize_button,
)
from v4.mode3_runner import V4Mode3Runner
from v4.watchdog import ProgressWatchdog


def fake_v3(
    screen,
    active_tab="",
    selected_item="",
    confidence=0.90,
    actions=None,
    filter_state=None,
    scroll_state=None,
    ocr_regions=None,
):
    return SimpleNamespace(
        screen=screen,
        active_tab=active_tab,
        selected_item=selected_item,
        confidence=confidence,
        actions=actions or [],
        filter_state=filter_state or {},
        scroll_state=scroll_state or {},
        ocr_regions=ocr_regions or [],
    )


def test_button_mapping_accepts_v3_labels():
    assert normalize_button("A") == "a"
    assert normalize_button("Menu") == "start"
    assert normalize_button("DPadUp") == "dpad_up"
    assert normalize_button("Back/View") == "back"


def test_target_matchers_cover_mode3_goal_names():
    assert is_target_event("SP Farm / 24 second race = 10 skillpoints")
    assert is_22b("IMPREZA 22B-STI VERSION")
    assert is_22b("MPREZA 22B-STI VERSI...")


def test_filter_unchecked_toggles_once_checked_returns():
    unchecked = decide_mode3_navigation(
        fake_v3(
            "eventlab_filter",
            filter_state={"visible": True, "focused_row": "收藏", "favorite_checked": False},
        ),
        RouteContext(),
    )
    assert unchecked.button == "A"
    assert "勾选" in unchecked.reason

    checked = decide_mode3_navigation(
        fake_v3(
            "eventlab_filter",
            filter_state={"visible": True, "focused_row": "收藏", "favorite_checked": True},
        ),
        RouteContext(),
    )
    assert checked.button == "B"
    assert "取消" in checked.reason


def test_eventlab_uses_top_nav_not_y_for_favorites():
    decision = decide_mode3_navigation(
        fake_v3("eventlab_events", active_tab="热门", selected_item="dao ju4"),
        RouteContext(),
    )
    assert decision.button in {"LB", "RB"}
    assert "Y" in decision.reason


def test_eventlab_does_not_enter_wrong_event():
    context = RouteContext(eventlab_card_moves=8)
    decision = decide_mode3_navigation(
        fake_v3("eventlab_favorites", active_tab="我的收藏", selected_item="dao ju4"),
        context,
    )
    assert decision.button == ""
    assert decision.name == "target_event_not_found"


def test_eventlab_target_event_and_22b_are_enterable():
    event = decide_mode3_navigation(
        fake_v3("eventlab_favorites", active_tab="我的收藏", selected_item="SP Farm / 24 second race = 10 skillpoints"),
        RouteContext(),
    )
    assert event.button == "A"

    car = decide_mode3_navigation(
        fake_v3("eventlab_my_cars", selected_item="IMPREZA 22B-STI VERSION"),
        RouteContext(favorite_filter_done=True),
    )
    assert car.button == "A"


def test_race_hud_is_terminal_navigation_success():
    decision = decide_mode3_navigation(fake_v3("race_hud"), RouteContext())
    assert decision.name == "arrived_race_hud"
    assert decision.terminal
    assert decision.button == ""


def test_race_pause_menu_returns_to_existing_race_not_locked_tiles():
    decision = decide_mode3_navigation(fake_v3("race_pause_menu", selected_item="赛事暂停菜单（带锁功能）"), RouteContext())
    assert decision.name == "resume_from_race_pause_menu"
    assert decision.button == "B"
    assert "带锁" in decision.reason


def test_upgrade_submenu_backs_out_instead_of_switching_pause_tabs():
    decision = decide_mode3_navigation(
        fake_v3("upgrade_menu", active_tab="车辆", selected_item="车辆熟练度"),
        RouteContext(),
    )
    assert decision.name == "back_out_from_buy_flow"
    assert decision.button == "B"


def test_autoshow_child_pages_back_out_during_eventlab_navigation():
    for screen in (
        "autoshow_buy_sell",
        "autoshow_showroom",
        "vehicle_buy_grid",
        "manufacturer_grid",
        "design_grid",
        "color_select",
        "car_preview",
        "purchase_confirm",
        "garage_my_cars",
    ):
        decision = decide_mode3_navigation(fake_v3(screen, selected_item="not route"), RouteContext())
        assert decision.name == "back_out_from_buy_flow"
        assert decision.button == "B"


def test_buy_phase_owns_upgrade_and_autoshow_children():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    for screen in ("upgrade_menu", "autoshow_buy_sell", "vehicle_buy_grid", "purchase_confirm"):
        snapshot = SimpleNamespace(
            smart_state="prestart",
            smart_confidence=0.95,
            v3=fake_v3(screen, selected_item="not route", confidence=0.90),
        )
        assert not V4Mode3Runner._buy_phase_can_handoff_to_v4(runner, snapshot)


def test_eventlab_home_requires_confirmed_eventlab_focus():
    mismatch = decide_mode3_navigation(
        fake_v3("eventlab_home", active_tab="在线", selected_item="Horizon Play"),
        RouteContext(),
    )
    assert mismatch.button == ""
    assert mismatch.name == "eventlab_home_pause_tab_mismatch"

    unknown_focus = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item=""),
        RouteContext(),
    )
    assert unknown_focus.button == ""
    assert unknown_focus.name == "eventlab_home_focus_unknown"

    garage_layout = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="车库布局"),
        RouteContext(),
    )
    assert garage_layout.name == "move_creative_focus_to_eventlab"
    assert garage_layout.button == "DPadUp"

    confirmed = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="eventlab"),
        RouteContext(),
    )
    assert confirmed.button == "A"

    browse_events = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="浏览赛事"),
        RouteContext(),
    )
    assert browse_events.name == "enter_eventlab_events"
    assert browse_events.button == "A"

    play_events = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="游玩赛事"),
        RouteContext(),
    )
    assert play_events.name == "enter_eventlab_events"
    assert play_events.button == "A"


def test_locked_feature_modal_closes_known_ok_once():
    decision = decide_mode3_navigation(
        fake_v3("modal_warning", active_tab="在线", selected_item="功能尚未解锁"),
        RouteContext(),
    )
    assert decision.name == "close_locked_feature_modal"
    assert decision.button == "A"


def test_restart_event_modal_confirms_once():
    decision = decide_mode3_navigation(
        fake_v3("modal_warning", selected_item="重新开始赛事"),
        RouteContext(),
    )
    assert decision.name == "confirm_restart_event"
    assert decision.button == "A"


def test_eventlab_home_does_not_retry_after_locked_modal():
    decision = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="eventlab"),
        RouteContext(locked_feature_seen=True),
    )
    assert decision.name == "back_out_after_locked_feature"
    assert decision.button == "B"

    after_backouts = decide_mode3_navigation(
        fake_v3("eventlab_home", selected_item="eventlab"),
        RouteContext(locked_feature_seen=True, locked_backouts=2),
    )
    assert after_backouts.name == "eventlab_locked_after_retry"
    assert after_backouts.button == ""


def test_creative_hub_does_not_reenter_locked_eventlab():
    decision = decide_mode3_navigation(
        fake_v3("pause_creative_hub", active_tab="创意中心", selected_item="eventlab"),
        RouteContext(locked_feature_seen=True),
    )
    assert decision.name == "eventlab_feature_locked"
    assert decision.button == ""


def test_watchdog_tracks_progress_and_stall():
    watchdog = ProgressWatchdog(timeout_seconds=0.01, max_recoveries=1)
    assert watchdog.observe("route", "a") is True
    assert watchdog.observe("route", "a") is False
    import time

    time.sleep(0.02)
    assert watchdog.stalled()
    assert watchdog.can_recover()
    watchdog.note_recovery()
    assert not watchdog.can_recover()


def test_runner_does_not_treat_please_wait_as_controller_disconnect():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(
        smart_state="controller_disconnected",
        smart_confidence=0.90,
        v3=fake_v3("modal_warning", selected_item="请稍候", confidence=0.86),
    )
    decision = V4Mode3Runner._decide(runner, snapshot, RouteContext())
    assert decision.button == ""
    assert decision.name == "wait_modal_loading"


def test_runner_ignores_smart_prestart_when_v3_sees_buy_flow_page():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(
        smart_state="prestart",
        smart_confidence=0.95,
        v3=fake_v3("vehicle_mastery", active_tab="车辆", selected_item="XP", confidence=0.94),
    )

    decision = V4Mode3Runner._decide(runner, snapshot, RouteContext())
    assert decision.name == "back_out_from_buy_flow"
    assert not decision.terminal
    assert not V4Mode3Runner._buy_phase_can_handoff_to_v4(runner, snapshot)


def test_runner_allows_smart_prestart_only_when_v3_is_ambiguous_or_race_menu():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    snapshot = SimpleNamespace(
        smart_state="prestart",
        smart_confidence=0.95,
        v3=fake_v3("unknown", selected_item="", confidence=0.0),
    )

    decision = V4Mode3Runner._decide(runner, snapshot, RouteContext())
    assert decision.name == "arrived_race_menu"
    assert decision.terminal
    assert V4Mode3Runner._buy_phase_can_handoff_to_v4(runner, snapshot)

    start_event_menu = SimpleNamespace(
        smart_state="prestart",
        smart_confidence=0.99,
        v3=fake_v3("pause_story", selected_item="开始竞赛赛事", confidence=0.97),
    )
    decision = V4Mode3Runner._decide(runner, start_event_menu, RouteContext())
    assert decision.name == "arrived_race_menu"
    assert decision.terminal


def test_farm_phase_watchdog_stops_stuck_smart_runner():
    class FakeSmartRunner:
        def __init__(self):
            self.exit_reason = None
            self.stop_called = False
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs

        def is_running(self):
            return not self.stop_called

        def stop(self):
            self.stop_called = True
            self.exit_reason = "manual_stop"

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.smart_runner = FakeSmartRunner()
    runner.watchdog_seconds = 0.01
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[])
    runner._log = lambda message: None
    runner._sleep = lambda _seconds: (time.sleep(0.002) or True)

    assert V4Mode3Runner._run_farm_phase(runner, 0.001, auto_focus=False, require_foreground=True)
    assert runner.smart_runner.stop_called
    assert runner.smart_runner.started_with["total_seconds"] == 0.001
    assert any("farm_watchdog_stop" in item for item in runner.report.errors)


def test_exit_after_farm_keeps_verifying_after_idle_menu_press():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner._log = lambda message: None
    runner._sleep = lambda _seconds: True
    runner._ensure_foreground = lambda *args, **kwargs: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(v3=fake_v3("post_race_next", selected_item="HIDE"), smart_state="", smart_confidence=0.0),
            SimpleNamespace(v3=fake_v3("idle_showcase", selected_item=""), smart_state="", smart_confidence=0.0),
            SimpleNamespace(v3=fake_v3("pause_story", active_tab="剧情", selected_item="开始竞赛赛事"), smart_state="", smart_confidence=0.0),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._exit_after_farm(runner, SimpleNamespace(), False, True)
    assert taps == ["b", "start"]


def test_exit_after_farm_accepts_race_menu_as_safe_handoff():
    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner._log = lambda message: None
    runner._sleep = lambda _seconds: True
    runner._ensure_foreground = lambda *args, **kwargs: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("race_menu", selected_item="开始竞赛赛事"),
        smart_state="",
        smart_confidence=0.0,
    )

    assert V4Mode3Runner._exit_after_farm(runner, SimpleNamespace(), False, True)
    assert taps == []


def test_buy_phase_watchdog_stops_stuck_buy_runner():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.stop_called = False
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs

        def is_running(self):
            return not self.stop_called

        def stop(self):
            self.stop_called = True

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 0.01
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: (time.sleep(0.002) or True)
    runner._record_step = lambda *args, **kwargs: None
    runner._write_attention_report = lambda *args, **kwargs: "attention.json"
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("vehicle_buy_grid", selected_item="WRX STI"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )

    assert not V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.stop_called
    assert runner.buy_runner.started_with["total_seconds"] is None
    assert any("buy_phase_watchdog_stop" in item for item in runner.report.errors)


def test_buy_phase_world_map_recovery_closes_map_and_restarts():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            if self.start_count >= 2:
                self.stop_reason = "points_exhausted"
                return False
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

        def _invalidate_ocr(self):
            pass

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 0.01
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._pad_provider = lambda: SimpleNamespace(tap=lambda *args, **kwargs: None)
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: (time.sleep(0.002) or True)
    runner._record_step = lambda *args, **kwargs: None
    runner._write_attention_report = lambda *args, **kwargs: "attention.json"
    taps = []
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("world_map"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 2
    assert runner.buy_runner.stop_count == 1
    assert taps == ["b"]


def test_buy_phase_preflight_skips_buy_runner_when_already_on_eventlab_route():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("eventlab_home", selected_item="车库布局"),
        smart_state="",
        smart_confidence=0.0,
        elapsed_ms=1.0,
    )

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_preflight_backs_out_of_autoshow_child_before_starting_buy_runner():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.stop_reason = "points_exhausted"
            self.running = False

        def is_running(self):
            return self.running

        def stop(self):
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("autoshow_buy_sell", active_tab="角色", selected_item="自定义角色"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("pause_story", active_tab="剧情", selected_item="世界地图"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["b"]
    assert runner.buy_runner.start_count == 1


def test_buy_phase_preflight_dismisses_controller_before_smart_handoff():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("controller_disconnected", selected_item="controller"),
                smart_state="controller_disconnected",
                smart_confidence=0.99,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("race_pause_menu", selected_item="return to race"),
                smart_state="",
                smart_confidence=0.90,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["a"]
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_preflight_hands_restart_modal_to_v4_navigation():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    runner._recognize = lambda: SimpleNamespace(
        v3=fake_v3("modal_warning", selected_item="重新开始赛事"),
        smart_state="confirm_restart",
        smart_confidence=0.99,
        elapsed_ms=1.0,
    )

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_preflight_opens_pause_for_driving_state_then_starts_buy_runner():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.stop_reason = "points_exhausted"
            self.running = False

        def is_running(self):
            return self.running

        def stop(self):
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("unknown", selected_item=""),
                smart_state="racing",
                smart_confidence=0.91,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("pause_story", active_tab="story", selected_item="world map"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["start"]
    assert runner.buy_runner.start_count == 1


def test_buy_phase_preflight_driving_state_hands_off_when_pause_is_race_pause():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    taps = []
    runner._pad_provider = lambda: SimpleNamespace()
    runner._tap = lambda _pad, button, **kwargs: (taps.append(button) or True)
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("unknown", selected_item=""),
                smart_state="racing",
                smart_confidence=0.91,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("race_pause_menu", active_tab="race pause", selected_item="return to race"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert taps == ["start"]
    assert runner.buy_runner.start_count == 0
    assert runner.buy_runner.stop_count == 0


def test_buy_phase_monitor_hands_off_after_buy_runner_started():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            return self.running

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("vehicle_buy_grid", selected_item="WRX STI"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("eventlab_home", selected_item="eventlab"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 1
    assert runner.buy_runner.stop_count == 1


def test_buy_phase_monitor_keeps_buy_runner_on_buy_pages_even_if_smart_false_prestart():
    class FakeBuyRunner:
        def __init__(self):
            self.stop_reason = None
            self.running = False
            self.start_count = 0
            self.stop_count = 0
            self.running_checks = 0
            self._thread = None

        def start(self, **kwargs):
            self.started_with = kwargs
            self.start_count += 1
            self.running = True

        def is_running(self):
            if not self.running:
                return False
            self.running_checks += 1
            if self.running_checks == 1:
                return True
            self.stop_reason = "points_exhausted"
            self.running = False
            return False

        def stop(self):
            self.stop_count += 1
            self.running = False

    runner = V4Mode3Runner.__new__(V4Mode3Runner)
    runner.buy_runner = FakeBuyRunner()
    runner.watchdog_seconds = 1.0
    runner._stop = threading.Event()
    runner.report = SimpleNamespace(errors=[], reports=[])
    runner._log = lambda message: None
    runner.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    runner._sleep = lambda _seconds: True
    runner._record_step = lambda *args, **kwargs: None
    snapshots = iter(
        [
            SimpleNamespace(
                v3=fake_v3("vehicle_buy_grid", selected_item="WRX STI"),
                smart_state="",
                smart_confidence=0.0,
                elapsed_ms=1.0,
            ),
            SimpleNamespace(
                v3=fake_v3("vehicle_buy_grid", selected_item="IMPREZA 22B-STI VERSION"),
                smart_state="prestart",
                smart_confidence=0.92,
                elapsed_ms=1.0,
            ),
        ]
    )
    runner._recognize = lambda: next(snapshots)

    assert V4Mode3Runner._run_buy_phase(runner, auto_focus=False, require_foreground=True)
    assert runner.buy_runner.start_count == 1
    assert runner.buy_runner.stop_count == 0
