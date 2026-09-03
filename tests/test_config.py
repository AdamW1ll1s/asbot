from pathlib import Path

from game_assist.config import load_config, save_config


def test_saved_profile_can_be_loaded_again(tmp_path: Path) -> None:
    source = Path("config/profile.example.yaml")
    config = load_config(source)
    destination = tmp_path / "profile.yaml"

    save_config(destination, config)

    assert load_config(destination) == config
