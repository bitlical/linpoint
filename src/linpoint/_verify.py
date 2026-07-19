from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from hypothesis import given, settings

from ._checker import CheckResult, CheckStatus, check_history
from ._generation import Spec, scenarios
from ._history import Command, History, Raised, Returned
from ._minimize import minimize_history
from ._runner import Scenario, run

State = TypeVar("State")


def _format_command(command: Command) -> str:
    arguments = [repr(argument) for argument in command.args]
    arguments.extend(f"{name}={value!r}" for name, value in command.kwargs.items())
    return f"{command.name}({', '.join(arguments)})"


def _format_failure(history: History, result: CheckResult) -> str:
    lines = [
        f"history is not linearizable ({len(history)} calls, "
        f"{result.explored_states} states explored)",
        "",
    ]
    for call in history:
        if isinstance(call.outcome, Returned):
            outcome = f"returned {call.outcome.value!r}"
        elif isinstance(call.outcome, Raised):
            outcome = f"raised {call.outcome.type_name}{call.outcome.args!r}"
        lines.append(
            f"thread {call.thread_id}: [{call.invoked_at}, {call.returned_at}] "
            f"{_format_command(call.command)} {outcome}"
        )
    lines.extend(("", f"longest legal prefix: {len(result.longest_prefix)} calls"))
    return "\n".join(lines)


class NonLinearizable(AssertionError):
    """Raised when an observed history has no legal sequential ordering."""

    def __init__(self, history: History, result: CheckResult) -> None:
        self.history = history
        self.result = result
        super().__init__(_format_failure(history, result))


class Inconclusive(AssertionError):
    """Raised when checking a generated history exceeds its time budget."""

    def __init__(self, history: History) -> None:
        self.history = history
        super().__init__("linearizability check timed out")


class _FoundViolation(AssertionError):
    pass


class _CheckTimedOut(AssertionError):
    pass


def verify(
    *,
    implementation: Callable[[], Any],
    spec: Spec[State],
    max_threads: int = 3,
    max_calls: int = 8,
    attempts: int = 3,
    checker_timeout: float | None = None,
    hypothesis_settings: settings | None = None,
) -> None:
    """Generate concurrent scenarios and assert that every history is legal."""

    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    best_history: History | None = None
    best_result: CheckResult | None = None
    timed_out_history: History | None = None

    @given(scenario=scenarios(spec, max_threads=max_threads, max_calls=max_calls))
    def search(scenario: Scenario) -> None:
        nonlocal best_history, best_result, timed_out_history
        for _ in range(attempts):
            history = run(implementation, scenario)
            result = check_history(spec.model, history, timeout=checker_timeout)
            if result.status is CheckStatus.UNKNOWN:
                timed_out_history = history
                raise _CheckTimedOut
            if result.status is CheckStatus.NON_LINEARIZABLE:
                minimal = minimize_history(spec.model, history, timeout=checker_timeout)
                minimal_result = check_history(
                    spec.model, minimal, timeout=checker_timeout
                )
                if best_history is None or len(minimal) < len(best_history):
                    best_history = minimal
                    best_result = minimal_result
                raise _FoundViolation

    configured = hypothesis_settings or settings(deadline=None)
    try:
        configured(search)()
    except Exception as error:
        if best_history is not None and best_result is not None:
            raise NonLinearizable(best_history, best_result) from error
        if timed_out_history is not None:
            raise Inconclusive(timed_out_history) from error
        raise
