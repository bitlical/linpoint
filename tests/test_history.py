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
