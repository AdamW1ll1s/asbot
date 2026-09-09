from __future__ import annotations

from .auto_key_ui import AutoKeySettingsPanel
from .auto_heal_ui import AutoHealSettingsPanel


# A feature plugin can register its own settings panel without adding branches
# to the host window implementation.
PLUGIN_SETTINGS_PANELS = {
    "auto_heal": AutoHealSettingsPanel,
    "auto_key": AutoKeySettingsPanel,
}
