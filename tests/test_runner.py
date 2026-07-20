import threading
import time
from typing import Any, cast

import pytest

from linpoint import Command, Raised, Returned, RunTimedOut, Scenario, run


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

    history = run(
        EmptyMap,
        Scenario(((Command("pop", ("missing",)),),)),
        scheduling="native",
    )

    assert history.calls[0].outcome == Raised("builtins.KeyError", ("missing",))


def test_runner_times_out_blocked_operations() -> None:
    release = threading.Event()

    class Blocked:
        def wait(self) -> None:
            release.wait()

    started = time.perf_counter()
    try:
        with pytest.raises(RunTimedOut) as failure:
            run(Blocked, Scenario(((Command("wait"),),)), timeout=0.01)
    finally:
        release.set()

    assert time.perf_counter() - started < 1
    assert failure.value.active_threads == (0,)


def test_runner_rejects_invalid_timeouts_before_starting_threads() -> None:
    with pytest.raises(ValueError, match="timeout must be finite and non-negative"):
        run(
            RacingCounter,
            Scenario(((Command("fetch_add", (1,)),),)),
            timeout=float("nan"),
        )


def test_runner_rejects_invalid_scheduling_modes() -> None:
    with pytest.raises(ValueError, match="scheduling must be 'native' or 'stress'"):
        run(
            RacingCounter,
            Scenario(((Command("fetch_add", (1,)),),)),
            scheduling=cast(Any, "invalid"),
        )
