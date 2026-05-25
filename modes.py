"""Mode definitions for the helper UI and controller dispatch."""
from dataclasses import dataclass


MODE_SKILL_POINTS = "skill_points"
MODE_BUY_CAR = "buy_car"
MODE_COMBO = "combo"
MODE_FOREGROUND = "foreground"
MODE_BACKGROUND = "background"

RUNNER_SMART = "smart"
RUNNER_BUY_CAR = "buy_car"
RUNNER_COMBO = "combo"
RUNNER_LEGACY = "legacy"


@dataclass(frozen=True)
class ModeDefaults:
    no_activate: bool = True
    auto_focus: bool = True
    require_foreground: bool = True
    keep_active: bool = False
    resume_after_focus: bool = False


@dataclass(frozen=True)
class ModeDefinition:
    mode_id: str
    label: str
    runner_kind: str
    hint: str
    log_message: str
    defaults: ModeDefaults = ModeDefaults()
    product_visible: bool = True
    uses_drive_seconds: bool = False


MODE_DEFINITIONS = {
    MODE_SKILL_POINTS: ModeDefinition(
        mode_id=MODE_SKILL_POINTS,
        label="模式一：刷技能点（EventLab）",
        runner_kind=RUNNER_SMART,
        hint=(
            "刷技能点：EventLab 智能识别，不盲计时。图1先校准到开始赛事再按A，图2保持油门，"
            "图3按X，图4按A；总运行时间默认0=一直跑；暂停菜单按B返回，截图只在内存中处理。"
        ),
        log_message="已切到【刷技能点】模式。",
    ),
    MODE_BUY_CAR: ModeDefinition(
        mode_id=MODE_BUY_CAR,
        label="模式二：买车加点（先买22B）",
        runner_kind=RUNNER_BUY_CAR,
        hint=(
            "买车加点：第一段先购买默认斯巴鲁 22B。会按 Menu 打开暂停菜单，"
            "进入车展购买 22B，买车辆熟练度抽奖精灵后回车展循环；截图只在内存中处理。"
        ),
        log_message="已切到【买车加点】模式（买 22B + 熟练度抽奖精灵循环）。",
    ),
    MODE_COMBO: ModeDefinition(
        mode_id=MODE_COMBO,
        label="模式三：买车+刷分组合",
        runner_kind=RUNNER_COMBO,
        hint=(
            "组合模式：买车加点→点数不足→进 EventLab 我的收藏，"
            "筛选收藏 + 选 22B 后交给刷技能点 1.5 小时；到点等当前比赛跑完按 A 退出，"
            "回到暂停菜单后再开新一轮买车，循环往复。"
        ),
        log_message="已切到【买车+刷分组合】模式（循环：买车 ↔ 刷分）。",
    ),
    MODE_FOREGROUND: ModeDefinition(
        mode_id=MODE_FOREGROUND,
        label="模式四：前台计时（兜底）",
        runner_kind=RUNNER_LEGACY,
        hint=(
            "前台挂机：游戏保持前台，期间请勿操作其他窗口；"
            "失焦会自动暂停计时并尝试切回。"
        ),
        log_message="已切到【前台挂机】模式（兜底计时）。",
        product_visible=False,
        uses_drive_seconds=True,
    ),
    MODE_BACKGROUND: ModeDefinition(
        mode_id=MODE_BACKGROUND,
        label="模式五：后台尝试（实验，不保证）",
        runner_kind=RUNNER_LEGACY,
        hint=(
            "后台尝试：可去用别的窗口；建议游戏用无边框窗口。"
            "地平线很可能失焦就暂停，本模式不保证有效，但零封号风险。"
        ),
        log_message="已切到【后台尝试】模式（非注入，不保证）。",
        defaults=ModeDefaults(
            no_activate=True,
            auto_focus=False,
            require_foreground=False,
            keep_active=True,
            resume_after_focus=False,
        ),
        product_visible=False,
        uses_drive_seconds=True,
    ),
}

DEFAULT_MODE_ID = MODE_SKILL_POINTS


def get_mode(mode_id):
    return MODE_DEFINITIONS.get(mode_id, MODE_DEFINITIONS[DEFAULT_MODE_ID])


def product_modes():
    return [mode for mode in MODE_DEFINITIONS.values() if mode.product_visible]


def debug_modes():
    return [mode for mode in MODE_DEFINITIONS.values() if not mode.product_visible]
