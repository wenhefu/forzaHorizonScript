# Handoff - Forza Horizon 6 Helper

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
