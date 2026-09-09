from __future__ import annotations

from typing import Any
import tkinter as tk
from tkinter import messagebox, ttk

from ..config import PluginConfig
from ..recording import InputRecorder
from ..windows import activate_window, find_window
from .auto_key import DEFAULT_SCRIPT, parse_script


class AutoKeySettingsPanel(ttk.Frame):
    """Script editor owned by the AutoKey feature plugin."""

    def __init__(self, parent: ttk.Frame, host: Any) -> None:
        super().__init__(parent, style="Page.TFrame")
        self.host = host
        existing = next((item for item in host.config.plugins if item.plugin_id == "auto_key"), None)
        settings = {} if existing is None else existing.settings
        self.enabled = tk.BooleanVar(value=False if existing is None else existing.enabled)
        self.validation = tk.StringVar(value="保存配置时会自动校验脚本")
        self.recording_status = tk.StringVar(value="待命 · 录制时仅采集前台目标窗口")
        self.recording_name = tk.StringVar(value="录制宏")
        self.recorder: InputRecorder | None = None
        self._recording_finalized = True

        header = ttk.Frame(self, style="Panel.TFrame", padding=(18, 14))
        header.pack(fill="x", pady=(0, 12))
        title = ttk.Frame(header, style="Panel.TFrame")
        title.pack(side="left")
        ttk.Label(title, text="自动按键", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(title, text="内置插件 · v1.1.0 · 键鼠录制与安全宏", style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(header, text="启用插件", variable=self.enabled, command=host._refresh_plugin_catalog).pack(side="right")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        script_page = ttk.Frame(notebook, style="Page.TFrame", padding=(0, 12, 0, 0))
        record_page = ttk.Frame(notebook, style="Page.TFrame", padding=(0, 12, 0, 0))
        notebook.add(script_page, text="脚本编辑")
        notebook.add(record_page, text="操作录制")

        body = ttk.Frame(script_page, style="Page.TFrame")
        body.pack(fill="both", expand=True)
        editor_card = ttk.Frame(body, style="Panel.TFrame", padding=16)
        editor_card.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(editor_card, text="宏脚本", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(editor_card, textvariable=self.validation, style="Muted.TLabel").pack(anchor="w", pady=(3, 8))
        text_frame = ttk.Frame(editor_card, style="Panel.TFrame")
        text_frame.pack(fill="both", expand=True)
        self.editor = tk.Text(
            text_frame,
            bg="#07101c",
            fg=host.TEXT,
            insertbackground=host.TEXT,
            selectbackground=host.ACCENT_DARK,
            wrap="none",
            undo=True,
            font=("Consolas", 10),
            relief="flat",
            padx=12,
            pady=12,
        )
        vertical = ttk.Scrollbar(text_frame, orient="vertical", command=self.editor.yview)
        horizontal = ttk.Scrollbar(text_frame, orient="horizontal", command=self.editor.xview)
        self.editor.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.editor.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.editor.insert("1.0", str(settings.get("script", DEFAULT_SCRIPT)))
        ttk.Button(editor_card, text="检查脚本", style="Secondary.TButton", command=self.validate_script).pack(anchor="w", pady=(10, 0))

        help_card = ttk.Frame(body, style="Panel.TFrame", padding=16, width=265)
        help_card.pack(side="right", fill="y", padx=(6, 0))
        help_card.pack_propagate(False)
        ttk.Label(help_card, text="语法速查", style="CardTitle.TLabel").pack(anchor="w")
        help_text = (
            "macro 名称\n"
            "trigger start\n"
            "trigger every 5s\n"
            "when always\n"
            "when auto_heal.percent < 30\n"
            "repeat 3 / repeat forever\n"
            "press 1\n"
            "press CTRL+2 hold 80ms\n"
            "key_down W / key_up W\n"
            "move 320 240\n"
            "mouse_down left 320 240\n"
            "mouse_up left 320 240\n"
            "wheel 120 320 240\n"
            "wait 300ms\n"
            "end\n\n"
            "条件可以用 and 连接。\n"
            "支持 percent、confidence、streak。\n\n"
            "脚本不会执行任意系统命令，所有按键仍受前台检查和 F12 控制。"
        )
        ttk.Label(help_card, text=help_text, style="Muted.TLabel", justify="left", wraplength=230).pack(anchor="w", pady=(12, 0))

        self._build_record_page(record_page)

    def _build_record_page(self, page: ttk.Frame) -> None:
        card = ttk.Frame(page, style="Panel.TFrame", padding=20)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text="录制键盘与鼠标", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text="坐标以目标窗口客户区为基准；轨迹按 20ms 最小间隔采样。程序生成的注入事件不会被录入。",
            style="Muted.TLabel",
            wraplength=650,
            justify="left",
        ).pack(anchor="w", pady=(5, 18))
        form = ttk.Frame(card, style="Panel.TFrame")
        form.pack(fill="x")
        ttk.Label(form, text="宏名称", style="Muted.TLabel").pack(side="left")
        ttk.Entry(form, textvariable=self.recording_name, width=28).pack(side="left", padx=(10, 18))
        self.record_button = ttk.Button(form, text="开始录制", style="Accent.TButton", command=self.start_recording)
        self.record_button.pack(side="left")
        self.stop_record_button = ttk.Button(form, text="停止录制", style="Danger.TButton", command=self.stop_recording, state="disabled")
        self.stop_record_button.pack(side="left", padx=(8, 0))
        ttk.Label(card, textvariable=self.recording_status, foreground=self.host.ACCENT).pack(anchor="w", pady=(18, 0))
        ttk.Label(
            card,
            text=(
                "使用方法：选择目标窗口后点击“开始录制”，程序会自动切回目标窗口。完成后按 F10，"
                "结果会追加到“脚本编辑”页。F10 仅在录制期间作为停止键，不写入宏。\n\n"
                "录制会保留按下/释放时刻、鼠标按键、滚轮与轨迹。回放仍要求目标窗口位于前台，"
                "F12 可随时紧急停止。请仅用于你有权自动化的软件、测试环境或离线场景。"
            ),
            style="Muted.TLabel",
            wraplength=680,
            justify="left",
        ).pack(anchor="w", pady=(18, 0))

    def start_recording(self) -> None:
        if self.recorder is not None and not self.recorder.finished:
            return
        name = self.recording_name.get().strip()
        if not name or "\n" in name or "\r" in name:
            messagebox.showerror("无法录制", "请填写单行宏名称", parent=self)
            return
        title = self.host.window_title.get().strip()
        if not title:
            messagebox.showerror("无法录制", "请先在“运行控制”中选择目标窗口。", parent=self)
            return
        process_id = self.host.process_id if title == self.host.selected_window_title else None
        hwnd = find_window(title, process_id)
        if hwnd is None:
            messagebox.showerror("无法录制", "找不到已选择的目标窗口，请先在“运行控制”中重新选择。", parent=self)
            return
        if self.host.runner.running:
            self.host.runner.stop()
        self.recorder = InputRecorder(hwnd)
        try:
            self.recorder.start()
        except Exception as error:
            messagebox.showerror("录制器启动失败", str(error), parent=self)
            self.recorder = None
            return
        self._recording_finalized = False
        self.record_button.configure(state="disabled")
        self.stop_record_button.configure(state="normal")
        self.recording_status.set("录制中 · 0 个事件 · 按 F10 停止")
        self.host.status.set("宏录制中 · 仅采集前台目标窗口 · F10 停止")
        activate_window(hwnd)
        self.after(100, self._poll_recording)

    def stop_recording(self) -> None:
        if self.recorder is not None:
            self.recorder.stop()
            self.recording_status.set("正在整理录制结果…")

    def _poll_recording(self) -> None:
        recorder = self.recorder
        if recorder is None or self._recording_finalized:
            return
        if not recorder.finished:
            self.recording_status.set(f"录制中 · {recorder.event_count} 个事件 · 按 F10 停止")
            self.after(100, self._poll_recording)
            return
        self._recording_finalized = True
        self.record_button.configure(state="normal")
        self.stop_record_button.configure(state="disabled")
        if recorder.error is not None:
            self.recording_status.set(f"录制失败：{recorder.error}")
            messagebox.showerror("录制失败", str(recorder.error), parent=self)
            return
        try:
            script = recorder.to_script(self.recording_name.get().strip())
        except ValueError as error:
            self.recording_status.set(str(error))
            return
        existing = self.script().rstrip()
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", f"{existing}\n\n{script}" if existing else script)
        self.recording_status.set(f"录制完成 · {recorder.event_count} 个事件 · 已追加到脚本")
        self.validation.set("录制内容已追加，请检查脚本后保存配置")
        self.host.status.set("宏录制完成 · 请检查并保存配置")

    def shutdown(self) -> None:
        if self.recorder is not None:
            self.recorder.stop()

    def script(self) -> str:
        return self.editor.get("1.0", "end-1c")

    def validate_script(self) -> bool:
        try:
            macros = parse_script(self.script())
        except ValueError as error:
            self.validation.set(f"脚本错误：{error}")
            return False
        self.validation.set(f"脚本有效 · {len(macros)} 个宏")
        return True

    def refresh(self) -> None:
        pass

    def plugin_config(self, existing: PluginConfig | None) -> PluginConfig:
        script = self.script()
        parse_script(script)
        settings = {} if existing is None else dict(existing.settings)
        settings["script"] = script
        return PluginConfig("auto_key", self.enabled.get(), settings)

    def is_enabled(self) -> bool:
        return self.enabled.get()
