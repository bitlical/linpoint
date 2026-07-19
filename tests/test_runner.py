import threading

from linpoint import Command, Raised, Returned, Scenario, run


class RacingCounter:
    def __init__(self) -> None:
        self.value = 0
        self.ready = threading.Barrier(2)

    def fetch_add(self, amount: int) -> int:
        previous = self.value
        self.ready.wait()
        self.value = previous + amount
        return previous


def test_runner_records_overlapping_calls_on_one_shared_object() -> None:
    scenario = Scenario(
        (
            (Command("fetch_add", (1,)),),
            (Command("fetch_add", (1,)),),
        )
    )

    history = run(RacingCounter, scenario)

    assert len(history) == 2
    assert [call.outcome for call in history] == [Returned(0), Returned(0)]
    first, second = history.calls
    assert first.invoked_at < second.returned_at
    assert second.invoked_at < first.returned_at


def test_runner_records_operation_exceptions_as_outcomes() -> None:
    class EmptyMap:
        def pop(self, key: str) -> None:
            raise KeyError(key)

    history = run(EmptyMap, Scenario(((Command("pop", ("missing",)),),)))

    assert history.calls[0].outcome == Raised("builtins.KeyError", ("missing",))
