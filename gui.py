"""Simple GUI for the FH6 skill-point farm. Package to .exe with build.bat (on Windows)."""
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

from app_logging import LOG_PATH, log_startup_diagnostics, setup_logging
import config
import focus
from gamepad import Gamepad
from hotkeys import GlobalHotkey
from runner import Runner
from sequences import farm_sequence


class App:
    def __init__(self, root):
        self.root = root
        root.title("地平线6 刷分助手")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.log_q = queue.Queue()
        self.command_q = queue.Queue()
        self.logger = setup_logging()
        log_startup_diagnostics(self.logger)

        self.pad = None
        self.pad_error = None
        self.pad_lock = threading.Lock()

        self.runner = Runner(on_log=self._log, logger=self.logger, pad_provider=self.get_gamepad)
        self.keeper = None
        self.hotkey = GlobalHotkey(on_press=self._enqueue_toggle, on_log=self._log)

        self.startup_var = tk.StringVar(value=str(config.STARTUP_DELAY))
        self.drive_var = tk.StringVar(value=str(config.DRIVE_SECONDS))
        self.total_var = tk.StringVar(value=str(config.TOTAL_MINUTES))
        self.keep_var = tk.BooleanVar(value=False)
        self.auto_focus_var = tk.BooleanVar(value=True)
        self.no_activate_var = tk.BooleanVar(value=True)
        self.require_foreground_var = tk.BooleanVar(value=True)
        self.resume_var = tk.BooleanVar(value=False)

        frm = ttk.Frame(root, padding=12)
        frm.grid(row=0, column=0)

        fields = [
            ("启动倒计时（秒）", self.startup_var),
            ("每圈前进时间（秒）", self.drive_var),
            ("总运行时间（分钟，0=一直跑）", self.total_var),
        ]
        r = 0
        for label, var in fields:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=var, width=10).grid(row=r, column=1, pady=3)
            r += 1

        btns = ttk.Frame(frm)
        btns.grid(row=r, column=0, columnspan=2, pady=(8, 4))
        r += 1
        self.start_btn = ttk.Button(btns, text="开始", command=self.on_start)
        self.start_btn.grid(row=0, column=0, padx=4)
        self.stop_btn = ttk.Button(btns, text="停止", command=self.on_stop, state="disabled")
        self.stop_btn.grid(row=0, column=1, padx=4)
        self.log_btn = ttk.Button(btns, text="打开日志", command=self.open_log)
        self.log_btn.grid(row=0, column=2, padx=4)
        self.focus_btn = ttk.Button(btns, text="切回游戏", command=self.activate_game)
        self.focus_btn.grid(row=0, column=3, padx=4)
        self.confirm_btn = ttk.Button(btns, text="按A确认", command=lambda: self.tap_button("a"))
        self.confirm_btn.grid(row=1, column=0, padx=4, pady=(6, 0))
        self.back_btn = ttk.Button(btns, text="按B返回", command=lambda: self.tap_button("b"))
        self.back_btn.grid(row=1, column=1, padx=4, pady=(6, 0))

        ttk.Checkbutton(frm, text="游戏模式：点击本窗口不抢焦点",
                        variable=self.no_activate_var,
                        command=self.apply_game_mode).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="开始后自动切回游戏窗口",
                        variable=self.auto_focus_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="只在游戏前台时计时（失焦自动暂停脚本）",
                        variable=self.require_foreground_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="切回后按 A 确认/恢复控制器",
                        variable=self.resume_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Checkbutton(frm, text="失焦时尝试保持运行（实验性；建议先用无边框窗口）",
                        variable=self.keep_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Label(frm, text="运行时不要操作其他窗口；如果失焦，脚本计时会暂停，回到游戏前台后继续。",
                  foreground="#666", wraplength=320).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        self.log = scrolledtext.ScrolledText(frm, width=46, height=12, state="disabled")
        self.log.grid(row=r, column=0, columnspan=2, pady=(8, 0))
        self._log(f"日志文件：{LOG_PATH}")
        self.hotkey.start()
        self.root.after(300, self.apply_game_mode)
        self.root.after(500, self.connect_gamepad_async)

        self.root.after(100, self._tick)

    def _log(self, msg):
        self.logger.info(msg)
        self.log_q.put(msg)

    def _append(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _enqueue_toggle(self):
        self.logger.info("Ctrl+Alt+F8 pressed")
        self.command_q.put("toggle")

    def connect_gamepad_async(self):
        threading.Thread(target=self._connect_gamepad_worker, name="gamepad-connect", daemon=True).start()

    def _connect_gamepad_worker(self):
        try:
            self.get_gamepad()
            self._log("虚拟手柄已常驻连接。")
        except Exception as exc:
            self.logger.exception("Persistent gamepad connection failed")
            self._log(f"虚拟手柄连接失败：{exc}")

    def get_gamepad(self):
        with self.pad_lock:
            if self.pad:
                return self.pad
            if self.pad_error:
                raise self.pad_error
            try:
                self.pad = Gamepad(logger=self.logger)
                return self.pad
            except Exception as exc:
                self.pad_error = exc
                raise

    def tap_button(self, name):
        if self.auto_focus_var.get():
            self.activate_game()
        try:
            pad = self.get_gamepad()
            pad.tap(name, hold=0.15)
            self._log(f"已按 {name.upper()}。")
        except Exception as exc:
            self.logger.exception("Manual tap failed")
            self._log(f"按键失败：{exc}")

    def _tick(self):
        try:
            while True:
                command = self.command_q.get_nowait()
                if command == "toggle":
                    self.toggle_run(source="hotkey")
        except queue.Empty:
            pass

        try:
            while True:
                self._append(self.log_q.get_nowait())
        except queue.Empty:
            pass
        running = self.runner.is_running()
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.root.after(100, self._tick)

    def _num(self, var, default):
        try:
            return float(var.get())
        except ValueError:
            return default

    def on_start(self):
        self.start_run(source="button")

    def start_run(self, source="button"):
        startup = self._num(self.startup_var, config.STARTUP_DELAY)
        drive = self._num(self.drive_var, config.DRIVE_SECONDS)
        minutes = self._num(self.total_var, config.TOTAL_MINUTES)
        total = None if minutes <= 0 else minutes * 60
        self.logger.info(
            "Start requested source=%s startup=%.2f drive=%.2f minutes=%.2f keep_active=%s auto_focus=%s require_foreground=%s resume=%s no_activate=%s",
            source,
            startup,
            drive,
            minutes,
            self.keep_var.get(),
            self.auto_focus_var.get(),
            self.require_foreground_var.get(),
            self.resume_var.get(),
            self.no_activate_var.get(),
        )
        if self.auto_focus_var.get():
            self.activate_game()
        if self.keep_var.get():
            self.keeper = focus.KeepActive(title_substr=config.GAME_TITLE, on_log=self._log)
            self.keeper.start()
        self.runner.start(farm_sequence(drive_seconds=drive),
                          startup_delay=startup,
                          total_seconds=total,
                          resume_button="a" if self.resume_var.get() else None,
                          require_foreground=self.require_foreground_var.get(),
                          foreground_check=lambda: focus.is_foreground(config.GAME_TITLE),
                          on_focus_lost=self._on_focus_lost,
                          on_focus_restored=self._on_focus_restored)

    def on_stop(self, source="button"):
        self.logger.info("Stop requested source=%s", source)
        self.runner.stop()
        if self.keeper:
            self.keeper.stop()
            self.keeper = None

    def toggle_run(self, source="hotkey"):
        if self.runner.is_running():
            self.on_stop(source=source)
        else:
            self.start_run(source=source)

    def activate_game(self):
        return focus.activate_window(
            title_substr=config.GAME_TITLE,
            on_log=self._log,
            logger=self.logger,
        )

    def _on_focus_lost(self):
        if self.auto_focus_var.get():
            focus.activate_window(
                title_substr=config.GAME_TITLE,
                on_log=self._log,
                logger=self.logger,
            )

    def _on_focus_restored(self):
        # Leave menu recovery to the user or the explicit checkbox.
        pass

    def apply_game_mode(self):
        try:
            self.root.update_idletasks()
            ok = focus.set_no_activate(
                self.root.winfo_id(),
                enabled=self.no_activate_var.get(),
                topmost=self.no_activate_var.get(),
                logger=self.logger,
            )
        except Exception as exc:
            self._log(f"游戏模式设置失败：{exc}")
            return False

        if ok:
            state = "开启" if self.no_activate_var.get() else "关闭"
            self._log(f"游戏模式已{state}。")
        return ok

    def open_log(self):
        try:
            LOG_PATH.touch(exist_ok=True)
            os.startfile(LOG_PATH)
            self.logger.info("Opened log file")
        except Exception as exc:
            self._log(f"无法打开日志文件：{exc}")

    def on_close(self):
        self.logger.info("Window closing")
        self.hotkey.stop()
        self.runner.stop()
        if self.pad:
            self.pad.neutral()
        if self.keeper:
            self.keeper.stop()
        self.root.after(200, self.root.destroy)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
