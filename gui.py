"""Simple GUI for the FH6 skill-point farm. Package to .exe with build.bat (on Windows)."""
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext

import config
import focus
from runner import Runner
from sequences import farm_sequence


class App:
    def __init__(self, root):
        self.root = root
        root.title("地平线6 刷分助手")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.log_q = queue.Queue()
        self.runner = Runner(on_log=self.log_q.put)
        self.keeper = None

        self.startup_var = tk.StringVar(value=str(config.STARTUP_DELAY))
        self.drive_var = tk.StringVar(value=str(config.DRIVE_SECONDS))
        self.total_var = tk.StringVar(value=str(config.TOTAL_MINUTES))
        self.keep_var = tk.BooleanVar(value=False)

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

        ttk.Checkbutton(frm, text="失焦时尝试保持运行（实验性；建议先用无边框窗口）",
                        variable=self.keep_var).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        ttk.Label(frm, text="开始后请在倒计时内切到地平线。每圈：油门前进 → X重开 → A确认 → A开始。",
                  foreground="#666", wraplength=320).grid(row=r, column=0, columnspan=2, sticky="w")
        r += 1

        self.log = scrolledtext.ScrolledText(frm, width=46, height=12, state="disabled")
        self.log.grid(row=r, column=0, columnspan=2, pady=(8, 0))

        self.root.after(100, self._tick)

    def _append(self, msg):
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _tick(self):
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
        startup = self._num(self.startup_var, config.STARTUP_DELAY)
        drive = self._num(self.drive_var, config.DRIVE_SECONDS)
        minutes = self._num(self.total_var, config.TOTAL_MINUTES)
        total = None if minutes <= 0 else minutes * 60
        if self.keep_var.get():
            self.keeper = focus.KeepActive(title_substr=config.GAME_TITLE, on_log=self.log_q.put)
            self.keeper.start()
        self.runner.start(farm_sequence(drive_seconds=drive),
                          startup_delay=startup, total_seconds=total)

    def on_stop(self):
        self.runner.stop()
        if self.keeper:
            self.keeper.stop()
            self.keeper = None

    def on_close(self):
        self.runner.stop()
        if self.keeper:
            self.keeper.stop()
        self.root.after(200, self.root.destroy)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
