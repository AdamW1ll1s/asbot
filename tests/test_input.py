import pytest

from game_assist.input import VIRTUAL_KEYS, parse_key_expression


def test_parses_sequence_and_chord() -> None:
    assert parse_key_expression("ctrl+1, a") == (
        (VIRTUAL_KEYS["CTRL"], VIRTUAL_KEYS["1"]),
        (VIRTUAL_KEYS["A"],),
    )


@pytest.mark.parametrize("value", ["", "CTRL+", "1,,2", "UNKNOWN", "CTRL+CTRL"])
def test_rejects_invalid_key_expressions(value: str) -> None:
    with pytest.raises(ValueError):
        parse_key_expression(value)
