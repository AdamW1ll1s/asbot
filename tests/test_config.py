from pathlib import Path

import pytest

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
