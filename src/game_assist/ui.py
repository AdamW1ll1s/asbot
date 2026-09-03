from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import base64
import shutil
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
import numpy as np

from .config import AppConfig, load_config, save_config
from .hotkeys import GlobalHotkeys, HotkeyRegistrationError
from .runner import AutomationRunner
from .windows import WindowsOnlyError, activate_window, find_window, list_visible_windows


class GameAssistApp:
    """A small Windows control panel around the safe automation runner."""

    BACKGROUND = "#0b1220"
    PANEL = "#152238"
    PANEL_ALT = "#1b2b45"
    TEXT = "#edf4ff"
    MUTED = "#9eafc7"
    ACCENT = "#39d9a9"
    DANGER = "#ff6b7a"

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            example = self.config_path.with_name("profile.example.yaml")
            if not example.exists():
                raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(example, self.config_path)
        self.config = load_config(self.config_path)
        self.runner = AutomationRunner(self.config)
        self.hotkeys = GlobalHotkeys(
            {
                self.config.toggle_hotkey: lambda: self.runner.toggle(),
                self.config.emergency_stop_hotkey: self.runner.stop,
            }
        )
        self.root = tk.Tk()
        self.root.title("Game Assist · 控制台")
        self.root.geometry("860x650")
        self.root.minsize(760, 560)
        self.root.configure(bg=self.BACKGROUND)
        self._configure_style()

        self.window_title = tk.StringVar(value=self.config.window.title_contains)
        self.process_id: int | None = self.config.window.process_id
        self.threshold = tk.StringVar(value=str(self.config.rules.heal_below_percent))
        self.heal_key = tk.StringVar(value=self.config.rules.heal_key)
        self.recognition_interval = tk.StringVar(value=str(self.config.recognition_interval_ms))
        self.save_debug = tk.BooleanVar(value=self.config.save_debug_frame)
        self.status = tk.StringVar(value="待命 · 请先选择目标窗口")
        self.window_count = tk.StringVar(value="尚未刷新")
        self.preview_window: tk.Toplevel | None = None
        self.preview_canvas: tk.Canvas | None = None
        self.preview_photo: tk.PhotoImage | None = None
        self.preview_scale = 1.0
        self.preview_zoom = 1.0
        self.preview_rendered_revision = -1
        self.preview_mode = tk.StringVar(value="roi")
        self.preview_zoom_text = tk.StringVar(value="缩放：适应窗口")
        self.preview_help = tk.StringVar(value="先选择“框选识别区域”，拖拽覆盖完整血条。")
        self.preview_reading = tk.StringVar(value="等待首次识别")
        self.preview_start: tuple[int, int] | None = None
        self.preview_rect: int | None = None
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BACKGROUND)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.PANEL, foreground=self.MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=self.BACKGROUND, foreground=self.TEXT, font=("Segoe UI Semibold", 22))
        style.configure("Subtitle.TLabel", background=self.BACKGROUND, foreground=self.MUTED, font=("Segoe UI", 10))
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#06130f", font=("Segoe UI Semibold", 10), padding=(16, 9))
        style.map("Accent.TButton", background=[("active", "#60e9bf")])
        style.configure("Danger.TButton", background="#442333", foreground=self.TEXT, font=("Segoe UI Semibold", 10), padding=(16, 9))
        style.map("Danger.TButton", background=[("active", "#623246")])
        style.configure("Secondary.TButton", background=self.PANEL_ALT, foreground=self.TEXT, font=("Segoe UI", 10), padding=(12, 7))
        style.map("Secondary.TButton", background=[("active", "#29405f")])
        style.configure("Treeview", background=self.PANEL_ALT, fieldbackground=self.PANEL_ALT, foreground=self.TEXT, rowheight=28, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=self.PANEL, foreground=self.MUTED, relief="flat", font=("Segoe UI Semibold", 9))
        style.map("Treeview", background=[("selected", "#28566a")])
        style.configure("TEntry", fieldbackground="#0d1929", foreground=self.TEXT, insertcolor=self.TEXT, padding=7)
        style.configure("TCheckbutton", background=self.PANEL, foreground=self.TEXT, font=("Segoe UI", 10))
        style.configure("Mode.TRadiobutton", background=self.BACKGROUND, foreground=self.TEXT, font=("Segoe UI", 10))
        style.map("Mode.TRadiobutton", background=[("active", self.BACKGROUND)], foreground=[("active", self.ACCENT)])

    def _build(self) -> None:
        shell = ttk.Frame(self.root, padding=26)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Game Assist", style="Title.TLabel").pack(anchor="w")
        ttk.Label(shell, text="选择可见窗口，确认安全配置后再启动自动化。", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 22))

        status_card = ttk.Frame(shell, style="Panel.TFrame", padding=(18, 13))
        status_card.pack(fill="x", pady=(0, 15))
        ttk.Label(status_card, textvariable=self.status, font=("Segoe UI Semibold", 11)).pack(side="left")
        ttk.Label(status_card, text=f"F8 启停  ·  {self.config.emergency_stop_hotkey} 紧急停止", style="Muted.TLabel").pack(side="right")

        picker = ttk.Frame(shell, style="Panel.TFrame", padding=18)
        picker.pack(fill="both", expand=True)
        picker.columnconfigure(0, weight=1)
        picker.rowconfigure(2, weight=1)
        ttk.Label(picker, text="目标窗口", font=("Segoe UI Semibold", 13)).grid(row=0, column=0, sticky="w")
        ttk.Label(picker, textvariable=self.window_count, style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(12, 0))
        tools = ttk.Frame(picker, style="Panel.TFrame")
        tools.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 10))
        ttk.Button(tools, text="刷新窗口列表", style="Secondary.TButton", command=self.refresh_windows).pack(side="left")
        ttk.Label(tools, text="选择一项后会填入下方的窗口标题。", style="Muted.TLabel").pack(side="left", padx=12)
        self.window_tree = ttk.Treeview(picker, columns=("pid", "title"), show="headings", selectmode="browse", height=9)
        self.window_tree.heading("pid", text="PID")
        self.window_tree.heading("title", text="窗口标题")
        self.window_tree.column("pid", width=100, stretch=False, anchor="center")
        self.window_tree.column("title", width=620, stretch=True)
        self.window_tree.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.window_tree.bind("<<TreeviewSelect>>", self._select_window)

        settings = ttk.Frame(shell, style="Panel.TFrame", padding=18)
        settings.pack(fill="x", pady=(15, 0))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="运行设置", font=("Segoe UI Semibold", 13)).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        ttk.Label(settings, text="窗口标题", style="Muted.TLabel").grid(row=1, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.window_title).grid(row=1, column=1, sticky="ew", padx=(8, 18))
        ttk.Label(settings, text="治疗阈值 (%)", style="Muted.TLabel").grid(row=1, column=2, sticky="w")
        ttk.Entry(settings, textvariable=self.threshold, width=7).grid(row=1, column=3, sticky="w", padx=(8, 0))
        ttk.Label(settings, text="治疗按键", style="Muted.TLabel").grid(row=2, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(settings, textvariable=self.heal_key, width=8).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(12, 0))
        ttk.Label(settings, text="判断间隔 (ms)", style="Muted.TLabel").grid(row=2, column=2, sticky="w", pady=(12, 0))
        ttk.Entry(settings, textvariable=self.recognition_interval, width=7).grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(12, 0))
        ttk.Checkbutton(settings, text="保存调试截图", variable=self.save_debug).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 0))

        actions = ttk.Frame(shell)
        actions.pack(fill="x", pady=(18, 0))
        ttk.Button(actions, text="保存配置", style="Secondary.TButton", command=self.save_settings).pack(side="left")
        ttk.Button(actions, text="实时识别预览", style="Secondary.TButton", command=self.show_preview).pack(side="left", padx=(10, 0))
        ttk.Button(actions, text="停止", style="Danger.TButton", command=self._stop).pack(side="right")
        self.start_button = ttk.Button(actions, text="开始自动化", style="Accent.TButton", command=self._start)
        self.start_button.pack(side="right", padx=(0, 10))

    def refresh_windows(self) -> None:
        for item in self.window_tree.get_children():
            self.window_tree.delete(item)
        windows = list_visible_windows()
        for window in windows:
            self.window_tree.insert("", "end", values=(window.process_id, window.title))
        self.window_count.set(f"找到 {len(windows)} 个可见窗口")

    def _select_window(self, _: object) -> None:
        selected = self.window_tree.selection()
        if selected:
            values = self.window_tree.item(selected[0], "values")
            self.process_id = int(values[0])
            self.window_title.set(str(values[1]))

    def _updated_config(self) -> AppConfig:
        title = self.window_title.get().strip()
        if not title:
            raise ValueError("请先从列表选择目标窗口，或输入窗口标题")
        threshold = float(self.threshold.get())
        if not 0 <= threshold <= 100:
            raise ValueError("治疗阈值必须在 0 到 100 之间")
        key = self.heal_key.get().strip().upper()
        if not key:
            raise ValueError("请填写治疗按键")
        recognition_interval = int(self.recognition_interval.get())
        if recognition_interval < 50:
            raise ValueError("判断间隔不能小于 50 毫秒")
        return replace(
            self.config,
            window=replace(self.config.window, title_contains=title, process_id=self.process_id),
            recognition_interval_ms=recognition_interval,
            save_debug_frame=self.save_debug.get(),
            rules=replace(self.config.rules, heal_below_percent=threshold, heal_key=key),
        )

    def save_settings(self) -> bool:
        try:
            self.config = self._updated_config()
            save_config(self.config_path, self.config)
        except (OSError, ValueError) as error:
            messagebox.showerror("无法保存配置", str(error), parent=self.root)
            return False
        self.status.set(f"配置已保存 · {self.config_path}")
        return True

    def _start(self) -> None:
        if not self.save_settings():
            return
        if self.runner.running and not self.runner.preview_only:
            return
        if self.runner.running:
            self.runner.stop()
        hwnd = find_window(self.config.window.title_contains, self.config.window.process_id)
        if hwnd is None:
            messagebox.showerror("无法启动", "找不到已选择的目标窗口，请刷新窗口列表后重新选择。", parent=self.root)
            return
        activated = not self.config.window.require_foreground or activate_window(hwnd)
        self.runner = AutomationRunner(self.config)
        self.runner.start()
        if activated:
            self.status.set("运行中 · 失焦时暂停，目标窗口回到前台后自动继续")
        else:
            self.status.set("已暂停 · 请手动将目标窗口切回前台")

    def _stop(self) -> None:
        self.runner.stop()
        self.status.set("已停止 · 所有已按下按键已释放")
        self.start_button.configure(text="开始自动化")

    def _refresh_status(self) -> None:
        if self.runner.running:
            if self.runner.preview_only:
                self.start_button.configure(text="开始自动化")
                if self.runner.last_reading:
                    hp, confidence = self.runner.last_reading
                    self.preview_reading.set(f"HP {hp:.1f}% · 置信度 {confidence:.2f}")
            else:
                self.start_button.configure(text="运行中")
            if not self.runner.preview_only and self.runner.paused_for_focus:
                self.status.set("已暂停 · 请将目标窗口切回前台，程序会自动继续")
            elif not self.runner.preview_only and self.runner.last_reading:
                hp, confidence = self.runner.last_reading
                self.status.set(f"运行中 · HP {hp:.1f}% · 置信度 {confidence:.2f} · {self.runner.last_event}")
        else:
            self.start_button.configure(text="开始自动化")
        self._refresh_preview()
        self.root.after(250, self._refresh_status)

    def show_preview(self) -> None:
        if self.preview_window is not None and self.preview_window.winfo_exists():
            self.preview_window.deiconify()
            self.preview_window.lift()
            return
        try:
            self.config = self._updated_config()
        except ValueError as error:
            messagebox.showerror("无法开始预览", str(error), parent=self.root)
            return
        # Calibration is intentionally capture-only: the preview window may take focus,
        # so it must never emit input into the wrong foreground application.
        if self.runner.running:
            self.runner.stop()
        self.runner = AutomationRunner(self.config, preview_only=True)
        self.runner.start()
        self.status.set("校准预览中 · 不会发送任何按键")
        self.preview_zoom = 1.0
        self.preview_rendered_revision = -1
        self.preview_mode.set("roi")
        self.preview_zoom_text.set("缩放：适应窗口")
        self.preview_help.set("左键框选完整血条；滚轮缩放；按住右键拖拽移动画面。")
        self.preview_reading.set("等待首次识别")
        window = tk.Toplevel(self.root)
        window.title("Game Assist · 实时识别预览")
        window.configure(bg=self.BACKGROUND)
        window.geometry("960x700")
        window.minsize(720, 520)
        ttk.Label(window, textvariable=self.preview_help, style="Subtitle.TLabel").pack(anchor="w", padx=16, pady=(14, 8))
        toolbar = ttk.Frame(window)
        toolbar.pack(fill="x", padx=16, pady=(0, 8))
        ttk.Radiobutton(toolbar, text="框选识别区域", variable=self.preview_mode, value="roi", style="Mode.TRadiobutton").pack(side="left")
        ttk.Radiobutton(toolbar, text="吸取血条颜色", variable=self.preview_mode, value="color", style="Mode.TRadiobutton").pack(side="left", padx=(12, 0))
        ttk.Label(toolbar, textvariable=self.preview_reading, style="Subtitle.TLabel").pack(side="left", padx=(20, 0))
        ttk.Button(toolbar, text="适应窗口", style="Secondary.TButton", command=self._preview_fit).pack(side="right")
        ttk.Button(toolbar, text="放大 +", style="Secondary.TButton", command=lambda: self._preview_zoom_by(1.25)).pack(side="right", padx=(8, 0))
        ttk.Button(toolbar, text="缩小 −", style="Secondary.TButton", command=lambda: self._preview_zoom_by(0.8)).pack(side="right", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.preview_zoom_text, style="Subtitle.TLabel").pack(side="right", padx=(0, 10))
        canvas_frame = ttk.Frame(window)
        canvas_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(canvas_frame, bg="#07101c", highlightthickness=0, cursor="crosshair")
        horizontal = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.preview_canvas.xview)
        vertical = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.preview_canvas.yview)
        self.preview_canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.preview_canvas.bind("<ButtonPress-1>", self._preview_press)
        self.preview_canvas.bind("<B1-Motion>", self._preview_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._preview_release)
        self.preview_canvas.bind("<MouseWheel>", self._preview_mousewheel)
        self.preview_canvas.bind("<ButtonPress-3>", self._preview_pan_start)
        self.preview_canvas.bind("<B3-Motion>", self._preview_pan_drag)
        self.preview_canvas.bind("<ButtonRelease-3>", self._preview_pan_end)
        self.preview_window = window
        window.protocol("WM_DELETE_WINDOW", self._close_preview)

    def _close_preview(self) -> None:
        if self.preview_window is not None:
            self.preview_window.destroy()
        self.preview_window = None
        self.preview_canvas = None
        self.preview_photo = None
        self.preview_rendered_revision = -1
        self.preview_start = None
        self.preview_rect = None
        if self.runner.preview_only:
            self.runner.stop()
            self.status.set("校准预览已停止 · 保存配置后可开始自动化")

    def _refresh_preview(self, force: bool = False) -> bool:
        if self.preview_window is None or not self.preview_window.winfo_exists() or self.preview_canvas is None:
            return False
        snapshot = self.runner.preview_frame()
        if snapshot is None:
            return False
        revision, frame = snapshot
        if revision == self.preview_rendered_revision and not force:
            return False
        height, width = frame.shape[:2]
        canvas_width = self.preview_canvas.winfo_width()
        canvas_height = self.preview_canvas.winfo_height()
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width, canvas_height = 900, 570
        fit_scale = min(canvas_width / width, canvas_height / height, 1.0)
        scale = fit_scale * self.preview_zoom
        interpolation = cv2.INTER_NEAREST if scale > 1 else cv2.INTER_AREA
        image = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=interpolation)
        ok, encoded = cv2.imencode(".png", image)
        if ok:
            self.preview_photo = tk.PhotoImage(data=base64.b64encode(encoded.tobytes()))
            self.preview_rendered_revision = revision
            self.preview_scale = scale
            self.preview_zoom_text.set(f"缩放：{scale * 100:.0f}%")
            self.preview_canvas.delete("frame")
            self.preview_canvas.create_image(0, 0, image=self.preview_photo, anchor="nw", tags="frame")
            self.preview_canvas.tag_lower("frame")
            self.preview_canvas.configure(scrollregion=(0, 0, image.shape[1], image.shape[0]))
            return True
        return False

    def _preview_press(self, event: tk.Event) -> None:
        if self.preview_canvas is None:
            return
        x = int(self.preview_canvas.canvasx(event.x))
        y = int(self.preview_canvas.canvasy(event.y))
        self.preview_start = (x, y)
        if self.preview_mode.get() == "roi":
            self.preview_canvas.delete("selection")
            self.preview_rect = self.preview_canvas.create_rectangle(x, y, x, y, outline="#39d9a9", width=2, tags="selection")

    def _preview_drag(self, event: tk.Event) -> None:
        if self.preview_canvas and self.preview_start and self.preview_rect and self.preview_mode.get() == "roi":
            x = int(self.preview_canvas.canvasx(event.x))
            y = int(self.preview_canvas.canvasy(event.y))
            self.preview_canvas.coords(self.preview_rect, self.preview_start[0], self.preview_start[1], x, y)

    def _preview_release(self, event: tk.Event) -> None:
        if not self.preview_start:
            return
        start_x, start_y = self.preview_start
        if self.preview_canvas is None:
            return
        end_x = int(self.preview_canvas.canvasx(event.x))
        end_y = int(self.preview_canvas.canvasy(event.y))
        self.preview_start = None
        raw = self.runner.raw_preview_frame()
        if raw is None:
            return
        if self.preview_mode.get() == "color":
            self._pick_preview_color(raw, end_x, end_y)
            return
        x1, x2 = sorted((int(start_x / self.preview_scale), int(end_x / self.preview_scale)))
        y1, y2 = sorted((int(start_y / self.preview_scale), int(end_y / self.preview_scale)))
        x1, x2 = max(0, x1), min(raw.shape[1], x2)
        y1, y2 = max(0, y1), min(raw.shape[0], y2)
        if x2 - x1 < 4 or y2 - y1 < 4:
            self.preview_help.set("框选区域太小，请拖拽覆盖完整血条（包括空血部分）。")
            return
        roi = (x1, y1, x2 - x1, y2 - y1)
        self.config = replace(self.config, health_bar=replace(self.config.health_bar, roi=roi))
        self.runner.update_health_bar(self.config.health_bar)
        self.preview_mode.set("color")
        self.preview_help.set(f"识别区域 {roi} 已设置。现在请单击血条中有颜色的填充部分。")
        self.status.set(f"已框选 ROI {roi}；点击“保存配置”生效")

    def _pick_preview_color(self, raw: np.ndarray, display_x: int, display_y: int) -> None:
        x = int(display_x / self.preview_scale)
        y = int(display_y / self.preview_scale)
        if not 0 <= x < raw.shape[1] or not 0 <= y < raw.shape[0]:
            self.preview_help.set("取色点不在图像内，请单击血条的有色填充部分。")
            return
        radius = 2
        patch = raw[max(0, y - radius) : min(raw.shape[0], y + radius + 1), max(0, x - radius) : min(raw.shape[1], x + radius + 1)]
        median_bgr = np.median(patch.reshape(-1, 3), axis=0).astype(np.uint8)
        hsv = cv2.cvtColor(median_bgr.reshape(1, 1, 3), cv2.COLOR_BGR2HSV)[0, 0]
        hue, saturation, value = (int(component) for component in hsv)
        saturation_bounds = (max(0, saturation - 80), min(255, saturation + 80))
        value_bounds = (max(0, value - 80), min(255, value + 80))
        hue_low, hue_high = hue - 10, hue + 10
        if hue_low < 0:
            hue_ranges = ((0, hue_high), (180 + hue_low, 179))
        elif hue_high > 179:
            hue_ranges = ((hue_low, 179), (0, hue_high - 180))
        else:
            hue_ranges = ((hue_low, hue_high),)
        hsv_ranges = tuple(
            (
                (low, saturation_bounds[0], value_bounds[0]),
                (high, saturation_bounds[1], value_bounds[1]),
            )
            for low, high in hue_ranges
        )
        lower, upper = hsv_ranges[0]
        self.config = replace(
            self.config,
            health_bar=replace(
                self.config.health_bar,
                hsv_lower=lower,
                hsv_upper=upper,
                hsv_ranges=hsv_ranges if len(hsv_ranges) > 1 else (),
            ),
        )
        self.runner.update_health_bar(self.config.health_bar)
        self.preview_help.set(f"已吸取颜色 HSV {(hue, saturation, value)}。观察置信度，满意后点击主界面的“保存配置”。")
        self.status.set(f"已取色 HSV {(hue, saturation, value)}；点击“保存配置”生效")

    def _preview_zoom_by(self, multiplier: float, anchor: tuple[int, int] | None = None) -> None:
        source_anchor: tuple[float, float] | None = None
        if self.preview_canvas is not None and anchor is not None:
            source_anchor = (
                self.preview_canvas.canvasx(anchor[0]) / self.preview_scale,
                self.preview_canvas.canvasy(anchor[1]) / self.preview_scale,
            )
        next_zoom = min(4.0, max(0.25, self.preview_zoom * multiplier))
        if next_zoom == self.preview_zoom:
            return
        self.preview_zoom = next_zoom
        if self.preview_canvas is not None:
            self.preview_canvas.delete("selection")
        rendered = self._refresh_preview(force=True)
        if self.preview_canvas is not None and source_anchor is not None and rendered:
            image_bounds = self.preview_canvas.bbox("frame")
            if image_bounds is None:
                return
            image_width = max(1, image_bounds[2] - image_bounds[0])
            image_height = max(1, image_bounds[3] - image_bounds[1])
            left = source_anchor[0] * self.preview_scale - anchor[0]
            top = source_anchor[1] * self.preview_scale - anchor[1]
            max_left = max(0, image_width - self.preview_canvas.winfo_width())
            max_top = max(0, image_height - self.preview_canvas.winfo_height())
            self.preview_canvas.xview_moveto(min(max(left, 0), max_left) / image_width)
            self.preview_canvas.yview_moveto(min(max(top, 0), max_top) / image_height)

    def _preview_fit(self) -> None:
        self.preview_zoom = 1.0
        if self.preview_canvas is not None:
            self.preview_canvas.delete("selection")
            self.preview_canvas.xview_moveto(0)
            self.preview_canvas.yview_moveto(0)
        self._refresh_preview(force=True)

    def _preview_mousewheel(self, event: tk.Event) -> str:
        self._preview_zoom_by(1.25 if event.delta > 0 else 0.8, anchor=(event.x, event.y))
        return "break"

    def _preview_pan_start(self, event: tk.Event) -> str:
        if self.preview_canvas is not None:
            self.preview_canvas.scan_mark(event.x, event.y)
            self.preview_canvas.configure(cursor="fleur")
        return "break"

    def _preview_pan_drag(self, event: tk.Event) -> str:
        if self.preview_canvas is not None:
            self.preview_canvas.scan_dragto(event.x, event.y, gain=1)
        return "break"

    def _preview_pan_end(self, _: tk.Event) -> str:
        if self.preview_canvas is not None:
            self.preview_canvas.configure(cursor="crosshair")
        return "break"

    def _close(self) -> None:
        self.runner.stop()
        self.hotkeys.stop()
        self._close_preview()
        self.root.destroy()

    def run(self) -> int:
        try:
            self.hotkeys.start()
        except (HotkeyRegistrationError, OSError, ValueError) as error:
            # The UI remains usable through its buttons.  Most commonly this
            # means another copy of the app (or another tool) owns F8/F12.
            self.status.set("全局热键不可用 · 可使用界面按钮启动/停止")
            self.root.after(0, lambda: messagebox.showwarning("全局热键不可用", str(error), parent=self.root))
        self.refresh_windows()
        self.root.after(250, self._refresh_status)
        self.root.mainloop()
        return 0


def run_ui(config_path: str | Path) -> int:
    if __import__("os").name != "nt":
        raise WindowsOnlyError("The desktop control panel must run on Windows.")
    return GameAssistApp(config_path).run()
