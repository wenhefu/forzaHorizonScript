# Handoff - Forza Horizon 6 Helper

## 2026-05-26 EXE Packaging Prep

本轮目标：把项目准备成能发给朋友的 exe，并把虚拟手柄驱动依赖做成更像产品的提示，而不是只丢一句“自己去装驱动”。

已完成：

- 修复朋友电脑未安装 ViGEmBus 时 exe 直接崩溃的问题：`gamepad.py` 不再顶层导入 `vgamepad`，改为创建手柄时懒加载；`app_controller.py` 在常驻连接和开始运行前都会先检查 ViGEmBus，未就绪只提示安装/重启，不让 PyInstaller 弹 `VIGEM_ERROR_BUS_NOT_FOUND` 崩溃框。
- 缺少 ViGEmBus 时，`gui.py` 现在会首次启动自动弹出安装说明并打开官方安装页；用户仍需手动运行安装包和批准管理员权限。
- `gui.py` 顶部右侧新增 **GitHub / 反馈** 入口，打开 `https://github.com/wenhefu/forzaHorizonScript`，用于查看更新和问题反馈。
- `release\README.txt` 改成中文朋友版说明，包含仓库地址、ViGEmBus 一次性安装、窗口模式、开始前准备、模式时间含义、风险说明和日志位置。
- 新增 `driver_check.py`：启动时用 `sc.exe query ViGEmBus` 检查 ViGEmBus 是否安装并运行。
- `gui.py` 顶部引导区新增虚拟手柄驱动状态和“安装/修复虚拟手柄驱动”按钮；按钮打开官方 release 页面。
- `gamepad.py` 的虚拟手柄创建失败提示追加官方安装页，朋友电脑没装驱动时更容易自救。
- `build.bat` 改为先安装依赖、跑 `compileall` 和单测，再用 PyInstaller 打包；现在会额外 `--collect-all vgamepad`，并把 `release\README.txt` 复制到 `dist\README.txt`。
- 新增 `release\README.txt`，用于和 exe 一起发给朋友，说明 ViGEmBus 一次性安装、窗口模式和风险边界。
- `app_logging.py` 在 PyInstaller onefile 环境下会把日志写到 exe 同目录的 `logs\forza6helper.log`，避免日志落在临时解压目录。

## 2026-05-26 Post-Race Next Page Fix

现场问题：组合模式到达每轮刷图时间后，`SmartRunner` 在结算页按 `A` 退出赛事，随后游戏会进入“下一站”推荐赛事页面。旧逻辑把这个页面误当成暂停菜单，导致组合模式提前进入下一轮并把 `SmartRunner` 启在错误页面上，随后开始反复按十字键上。

已完成：

- `buy_car_detector.py` 新增 `post_race_next` 状态，用 OCR 区分“下一站”推荐页和真正的暂停菜单；真正暂停菜单仍通过“世界地图 / 收集簿 / 剧情 / 车辆 / 创意中心 / 设置”等关键词识别。
- `combo_runner.py` 在回暂停菜单流程中遇到 `post_race_next` 会按 `B` 返回自由漫游，再重新按 `Menu` 打开暂停菜单，不再直接进入下一轮买车。
- `screen_detector.py` 和 `smart_runner.py` 也新增赛后“下一站”页面兜底识别；如果智能刷图模式单独遇到该页，会按 `B` 退回自由漫游，避免继续按上。
- `buy_car_runner.py` 增加独立买车模式的同类恢复：识别到赛后“下一站”页时按 `B` 回自由漫游，再按 `Menu` 打开暂停菜单。
- 新增 `tests/test_post_race_next.py`，覆盖“下一站”推荐页不应识别为暂停菜单，以及真正暂停菜单仍应保持 `buy_pause_menu`。

追加修正：

