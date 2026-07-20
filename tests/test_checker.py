from itertools import permutations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from linpoint import (
    Call,
    CheckStatus,
    Command,
    History,
    Model,
    Returned,
    check_history,
    minimize_history,
)


def register_step(state: int, command: Command, observed: object) -> tuple[bool, int]:
    if command.name == "write":
        return observed == Returned(None), command.args[0]
    if command.name == "read":
        return observed == Returned(state), state
    return False, state


def test_overlapping_register_history_is_linearizable() -> None:
    history = History(
        (
            Call(0, Command("write", (100,)), Returned(None), 0, 5),
            Call(1, Command("read"), Returned(100), 1, 3),
            Call(2, Command("read"), Returned(0), 2, 4),
        )
    )

    result = check_history(Model(initial=lambda: 0, step=register_step), history)

    assert result.status is CheckStatus.LINEARIZABLE


def test_real_time_order_can_make_register_history_non_linearizable() -> None:
    history = History(
        (
            Call(0, Command("write", (200,)), Returned(None), 0, 5),
            Call(1, Command("read"), Returned(200), 1, 2),
            Call(2, Command("read"), Returned(0), 3, 4),
        )
    )

    result = check_history(Model(initial=lambda: 0, step=register_step), history)

    assert result.status is CheckStatus.NON_LINEARIZABLE
    assert result.linearization is None
    assert len(result.longest_prefix) == 2


def test_empty_history_is_linearizable_with_zero_timeout() -> None:
    result = check_history(
        Model(initial=lambda: 0, step=register_step), History(()), timeout=0
    )

    assert result.status is CheckStatus.LINEARIZABLE


@pytest.mark.parametrize("timeout", [-1.0, float("nan"), float("inf")])
def test_checker_rejects_invalid_timeouts(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout must be finite and non-negative"):
        check_history(
            Model(initial=lambda: 0, step=register_step), History(()), timeout=timeout
        )


def test_checker_handles_histories_deeper_than_python_recursion_limit() -> None:
    history = History(
        tuple(
            Call(0, Command("read"), Returned(0), index * 2, index * 2 + 1)
            for index in range(1_100)
        )
    )

    result = check_history(Model(initial=lambda: 0, step=register_step), history)

    assert result.status is CheckStatus.LINEARIZABLE
    assert result.linearization is not None
    assert len(result.linearization) == len(history)


def test_checker_memoizes_hashable_states_without_an_explicit_key() -> None:
    call_count = 10
    history = History(
        tuple(
            Call(
                thread_id,
                Command("read" if thread_id < call_count - 1 else "invalid"),
                Returned(0),
                0,
                1,
            )
            for thread_id in range(call_count)
        )
    )

    result = check_history(Model(initial=lambda: 0, step=register_step), history)

    assert result.status is CheckStatus.NON_LINEARIZABLE
    assert result.explored_states <= 2 ** (call_count - 1)


def test_minimizer_removes_calls_that_are_not_needed_for_the_violation() -> None:
    def counter_step(
        state: int, command: Command, observed: object
    ) -> tuple[bool, int]:
        if command.name == "fetch_add":
            return observed == Returned(state), state + command.args[0]
        if command.name == "read":
            return observed == Returned(state), state
        return False, state

    history = History(
        (
            Call(0, Command("read"), Returned(0), 0, 1),
            Call(0, Command("fetch_add", (1,)), Returned(0), 2, 5),
            Call(1, Command("fetch_add", (1,)), Returned(0), 3, 4),
        )
    )
    model = Model(initial=lambda: 0, step=counter_step)

    minimal = minimize_history(model, history)

    assert len(minimal) == 2
    assert {call.command.name for call in minimal} == {"fetch_add"}
    assert check_history(model, minimal).status is CheckStatus.NON_LINEARIZABLE


def test_minimizer_avoids_rechecking_every_removable_call_individually() -> None:
    step_calls = 0

    def counter_step(
        state: int, command: Command, observed: object
    ) -> tuple[bool, int]:
        nonlocal step_calls
        step_calls += 1
        if command.name == "noop":
            return True, state
        return observed == Returned(state), state + 1

    calls = [
        Call(0, Command("noop"), Returned(None), index * 2, index * 2 + 1)
        for index in range(64)
    ]
    calls.extend(
        (
            Call(0, Command("add"), Returned(0), 200, 203),
            Call(1, Command("add"), Returned(0), 201, 202),
        )
    )

    minimal = minimize_history(
        Model(initial=lambda: 0, step=counter_step), History(tuple(calls))
    )

    assert len(minimal) == 2
    assert step_calls < 500


@st.composite
def register_histories(draw: st.DrawFn) -> History:
    calls = []
    for thread_id in range(draw(st.integers(min_value=0, max_value=5))):
        invoked_at = draw(st.integers(min_value=0, max_value=4))
        returned_at = draw(st.integers(min_value=invoked_at, max_value=5))
        if draw(st.booleans()):
            command = Command("write", (draw(st.integers(0, 1)),))
            outcome = Returned(None)
        else:
            command = Command("read")
            outcome = Returned(draw(st.integers(0, 1)))
        calls.append(Call(thread_id, command, outcome, invoked_at, returned_at))
    return History(tuple(calls))


def register_oracle(history: History) -> bool:
    for order in permutations(range(len(history))):
        positions = {call_index: position for position, call_index in enumerate(order)}
        if any(
            first.returned_at < second.invoked_at
            and positions[first_index] > positions[second_index]
            for first_index, first in enumerate(history)
            for second_index, second in enumerate(history)
        ):
            continue

        state = 0
        for call_index in order:
            call = history.calls[call_index]
            legal, state = register_step(state, call.command, call.outcome)
            if not legal:
                break
        else:
            return True
    return False


@given(register_histories())
@settings(max_examples=500, deadline=None)
def test_checker_agrees_with_an_independent_permutation_oracle(
    history: History,
) -> None:
    result = check_history(Model(initial=lambda: 0, step=register_step), history)

    assert (result.status is CheckStatus.LINEARIZABLE) is register_oracle(history)
