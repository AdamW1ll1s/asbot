from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import base64
import shutil
import tkinter as tk
from tkinter import messagebox, ttk

import cv2

from .config import AppConfig, load_config, save_config
from .hotkeys import GlobalHotkeys
from .runner import AutomationRunner
from .windows import WindowsOnlyError, list_visible_windows


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
        self.save_debug = tk.BooleanVar(value=self.config.save_debug_frame)
        self.status = tk.StringVar(value="待命 · 请先选择目标窗口")
        self.window_count = tk.StringVar(value="尚未刷新")
        self.preview_window: tk.Toplevel | None = None
        self.preview_label: tk.Label | None = None
        self.preview_photo: tk.PhotoImage | None = None
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
        ttk.Checkbutton(settings, text="保存调试截图", variable=self.save_debug).grid(row=2, column=2, columnspan=2, sticky="w", padx=(18, 0), pady=(12, 0))

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
        return replace(
            self.config,
            window=replace(self.config.window, title_contains=title, process_id=self.process_id),
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
        if self.runner.running:
            return
        self.runner = AutomationRunner(self.config)
        self.runner.start()
        self.status.set("运行中 · 目标窗口必须保持前台")
        self.show_preview()
        self._refresh_status()

    def _stop(self) -> None:
        self.runner.stop()
        self.status.set("已停止 · 所有已按下按键已释放")
        self.start_button.configure(text="开始自动化")

    def _refresh_status(self) -> None:
        if self.runner.running:
            self.start_button.configure(text="运行中")
            if self.runner.last_reading:
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
        window = tk.Toplevel(self.root)
        window.title("Game Assist · 实时识别预览")
        window.configure(bg=self.BACKGROUND)
        window.geometry("820x560")
        ttk.Label(window, text="绿色框：识别可信  ·  橙色框：等待确认或置信度不足", style="Subtitle.TLabel").pack(anchor="w", padx=16, pady=(14, 8))
        self.preview_label = tk.Label(window, text="等待目标窗口画面…", bg="#07101c", fg=self.MUTED, font=("Segoe UI", 12), compound="center")
        self.preview_label.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.preview_window = window
        window.protocol("WM_DELETE_WINDOW", self._close_preview)

    def _close_preview(self) -> None:
        if self.preview_window is not None:
            self.preview_window.destroy()
        self.preview_window = None
        self.preview_label = None
        self.preview_photo = None

    def _refresh_preview(self) -> None:
        if self.preview_window is None or not self.preview_window.winfo_exists() or self.preview_label is None:
            return
        frame = self.runner.preview_frame()
        if frame is None:
            return
        height, width = frame.shape[:2]
        scale = min(780 / width, 470 / height, 1.0)
        image = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", image)
        if ok:
            self.preview_photo = tk.PhotoImage(data=base64.b64encode(encoded.tobytes()))
            self.preview_label.configure(image=self.preview_photo, text="")

    def _close(self) -> None:
        self.runner.stop()
        self.hotkeys.stop()
        self._close_preview()
        self.root.destroy()

    def run(self) -> int:
        self.hotkeys.start()
        self.refresh_windows()
        self.root.after(250, self._refresh_status)
        self.root.mainloop()
        return 0


def run_ui(config_path: str | Path) -> int:
    if __import__("os").name != "nt":
        raise WindowsOnlyError("The desktop control panel must run on Windows.")
    return GameAssistApp(config_path).run()