- 初版把暂停菜单关键词写得过宽，`购买与出售 / 车展` 页会被误判为 `buy_pause_menu`，导致买车阶段不停按 RB。
- 已把 `购买与出售 / 车展 / 拍卖场 / 车辆通行证 / 票券车辆` 的判断放到暂停菜单判断之前，并移除暂停菜单判断里的泛化关键词 `剧情 / 车辆 / 在线 / 创意中心 / 商店 / 设置`。
- `post_race_next` 现在要求“下一站”出现在左上标题位置，避免暂停菜单中间的“下一站”卡片误触发。
- 测试补充覆盖 `购买与出售 / 车展` 不应被识别成暂停菜单。

## 2026-05-26 Wide Prep UI

本轮目标：把窗口从偏正方形调整成横向长方形，并把用户给的三张准备截图放进产品 UI，而不是只写一段说明。

已完成：

- `gui.py` 改成两列布局：左侧保留主操作区，右侧新增 **开始前准备** 卡片。
- 后续按用户反馈继续拉宽窗口，当前预览约 `1495 x 958`，整体更接近横向桌面工具。
- 右侧三步准备清单使用真实截图缩略图，点击缩略图可弹出大图预览。
- 已移除三步准备卡片里的“已完成”勾选，避免普通用户误以为需要逐项打卡才能运行。
- 运行参数会按模式显示：模式一是 **刷图运行时间**，模式三是 **每轮刷图时间**；模式三旁边提示 `推荐 60；0=默认 90；买车不计时`。
- 运行参数不需要保存按钮，点“开始”时读取当前输入；无效输入会自动回填为安全默认值并写日志。启动倒计时无效回到 `5.0`，刷图时间无效回到 `0.0`，负数会钳到 `0.0`。
- 组合模式的时间语义已修正：界面里的“每轮刷图时间”只控制 EventLab 刷图阶段，买车加点阶段不再消耗这个时间，也不会因为这个时间到而中断买车。模式三填 `0` 时会使用 `config.py` 的 `COMBO_EVENTLAB_FARM_SECONDS` 作为每轮刷图默认值。
- 三步文案已按用户原意优化并完整放入界面：
  1. 把加满点数的 `1998 Subaru Impreza 22B-STI` 加入“车库 -> 我的车辆”的收藏，并把当前驾驶车辆设为这台车。
  2. 把刷技能点赛事放进“创意中心 -> 游玩赛事 -> 我的收藏”的第一个位置，推荐共享代码 `890 169 683`。
  3. 开始前停留在暂停菜单的首个分页，也就是上方分页从“剧情 / 车辆 / 我的地平线 / 在线 / 创意中心 / 商店”开始的页面。
- 三张图片已复制到 `assets/prep/`：
  - `vehicle_22b.png`
  - `eventlab_favorite.png`
  - `pause_home.png`
- `build.bat` 已加入 `--add-data "assets;assets"`，打包 exe 时会带上引导截图。
- `README.md` 已同步开始前准备说明。

验证：

- `.venv\Scripts\python.exe -m compileall -q .` 通过。
- `.venv\Scripts\python.exe -m unittest discover -s tests` 通过。
- 本地生成 GUI 预览图 `logs/gui-preview-wide.png`，窗口约 `1253 x 998`，横向布局和右侧准备清单显示正常。

## 2026-05-26 Product UI Pass

本轮目标：把 GUI 从“开发工具面板”调整成更接近 Codex/Claude 桌面版的安静产品感，同时使用地平线暂停菜单近似的深绿色背景。

已完成：

- `gui.py` 重排为顶部标题/引导、运行模式、运行参数、控制、当前模式提示、运行日志几个清晰区域。
- 顶部新增首次使用引导：**设置 -> 视频 -> 亮度 -> 全屏幕：关闭**，提醒用户先把游戏设为窗口模式。
- 默认界面继续只展示模式一/二/三；高级/调试模式、手动按 A/B、识别一次和高级复选框保持折叠。
- 使用深绿色主背景、浅色内容面板、克制按钮和深色日志区，整体更接近产品版桌面工具。
- `README.md` 同步补充窗口模式引导。

验证：

