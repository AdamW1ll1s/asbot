from pathlib import Path

import pytest
import yaml

from game_assist.config import load_config, save_config


def test_saved_profile_can_be_loaded_again(tmp_path: Path) -> None:
    source = Path("config/profile.example.yaml")
    config = load_config(source)
    destination = tmp_path / "profile.yaml"

    save_config(destination, config)

    assert load_config(destination) == config
    assert config.recognition_interval_ms == 500


def test_old_profile_uses_default_recognition_interval(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    text = Path("config/profile.example.yaml").read_text(encoding="utf-8")
    profile.write_text(text.replace("  recognition_interval_ms: 500\n", ""), encoding="utf-8")

    assert load_config(profile).recognition_interval_ms == 500


def test_profile_without_plugin_section_enables_auto_heal(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    raw = yaml.safe_load(Path("config/profile.example.yaml").read_text(encoding="utf-8"))
    raw.pop("plugins")
    profile.write_text(yaml.safe_dump(raw), encoding="utf-8")

    assert load_config(profile).plugin_enabled("auto_heal")


def test_plugin_specific_settings_survive_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    destination = tmp_path / "saved.yaml"
    text = Path("config/profile.example.yaml").read_text(encoding="utf-8")
    source.write_text(
        text.replace("    enabled: true", "    enabled: true\n    model: monsters.onnx\n    confidence: 0.8"),
        encoding="utf-8",
    )

    config = load_config(source)
    save_config(destination, config)

    assert load_config(destination).plugin_settings("auto_heal") == {
        "model": "monsters.onnx",
        "confidence": 0.8,
    }


def test_rejects_too_short_recognition_interval(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    text = Path("config/profile.example.yaml").read_text(encoding="utf-8")
    profile.write_text(
        text.replace("recognition_interval_ms: 500", "recognition_interval_ms: 20"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="recognition_interval_ms"):
        load_config(profile)


def test_rejects_identical_toggle_and_emergency_hotkeys(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    text = Path("config/profile.example.yaml").read_text(encoding="utf-8")
    profile.write_text(
        text.replace('emergency_stop: "F12"', 'emergency_stop: "F8"'),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be different"):
        load_config(profile)


def test_primary_rule_name_survives_round_trip(tmp_path: Path) -> None:
    profile = tmp_path / "profile.yaml"
    text = Path("config/profile.example.yaml").read_text(encoding="utf-8")
    source = tmp_path / "source.yaml"
    source.write_text(text.replace("rules:\n", "rules:\n  name: Primary heal\n"), encoding="utf-8")

    config = load_config(source)
    save_config(profile, config)

    assert load_config(profile).rules.name == "Primary heal"


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("roi: [40, 45, 220, 18]", "roi: [-1, 45, 220, 18]", "roi"),
        ("min_confidence: 0.70", "min_confidence: 1.1", "min_confidence"),
        ("heal_below_percent: 30", "heal_below_percent: 101", "threshold"),
        ('heal_key: "5"', 'heal_key: "UNKNOWN"', "Unsupported key"),
    ],
)
def test_rejects_unsafe_values(tmp_path: Path, old: str, new: str, message: str) -> None:
    profile = tmp_path / "profile.yaml"
    text = Path("config/profile.example.yaml").read_text(encoding="utf-8")
    profile.write_text(text.replace(old, new), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_config(profile)
