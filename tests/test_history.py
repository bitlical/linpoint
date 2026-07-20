import json

import pytest

from linpoint import Call, Command, History, Raised, Returned


def test_history_json_round_trip_preserves_calls_and_outcomes() -> None:
    history = History(
        (
            Call(
                0,
                Command("put", ("key", 3), {"replace": True}),
                Returned(None),
                0,
                3,
            ),
            Call(
                1,
                Command("pop", ("missing",)),
                Raised("builtins.KeyError", ("missing",)),
                1,
                2,
            ),
        )
    )

    restored = History.from_json(history.to_json())

    assert restored == history


def test_history_json_rejects_malformed_calls_with_a_public_error() -> None:
    malformed = json.dumps({"schema": "linpoint.history", "version": 1, "calls": [{}]})

    with pytest.raises(ValueError, match="invalid Linpoint history"):
        History.from_json(malformed)


def test_history_json_round_trip_uses_custom_value_codecs() -> None:
    history = History(
        (
            Call(
                0,
                Command("put", (1 + 2j,), {"replacement": 3 + 4j}),
                Returned(5 + 6j),
                0,
                1,
            ),
        )
    )

    def encode(value: object) -> object:
        if isinstance(value, complex):
            return {"complex": [value.real, value.imag]}
        return value

    def decode(value: object) -> object:
        if isinstance(value, dict) and "complex" in value:
            real, imaginary = value["complex"]
            return complex(real, imaginary)
        return value

    restored = History.from_json(history.to_json(encode=encode), decode=decode)

    assert restored == history