- `.venv\Scripts\python.exe -m compileall -q .` 通过。
- `.venv\Scripts\python.exe -m unittest discover -s tests` 通过。
- 本地生成 GUI 预览图 `logs/gui-preview.png`，窗口约 `940 x 958`，默认调试区折叠，模式提示已正常显示。

## 2026-05-26 Product Shell Refactor

本轮目标是先把“产品版瘦身”的地基打稳，避免只是把控件隐藏、但旧功能仍通过零散变量暗中影响运行。

已完成：

- 新增 `modes.py`：所有运行模式集中登记，包含模式 id、显示名、runner 类型、默认高级选项、提示文案、是否普通界面可见。
- 新增 `settings.py`：GUI 启动一次运行时会生成不可变 `RuntimeSettings` 快照，runner 不再直接从 Tk 变量里读动态状态。
- 新增 `app_controller.py`：集中管理虚拟手柄、`Runner`/`SmartRunner`/`BuyCarRunner`/`ComboRunner` 生命周期、开始/停止、手动按键、识别入口和旧前台计时的焦点恢复回调。
- `gui.py` 现在只负责窗口渲染、输入框、按钮、日志展示和把当前表单转成 `RuntimeSettings`。
- 普通界面默认只展示模式一/二/三；模式四/五、按 A/B、识别一次和高级复选框放入“显示高级/调试模式”，默认折叠但未删除。
- `README.md` 已同步新的产品/调试分层和代码结构说明。

验证：

- `.venv\Scripts\python.exe -m compileall -q .` 通过。
- `.venv\Scripts\python.exe -m unittest discover -s tests` 通过。
- 轻量模块自检通过：`product_modes() == ['skill_points', 'buy_car', 'combo']`，`debug_modes() == ['foreground', 'background']`，`RuntimeSettings.total_seconds` 正常换算。

后续建议：

1. 再做一层“状态事件”输出，让 runner 发 `stage/message/severity`，GUI 显示稳定的状态卡，不再让普通用户读日志判断进度。
2. 给 `buy_car_detector.py` 和 `screen_detector.py` 加截图/识别回放测试，先覆盖这次现场踩过的 EventLab 我的车辆、我的收藏/历史记录 tab、22B 选车。
3. 打包前补 `packaging/` 目录、PyInstaller spec、版本号、图标、ViGEmBus 检测/安装提示。

## 2026-05-26 Mode Three Field Validation

当前最新状态：

- **模式三已现场跑通关键主链路**：买车加点 -> 技术点数不足 -> 自动退回自由漫游/暂停菜单 -> 创意中心 -> EventLab -> 赛事 -> 我的收藏 -> 选择收藏赛事 -> 单人 -> 我的车辆 -> 筛选收藏 -> 选择 22B -> 进入 EventLab 开始赛事菜单 -> 交给模式一刷图。
- 组合模式每轮 EventLab 刷图时长现在由 GUI 的 **每轮刷图时间** 控制，推荐填 60 分钟；填 0 时才使用 `config.py` 的 `COMBO_EVENTLAB_FARM_SECONDS = 90 * 60` 作为默认值。
- 到达每轮刷图时间后，`SmartRunner` 不会立刻打断比赛；它会继续跑到下一次结算页，在原本要按 X 重开的位置改按 A 退出，再交回 `ComboRunner`。
- **尚未现场完整验证**：每轮刷图时间到点后能否稳定等当前比赛结束、按 A 退出、回自由漫游、打开暂停菜单并进入下一轮买车。因为验证周期太长，目前只能确认前半段到刷图入口已成功。

本轮修复过的关键问题：

