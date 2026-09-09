from __future__ import annotations

from typing import Any
import tkinter as tk
from tkinter import ttk

from ..config import PluginConfig
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

        header = ttk.Frame(self, style="Panel.TFrame", padding=(18, 14))
        header.pack(fill="x", pady=(0, 12))
        title = ttk.Frame(header, style="Panel.TFrame")
        title.pack(side="left")
        ttk.Label(title, text="自动按键", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(title, text="内置插件 · v1.0.0 · 安全宏脚本", style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(header, text="启用插件", variable=self.enabled, command=host._refresh_plugin_catalog).pack(side="right")

        body = ttk.Frame(self, style="Page.TFrame")
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
            "wait 300ms\n"
            "end\n\n"
            "条件可以用 and 连接。\n"
            "支持 percent、confidence、streak。\n\n"
            "脚本不会执行任意系统命令，所有按键仍受前台检查和 F12 控制。"
        )
        ttk.Label(help_card, text=help_text, style="Muted.TLabel", justify="left", wraplength=230).pack(anchor="w", pady=(12, 0))

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
