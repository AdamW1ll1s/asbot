from __future__ import annotations

from typing import Any
from tkinter import ttk

from ..config import PluginConfig


class AutoHealSettingsPanel(ttk.Frame):
    """Plugin-owned settings UI for the built-in auto-heal feature."""

    def __init__(self, parent: ttk.Frame, host: Any) -> None:
        super().__init__(parent, style="Page.TFrame")
        self.host = host
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(2, weight=1)

        header = ttk.Frame(self, style="Panel.TFrame", padding=(18, 14))
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        title = ttk.Frame(header, style="Panel.TFrame")
        title.pack(side="left")
        ttk.Label(title, text="自动喝血", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(title, text="内置插件 · v1.0.0 · HSV 血条识别", style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(
            header,
            text="启用插件",
            variable=host.auto_heal_enabled,
            command=host._refresh_plugin_catalog,
        ).pack(side="right")

        detector = ttk.Frame(self, style="Panel.TFrame", padding=18)
        detector.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(0, 12))
        ttk.Label(detector, text="识别设置", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(detector, text="判断间隔（毫秒）", style="Muted.TLabel").pack(anchor="w", pady=(14, 4))
        ttk.Entry(detector, textvariable=host.recognition_interval, width=15).pack(anchor="w")
        ttk.Checkbutton(detector, text="保存调试截图", variable=host.save_debug).pack(anchor="w", pady=(12, 0))
        ttk.Label(detector, textvariable=host.roi_text, style="Muted.TLabel", wraplength=285).pack(anchor="w", pady=(12, 0))
        ttk.Label(detector, textvariable=host.color_text, style="Muted.TLabel", wraplength=285).pack(anchor="w", pady=(5, 12))
        ttk.Button(detector, text="实时校准", style="Secondary.TButton", command=host.show_preview).pack(anchor="w")

        editor = ttk.Frame(self, style="Panel.TFrame", padding=18)
        editor.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(0, 12))
        ttk.Label(editor, text="动作设置", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(editor, text="生命值低于（%）", style="Muted.TLabel").pack(anchor="w", pady=(14, 4))
        ttk.Entry(editor, textvariable=host.threshold, width=16).pack(anchor="w")
        ttk.Label(editor, text="触发按键", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        ttk.Entry(editor, textvariable=host.heal_key, width=16).pack(anchor="w")
        ttk.Label(editor, text="支持 CTRL+1 组合键和 1,2 动作序列。", style="Muted.TLabel", wraplength=285).pack(anchor="w", pady=(8, 0))

        overview = ttk.Frame(self, style="Panel.TFrame", padding=18)
        overview.grid(row=2, column=0, columnspan=2, sticky="nsew")
        ttk.Label(overview, text="插件规则", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(overview, text="自动喝血插件内部的规则；其他插件拥有各自独立的规则和状态。", style="Muted.TLabel").pack(anchor="w", pady=(4, 10))
        self.rule_tree = ttk.Treeview(overview, columns=("threshold", "key", "cooldown"), show="tree headings", height=5)
        self.rule_tree.heading("#0", text="规则")
        self.rule_tree.heading("threshold", text="阈值")
        self.rule_tree.heading("key", text="按键")
        self.rule_tree.heading("cooldown", text="冷却")
        self.rule_tree.column("#0", width=160)
        self.rule_tree.column("threshold", width=80, anchor="center")
        self.rule_tree.column("key", width=90, anchor="center")
        self.rule_tree.column("cooldown", width=100, anchor="center")
        self.rule_tree.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self) -> None:
        for item in self.rule_tree.get_children():
            self.rule_tree.delete(item)
        for rule in (self.host.config.rules, *self.host.config.additional_rules):
            self.rule_tree.insert(
                "",
                "end",
                text=rule.name,
                values=(f"< {rule.heal_below_percent:g}%", rule.heal_key, f"{rule.cooldown_ms} ms"),
            )

    def plugin_config(self, existing: PluginConfig | None) -> PluginConfig:
        settings = {} if existing is None else existing.settings
        return PluginConfig("auto_heal", self.host.auto_heal_enabled.get(), dict(settings))

    def is_enabled(self) -> bool:
        return self.host.auto_heal_enabled.get()