- EventLab “我的车辆”页在筛选收藏后，顶部会从“当前车辆/购买车辆”变成动态品牌 tab。检测器已改为使用“我的车辆”标题、底部“筛选/前往制造商/排序/切换详情/切换数据”提示和卡片文本综合判断，不再误判为 `buy_sell_menu`。
- 22B 选择不再写死位置，继续使用 OCR 文本列 + 当前高亮列定位，适配朋友收藏列表里 22B 位置不同的情况。
- EventLab 顶部 tab 切到“我的收藏”时，新增 active tab 识别：`7=我的收藏`，`8=我的历史记录`。如果按 RB 过头到历史记录，组合模式会按 LB 回退，而不是继续向右。
- 若 GUI/脚本中途停在 EventLab 页面，模式三重新开始时会尝试从当前 EventLab 中途页续接，不会强行从买车阶段重跑。

当前建议的短期验证：

1. 把 `COMBO_EVENTLAB_FARM_SECONDS` 临时改小，例如 `5 * 60` 或 `10 * 60`，专门验证“刷图到点 -> 等结算 -> A 退出 -> 回暂停菜单 -> 下一轮买车”。
2. 验证通过后再改回 `90 * 60`。
3. 日常使用时仍建议保持 Forza 前台，不要点击其它窗口；失焦时游戏会暂停或进菜单，这是游戏行为，当前工具不通过 hook/injection 绕过。

产品化/打包方向：

- 当前最稳的输入方式仍然是 **ViGEmBus + vgamepad 虚拟 Xbox 手柄**。打包成 exe 可行，但朋友电脑需要安装 ViGEmBus 驱动；exe 本身不能完全免驱替代内核级虚拟手柄。
- 不依赖虚拟手柄的替代方案主要是键盘输入或更底层的窗口/输入注入。键盘方案改动中等，但可靠性大概率更差，尤其是油门长按、菜单按键、焦点切换和 Forza 对后台输入的处理。hook/fake-focus 方案风险高，不建议内置。
- 推荐打包策略：保留虚拟手柄；提供一个正常的 exe，加一个首次运行检查/提示页，检测 ViGEmBus 是否安装并运行，缺失时提示用户安装。

GUI 精简建议：

- 给普通用户保留：运行模式、开始/停止、打开日志、切回游戏、总运行时间、模式三状态提示。
- 把“按A确认/按B返回/识别一次/高级复选框”折叠到“高级/调试”区域，默认隐藏。
- 可以去掉或弱化“模式四/模式五”：它们现在主要是实验/兜底，容易让朋友误选；产品版建议默认只展示模式一、模式二、模式三。

## 2026-05-25 Stable Checkpoint

Workspace: `D:\地平线6脚本`

目前已经现场验证的稳定能力：

- **模式一：刷技能点（EventLab）** 已能通过截图识别循环执行：图 1 开始赛事按 A、比赛中保持油门、结果页按 X、重开确认页按 A，再回到开始赛事页继续。
- **模式二：买车加点（先买 22B）** 已能从暂停菜单进入买车链路，购买斯巴鲁 22B，进入车辆熟练度，按固定 22B 加点路径买到抽奖精灵，然后回到买车入口继续循环。
- 买车链路现在依赖 OCR + 画面颜色双重确认，重点保护点包括：购买新车入口、车展、制造商列表、斯巴鲁品牌、22B 车辆卡、购买确认、车辆页、升级页、车辆熟练度页。
- 当前模式二在技能点不足时会停止，避免无点数时继续误操作。这个“点数不足”页面是下一阶段组合模式的切换点。

当前最重要的安全边界：

- 不注入游戏进程，不做 fake-focus/hook。
- 截图只在内存中处理，不把识别截图落盘。
- 买车路径只有在确认目标是 22B 后才允许进入设计/颜色/购买确认；购买确认若未 armed 会按 B 取消。

下一阶段目标：

- 新增一个组合模式：先跑买车加点，遇到“点数不足”后退出到自由漫游，打开暂停菜单，进入创意中心/EventLab/赛事/我的收藏，启动刷技能点 EventLab；刷够一段时间后再回到买车加点循环。
- 组合模式建议用新的编排 runner 实现，复用 `BuyCarRunner` 和 `SmartRunner` 的检测/输入逻辑，不直接破坏已经验证的模式一、模式二。

