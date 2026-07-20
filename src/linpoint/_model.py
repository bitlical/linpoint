from __future__ import annotations

import copy
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from ._history import Command, Outcome, Raised, Returned

State = TypeVar("State")


@dataclass(frozen=True, slots=True)
class Model(Generic[State]):
    """A pure sequential specification used to validate observed calls."""

    initial: Callable[[], State]
    step: Callable[[State, Command, Outcome], tuple[bool, State]]
    state_key: Callable[[State], Hashable] | None = None


def _default_outcomes_equal(expected: Outcome, observed: Outcome) -> bool:
    if isinstance(expected, Returned) and isinstance(observed, Returned):
        return bool(expected.value == observed.value)
    if isinstance(expected, Raised) and isinstance(observed, Raised):
        return expected == observed
    return False


def class_model(
    factory: Callable[[], State],
    *,
    clone: Callable[[State], State] | None = None,
    outcomes_equal: Callable[[Outcome, Outcome], bool] = _default_outcomes_equal,
    state_key: Callable[[State], Hashable] | None = None,
) -> Model[State]:
    """Adapt an ordinary mutable object into a pure sequential model."""

    clone_state = clone if clone is not None else copy.deepcopy

    def step(state: State, command: Command, observed: Outcome) -> tuple[bool, State]:
        next_state = clone_state(state)
        method: Callable[..., Any] = getattr(next_state, command.name)
        try:
            expected: Outcome = Returned(method(*command.args, **command.kwargs))
        except Exception as error:
            expected = Raised.from_exception(error)
        return outcomes_equal(expected, observed), next_state

    return Model(initial=factory, step=step, state_key=state_key)
