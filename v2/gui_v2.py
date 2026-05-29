"""Standalone V2 page-understanding test GUI.

This GUI never sends controller input.  It captures the Forza window, runs OCR,
and displays the semantic page model plus non-executed action recommendations.
"""
from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import focus
from ocr_engine import OcrReader
from window_capture import capture_client, capture_client_printwindow
from v2.semantic import ForzaSemanticAnalyzer


class V2RecognizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("地平线6 V2 页面理解测试版")
        self.root.geometry("1280x760")
        self.root.minsize(1120, 660)
        self.logger = logging.getLogger("forza6helper.v2")
        self.ocr = OcrReader(logger=self.logger)
        self.analyzer = ForzaSemanticAnalyzer()
        self.live = False
        self.busy = False
        self.last_frame = None
        self.last_understanding = None
        self.preview_photo = None

        self.title_var = tk.StringVar(value="Forza")
        self.min_conf_var = tk.DoubleVar(value=0.42)
        self.interval_var = tk.DoubleVar(value=1.2)
        self.status_var = tk.StringVar(value="V2 只识别页面，不会按任何键。")
        self.screen_var = tk.StringVar(value="页面: 未识别")
        self.action_var = tk.StringVar(value="动作建议: -")

        self._build_style()
        self._build_ui()

    def _build_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Root.TFrame", background="#073f36")
        style.configure("Panel.TFrame", background="#f4faf6", relief="flat")
        style.configure("Title.TLabel", background="#073f36", foreground="#f7fff9", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Sub.TLabel", background="#073f36", foreground="#bfe6d6", font=("Microsoft YaHei UI", 9))
        style.configure("PanelTitle.TLabel", background="#f4faf6", foreground="#082f2a", font=("Microsoft YaHei UI", 11, "bold"))
        style.configure("Panel.TLabel", background="#f4faf6", foreground="#163c36", font=("Microsoft YaHei UI", 9))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_ui(self):
        root = ttk.Frame(self.root, style="Root.TFrame", padding=14)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="Root.TFrame")
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="地平线6 V2 页面理解测试版", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="截图归一化 / OCR 布局理解 / 每步动作建议与验证条件（测试版不发送输入）",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(root, style="Root.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="Panel.TFrame", padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        controls = ttk.Frame(left, style="Panel.TFrame")
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(9, weight=1)
        ttk.Label(controls, text="窗口标题", style="Panel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.title_var, width=14).grid(row=0, column=1, padx=(6, 12))
        ttk.Label(controls, text="OCR阈值", style="Panel.TLabel").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(controls, from_=0.10, to=0.90, increment=0.02, textvariable=self.min_conf_var, width=6).grid(row=0, column=3, padx=(6, 12))
        ttk.Label(controls, text="间隔", style="Panel.TLabel").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(controls, from_=0.5, to=5.0, increment=0.1, textvariable=self.interval_var, width=6).grid(row=0, column=5, padx=(6, 12))

        button_bar = ttk.Frame(controls, style="Panel.TFrame")
        button_bar.grid(row=1, column=0, columnspan=10, sticky="w", pady=(10, 0))
        ttk.Button(button_bar, text="识别一次", style="Accent.TButton", command=self.capture_once).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="开始实时", command=self.start_live).pack(side="left", padx=(0, 8))
        ttk.Button(button_bar, text="停止", command=self.stop_live).pack(side="left")

        summary = ttk.Frame(left, style="Panel.TFrame")
        summary.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        summary.columnconfigure(0, weight=1)
        ttk.Label(summary, textvariable=self.screen_var, style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.action_var, style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.canvas = tk.Canvas(left, bg="#092e2a", highlightthickness=0)
        self.canvas.grid(row=2, column=0, sticky="nsew")

        right = ttk.Frame(body, style="Panel.TFrame", padding=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)
        top_right = ttk.Frame(right, style="Panel.TFrame")
        top_right.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top_right.columnconfigure(0, weight=1)
        ttk.Label(top_right, text="页面语义模型", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(top_right, text="复制结果", command=self.copy_result).grid(row=0, column=1, sticky="e")

        self.text = tk.Text(
            right,
            wrap="word",
            bg="#072c27",
            fg="#e9fff4",
            insertbackground="#e9fff4",
            relief="flat",
            font=("Consolas", 10),
            padx=10,
            pady=10,
        )
        self.text.grid(row=1, column=0, sticky="nsew")
        self.text.insert("1.0", "点击“识别一次”开始。\n")

        ttk.Label(root, textvariable=self.status_var, style="Sub.TLabel").pack(fill="x", pady=(10, 0))

    def start_live(self):
        self.live = True
        self.status_var.set("实时识别已开启。V2 不会按键。")
        self._schedule_live(0)

    def stop_live(self):
        self.live = False
        self.status_var.set("实时识别已停止。")

    def capture_once(self):
        self._run_capture_async()

    def _schedule_live(self, delay_ms=None):
        if not self.live:
            return
        if delay_ms is None:
            delay_ms = int(max(0.5, float(self.interval_var.get() or 1.2)) * 1000)
        self.root.after(delay_ms, self._live_tick)

    def _live_tick(self):
        if not self.live:
            return
        self._run_capture_async()
        self._schedule_live()

    def _run_capture_async(self):
        if self.busy:
            return
        self.busy = True
        self.status_var.set("正在截图和 OCR...")
        thread = threading.Thread(target=self._capture_worker, daemon=True)
        thread.start()

    def _capture_worker(self):
        started = time.monotonic()
        try:
            title = self.title_var.get().strip() or "Forza"
            hwnd = focus.find_window(title)
            if not hwnd:
                raise RuntimeError(f"没找到标题包含“{title}”的窗口")
            try:
                frame = capture_client_printwindow(hwnd)
            except Exception:
                frame = capture_client(hwnd)
            items = self.ocr.read_frame(frame, min_confidence=float(self.min_conf_var.get() or 0.42))
            understanding = self.analyzer.analyze(frame, items)
            elapsed = time.monotonic() - started
            self.root.after(0, lambda: self._update_result(frame, items, understanding, elapsed, None))
        except Exception as exc:
            self.root.after(0, lambda: self._update_result(None, [], None, 0.0, exc))

    def _update_result(self, frame, items, understanding, elapsed, error):
        self.busy = False
        if error:
            self.status_var.set(f"识别失败：{error}")
            return
        self.last_frame = frame
        self.last_understanding = understanding
        first_action = understanding.actions[0] if understanding.actions else None
        self.screen_var.set(
            f"页面: {understanding.screen}  分页: {understanding.active_tab or '未知'}  "
            f"置信度: {understanding.confidence:.2f}"
        )
        self.action_var.set(
            f"动作建议: {(first_action.button or '不按键') if first_action else '-'}"
            f" / {(first_action.name if first_action else '-')}"
        )
        self.text.delete("1.0", "end")
        self.text.insert("1.0", understanding.as_text())
        self._draw_preview(frame, items, understanding)
        self.status_var.set(
            f"完成：{len(items)} 个 OCR 条目，耗时 {elapsed:.2f}s。V2 没有发送任何输入。"
        )

    def _draw_preview(self, frame, items, understanding):
        try:
            import numpy as np
            from PIL import Image, ImageDraw, ImageTk
        except Exception as exc:
            self.canvas.delete("all")
            self.canvas.create_text(20, 20, anchor="nw", fill="#e9fff4", text=f"预览不可用：{exc}")
            return

        arr = np.frombuffer(frame.bgra, dtype=np.uint8).reshape((frame.height, frame.width, 4))
        rgba = arr[:, :, [2, 1, 0, 3]]
        image = Image.fromarray(rgba, "RGBA")
        canvas_w = max(320, self.canvas.winfo_width())
        canvas_h = max(200, self.canvas.winfo_height())
        scale = min(canvas_w / image.width, canvas_h / image.height)
        preview_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(preview_size)
        draw = ImageDraw.Draw(image)

        left, top, right, bottom = understanding.content_region
        draw.rectangle(
            [left * preview_size[0], top * preview_size[1], right * preview_size[0], bottom * preview_size[1]],
            outline="#00e0aa",
            width=2,
        )
        for item in items[:90]:
            x1 = getattr(item, "nx1", 0.0) * preview_size[0]
            y1 = getattr(item, "ny1", 0.0) * preview_size[1]
            x2 = getattr(item, "nx2", 0.0) * preview_size[0]
            y2 = getattr(item, "ny2", 0.0) * preview_size[1]
            draw.rectangle([x1, y1, x2, y2], outline="#f7ff00", width=1)
        for tab in understanding.visible_tabs:
            x = tab.x * preview_size[0]
            y = tab.y * preview_size[1]
            color = "#00ff66" if tab.label == understanding.active_tab else "#ffffff"
            draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=color)

        self.preview_photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        x = (canvas_w - preview_size[0]) // 2
        y = (canvas_h - preview_size[1]) // 2
        self.canvas.create_image(x, y, anchor="nw", image=self.preview_photo)

    def copy_result(self):
        if not self.last_understanding:
            messagebox.showinfo("V2 页面理解", "还没有识别结果。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_understanding.as_text())
        self.status_var.set("识别结果已复制到剪贴板。")


def main():
    logging.basicConfig(level=logging.INFO)
    root = tk.Tk()
    V2RecognizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