## 2026-05-25 Combined Mode Update

已新增 **模式三：买车+刷分组合（实验）**。

当前组合流程：

- 先运行买车加点流程。
- `BuyCarRunner` 现在会把“技术点数不足/不够购买额外加成”识别为明确的 `points_exhausted` 停止原因。
- `ComboRunner` 在该停止原因出现后，按 A 关闭弹窗，连续 B 返回到自由漫游，再按 Menu 打开暂停菜单。
- 组合模式会一边按 RB 一边识别，确认到“创意中心”后停止切 tab，按 A 进入 EventLab。
- 进入 EventLab 后，按 A 到赛事页，再一边按 RB 一边识别，确认到“我的收藏”后按 A。
- 进入收藏赛事后，确认/处理“选择比赛类型”，默认按 A 选“单人”。
- 到“我的车辆”页后按 Y 打开筛选，确认“收藏”被勾选后按 B 返回。
- 在筛选后的车辆列表里，用 OCR 文本和绿色高亮列计算 22B 的位置，只有确认当前高亮是 22B 后才按 A。
- 只有在现有 `SmartRunner` 能识别到 EventLab 开始赛事菜单时，才把控制权交给刷技能点模式；交接后默认固定刷 2 小时。

尚未完成：

- 从刷技能点阶段自动判断“刷够点数了”并回到买车流程。当前组合模式进入 EventLab 后会继续按模式一刷，直到手动停止或总运行时间到。

Date: 2026-05-24
Workspace: `D:\地平线6脚本`
Repository: `https://github.com/wenhefu/forzaHorizonScript.git`

## Current State

The repository was cloned directly into `D:\地平线6脚本` without an extra `forzaHorizonScript` directory.

Local setup completed:

- Created `.venv` in the project directory.
- Installed Python dependencies from `requirements.txt`.
- Installed `pyinstaller` for packaging support.
- Confirmed ViGEmBus is installed and running.
- Confirmed `vgamepad` can create a virtual Xbox 360 controller.

Runtime command:

```powershell
.\.venv\Scripts\python.exe gui.py
```

## Main Problem Investigated

The original goal was to automate a Forza Horizon 6 EventLab loop with a virtual Xbox controller.

The hard blocker is focus behavior:

- Clicking the helper UI makes Forza lose focus.
- Forza may pause, show menus, or show a controller disconnected modal.
- When the game pauses or leaves the race flow, a fixed wall-clock timer becomes wrong.
- In one observed run, the script advanced after the configured 44 seconds, but the actual game result screen showed about 3 minutes, so the script and game state had diverged.

## Research Summary

I checked how PC/AAA games generally handle background running and focus loss.

Findings:

- Clean background execution usually requires the game itself to support background input/running.
- Microsoft GameInput has a focus policy for background input, but it is something the game must opt into.
- Borderless window mode helps only for games that do not pause on focus loss; it is not guaranteed.
- Tools that force games to behave as foreground/background-multiplayer apps usually rely on hook/injection/fake-focus techniques.
- Hook/injection approaches such as Special K, Nucleus/ProtoInput-style fake focus, or similar Windows API interception are riskier around anti-cheat and are not appropriate to casually embed in this helper.

Useful references:

- Microsoft GameInput focus policy: https://learn.microsoft.com/en-us/gaming/gdk/docs/reference/input/gameinput-v0/enums/gameinputfocuspolicy-v0
- Forza forum discussion about pausing on alt-tab/focus loss: https://forums.forza.net/t/please-do-not-pause-with-alt-tab-lose-focus/537904
- Nucleus/ProtoInput fake focus/background input concepts: https://www.splitscreen.me/docs/kbm-setup and https://www.splitscreen.me/docs/proto/
- Special K anti-cheat warning context: https://wiki.special-k.info/en/SpecialK/Global

Conclusion: without injecting/hooking the game process, this helper cannot guarantee that Forza continues running fully in the background.

## Code Changes Made

### Logging

