"""Tk GUI for the FH6 helper. Package to .exe with build.bat on Windows."""
import os
import queue
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from app_controller import AppController
from app_logging import LOG_PATH, log_startup_diagnostics, setup_logging
import config
import focus
from hotkeys import GlobalHotkey
from modes import DEFAULT_MODE_ID, MODE_SKILL_POINTS, debug_modes, get_mode, product_modes
from settings import RuntimeSettings
from single_instance import SingleInstance


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

        self.controller = AppController(on_log=self._log, logger=self.logger)
        self.hotkey = GlobalHotkey(on_press=self._enqueue_toggle, on_log=self._log)

        self.startup_var = tk.StringVar(value=str(config.STARTUP_DELAY))
        self.drive_var = tk.StringVar(value=str(config.DRIVE_SECONDS))
        self.total_var = tk.StringVar(value=str(config.TOTAL_MINUTES))
        self.keep_var = tk.BooleanVar(value=False)
        self.auto_focus_var = tk.BooleanVar(value=True)
        self.no_activate_var = tk.BooleanVar(value=True)
        self.require_foreground_var = tk.BooleanVar(value=True)
        self.resume_var = tk.BooleanVar(value=False)
        self.mode_var = tk.StringVar(value=DEFAULT_MODE_ID)
        self.show_debug_var = tk.BooleanVar(value=False)
        self.hint_var = tk.StringVar()

        frm = ttk.Frame(root, padding=12)
        frm.grid(row=0, column=0)

        mode_box = ttk.LabelFrame(frm, text="运行模式", padding=6)
        mode_box.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 6))
        for row, mode in enumerate(product_modes()):
            self._add_mode_button(mode_box, mode, row)

        debug_row = len(product_modes())
        ttk.Checkbutton(
            mode_box,
            text="显示高级/调试模式",
            variable=self.show_debug_var,
            command=self.refresh_debug_visibility,
        ).grid(row=debug_row, column=0, sticky="w", pady=(4, 0))

        self.debug_mode_frame = ttk.Frame(mode_box)
        self.debug_mode_frame.grid(row=debug_row + 1, column=0, sticky="we")
        for row, mode in enumerate(debug_modes()):
            self._add_mode_button(self.debug_mode_frame, mode, row)

        r = 1
        ttk.Label(frm, text="启动倒计时（秒）").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.startup_var, width=10).grid(row=r, column=1, pady=3)
        r += 1

        self.drive_label = ttk.Label(frm, text="每圈前进时间（秒）")
        self.drive_entry = ttk.Entry(frm, textvariable=self.drive_var, width=10)
        self.drive_label.grid(row=r, column=0, sticky="w", pady=3)
        self.drive_entry.grid(row=r, column=1, pady=3)
        r += 1

        ttk.Label(frm, text="总运行时间（分钟，0=一直跑）").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=self.total_var, width=10).grid(row=r, column=1, pady=3)
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

        self.debug_buttons_frame = ttk.Frame(frm)
        self.debug_buttons_frame.grid(row=r, column=0, columnspan=2, pady=(2, 4))
        r += 1
        self.confirm_btn = ttk.Button(
            self.debug_buttons_frame,
            text="按A确认",
            command=lambda: self.tap_button("a"),
        )
        self.confirm_btn.grid(row=0, column=0, padx=4)
        self.back_btn = ttk.Button(
            self.debug_buttons_frame,
            text="按B返回",
            command=lambda: self.tap_button("b"),
        )
        self.back_btn.grid(row=0, column=1, padx=4)
        self.detect_btn = ttk.Button(self.debug_buttons_frame, text="识别一次", command=self.detect_once)
        self.detect_btn.grid(row=0, column=2, padx=4)

        self.advanced_frame = ttk.Frame(frm)
        self.advanced_frame.grid(row=r, column=0, columnspan=2, sticky="we")
        r += 1
        ttk.Label(
            self.advanced_frame,
            text="高级（切换模式会自动设置，可手动覆盖）",
            foreground="#888",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Checkbutton(
            self.advanced_frame,
            text="游戏模式：点击本窗口不抢焦点",
            variable=self.no_activate_var,
            command=self.apply_game_mode,
        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            self.advanced_frame,
            text="开始后自动切回游戏窗口",
            variable=self.auto_focus_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            self.advanced_frame,
            text="只在游戏前台时计时（失焦自动暂停脚本）",
            variable=self.require_foreground_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            self.advanced_frame,
            text="切回后按 A 确认/恢复控制器",
            variable=self.resume_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(
            self.advanced_frame,
            text="失焦时尝试保持运行（实验性；建议先用无边框窗口）",
            variable=self.keep_var,
        ).grid(row=5, column=0, columnspan=2, sticky="w")

        ttk.Label(
            frm,
            textvariable=self.hint_var,
            foreground="#666",
            wraplength=420,
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(2, 0))
        r += 1

        self.log = scrolledtext.ScrolledText(frm, width=56, height=12, state="disabled")
        self.log.grid(row=r, column=0, columnspan=2, pady=(8, 0))
        self._log(f"日志文件：{LOG_PATH}")
        self.hotkey.start()
        self.refresh_debug_visibility()
        self.root.after(300, self.apply_mode)
        self.root.after(500, self.connect_gamepad_async)
        self.root.after(100, self._tick)

    def _add_mode_button(self, parent, mode, row):
        ttk.Radiobutton(
            parent,
            text=mode.label,
            variable=self.mode_var,
            value=mode.mode_id,
            command=self.apply_mode,
        ).grid(row=row, column=0, sticky="w")

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
        self.controller.connect_gamepad_async()

    def tap_button(self, name):
        self.controller.tap_button(name, auto_focus=self.auto_focus_var.get())

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

        running = self.is_running()
        self.start_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        self.root.after(100, self._tick)

    def is_running(self):
        return self.controller.is_running()

    def _num(self, var, default):
        try:
            return float(var.get())
        except ValueError:
            return default

    def _settings_from_ui(self, source):
        return RuntimeSettings(
            mode_id=self.mode_var.get(),
            startup_delay=self._num(self.startup_var, config.STARTUP_DELAY),
            drive_seconds=self._num(self.drive_var, config.DRIVE_SECONDS),
            total_minutes=self._num(self.total_var, config.TOTAL_MINUTES),
            keep_active=self.keep_var.get(),
            auto_focus=self.auto_focus_var.get(),
            no_activate=self.no_activate_var.get(),
            require_foreground=self.require_foreground_var.get(),
            resume_after_focus=self.resume_var.get(),
            source=source,
        )

    def on_start(self):
        self.start_run(source="button")

    def start_run(self, source="button"):
        self.controller.start(self._settings_from_ui(source))

    def on_stop(self, source="button"):
        self.controller.stop(source=source)

    def toggle_run(self, source="hotkey"):
        if self.is_running():
            self.on_stop(source=source)
        else:
            self.start_run(source=source)

    def activate_game(self):
        return self.controller.activate_game()

    def apply_mode(self):
        mode = get_mode(self.mode_var.get())
        defaults = mode.defaults
        self.no_activate_var.set(defaults.no_activate)
        self.auto_focus_var.set(defaults.auto_focus)
        self.require_foreground_var.set(defaults.require_foreground)
        self.keep_var.set(defaults.keep_active)
        self.resume_var.set(defaults.resume_after_focus)
        if mode.mode_id == MODE_SKILL_POINTS and self.total_var.get().strip() == "10.0":
            self.total_var.set("0.0")
        self.hint_var.set(mode.hint)
        self._log(mode.log_message)
        self.refresh_field_visibility()
        self.apply_game_mode()

    def refresh_debug_visibility(self):
        show = self.show_debug_var.get()
        selected_mode = get_mode(self.mode_var.get())
        if not show and not selected_mode.product_visible:
            self.mode_var.set(DEFAULT_MODE_ID)
            self.apply_mode()
            return

        if show:
            self.debug_mode_frame.grid()
            self.debug_buttons_frame.grid()
            self.advanced_frame.grid()
        else:
            self.debug_mode_frame.grid_remove()
            self.debug_buttons_frame.grid_remove()
            self.advanced_frame.grid_remove()
        self.refresh_field_visibility()

    def refresh_field_visibility(self):
        mode = get_mode(self.mode_var.get())
        if mode.uses_drive_seconds or self.show_debug_var.get():
            self.drive_label.grid()
            self.drive_entry.grid()
        else:
            self.drive_label.grid_remove()
            self.drive_entry.grid_remove()

    def detect_once(self):
        if self.auto_focus_var.get():
            self.activate_game()
        try:
            detection = self.controller.detect_once(self.mode_var.get())
        except Exception as exc:
            self.logger.exception("Manual detection failed")
            self._log(f"识别失败：{exc}")
            return
        scores = ", ".join(f"{k}={v:.3f}" for k, v in detection.scores.items())
        self._log(f"识别一次：{detection.state} conf={detection.confidence:.2f}；{scores}")
        if getattr(detection, "ocr_text", ""):
            self._log(f"OCR：{detection.ocr_text[:180]}")
        self.logger.info(
            "Manual detection state=%s confidence=%.3f scores=%s",
            detection.state,
            detection.confidence,
            scores,
        )

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
        self.controller.close()
        self.root.after(200, self.root.destroy)


def main():
    instance = SingleInstance()
    if not instance.acquired:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("地平线6 刷分助手", "助手已经在运行。请先关闭旧窗口，避免创建多个虚拟手柄。")
        root.destroy()
        return
    root = tk.Tk()
    root._single_instance = instance
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
