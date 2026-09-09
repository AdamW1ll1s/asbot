import pytest

from game_assist.input import VIRTUAL_KEYS, parse_key_expression, parse_single_key, virtual_key_name


def test_parses_sequence_and_chord() -> None:
    assert parse_key_expression("ctrl+1, a") == (
        (VIRTUAL_KEYS["CTRL"], VIRTUAL_KEYS["1"]),
        (VIRTUAL_KEYS["A"],),
    )


@pytest.mark.parametrize("value", ["", "CTRL+", "1,,2", "UNKNOWN", "CTRL+CTRL"])
def test_rejects_invalid_key_expressions(value: str) -> None:
    with pytest.raises(ValueError):
        parse_key_expression(value)


def test_numeric_virtual_key_round_trip_supports_recorded_keys() -> None:
    assert virtual_key_name(0xBA) == "VK_BA"
    assert parse_single_key("VK_BA") == 0xBA