Added `app_logging.py`.

The app now writes persistent logs to:

```text
logs\forza6helper.log
```

The log records:

- Python/platform/package versions.
- ViGEmBus service status.
- Virtual gamepad creation.
- Foreground/focus actions.
- Runner steps and virtual gamepad input.
- Runtime exceptions.

`logs/` was added to `.gitignore`.

### Virtual Controller Lifecycle

Changed the design from "create a virtual gamepad only when Start is pressed" to "create and keep the virtual gamepad connected while the GUI is open."

Reason:

- Forza can show "controller disconnected" when the virtual device appears/disappears.
- Keeping the virtual controller alive should avoid unnecessary device disconnect/reconnect behavior.

`gamepad.py` now:

- Accepts a logger.
- Logs controller operations.
- Uses a lock around `vgamepad` calls.
- Fixes the trigger API call from `value=` to `value_float=`.

### GUI

`gui.py` now includes:

- Persistent virtual controller connection on startup.
- `打开日志` button.
- `切回游戏` button.
- Manual `按A确认` and `按B返回` buttons.
- "游戏模式：点击本窗口不抢焦点" option.
- "开始后自动切回游戏窗口" option.
- "只在游戏前台时计时（失焦自动暂停脚本）" option.
- "切回后按 A 确认/恢复控制器" option, currently default off.

### Focus Handling

Expanded `focus.py` with:

- Window title lookup.
- Current foreground title lookup.
- Forza foreground detection.
- Windows foreground activation using `SetForegroundWindow`, `BringWindowToTop`, `AttachThreadInput`, etc.
- Best-effort no-activate/topmost helper window mode.

Important limitation:

- Windows foreground APIs cannot force true background running.
- The helper can try to bring Forza back to the foreground, but cannot make Forza keep simulating while genuinely backgrounded.

### Runner Behavior

`runner.py` now supports foreground-aware timing:

- If configured, scripted time only advances while Forza is the foreground window.
- When Forza loses focus, the script logs the event and pauses its own timer.
- When Forza returns to foreground, the script continues from the same step instead of blindly advancing to the next lap.

This is the safest non-injection path identified so far.

## Current Recommended Product Direction

Do not try to solve "Forza fully runs in background" inside this helper unless the user explicitly accepts hook/injection risk.

Recommended safe behavior:

- Keep Forza foreground while automation runs.
- If focus is lost, pause the script timer and input sequence.
- Try to bring Forza back to foreground.
- Do not auto-press menu buttons unless explicitly enabled.
- Avoid user interaction with other windows during a run.

## Testing Performed

Verified:

- Python compile check passes:

```powershell
.\.venv\Scripts\python.exe -m compileall -q .
```

- `vgamepad` can create a virtual controller.
- `Gamepad.apply(throttle=1.0)` works after fixing `value_float`.
- Runner can run repeated steps without immediately crashing.
- Foreground-aware runner simulation pauses timing while foreground check returns false and resumes after it returns true.
- GUI starts and creates a persistent virtual gamepad.

## Known Issues / Open Questions

- Actual Forza behavior still needs live validation after the foreground-aware timing change.
- If Forza pauses itself despite being brought back to foreground, the helper cannot infer menu/race state from controller inputs alone.
- The configured `DRIVE_SECONDS = 44.0` may be too short for the user's observed route. One screenshot showed a completed run at `03:00.564`; the drive time may need to be closer to 180-185 seconds.
- The previous global hotkey `Ctrl+Alt+F8` registered successfully, but one user test did not show the hotkey being received while Forza was focused.
- A true "run in background while I use the PC" feature likely requires game support or risky hook/fake-focus tooling.

## Next Steps

1. Test the current foreground-aware build with Forza in the foreground.
2. Confirm logs show "检测到游戏失焦，暂停脚本计时" when focus is intentionally changed.
3. Set `每圈前进时间` to match the actual route duration.
4. Only after safe foreground automation works, decide whether to investigate hook/fake-focus tools separately.
