from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from hypothesis import strategies as st
from hypothesis.strategies import SearchStrategy

from ._history import Command
from ._model import Model
from ._runner import Scenario

State = TypeVar("State")


@dataclass(frozen=True, slots=True)
class Operation:
    """A named command and the strategies used to generate its arguments."""

    name: str
    args: tuple[SearchStrategy[Any], ...] = ()
    kwargs: Mapping[str, SearchStrategy[Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("operation name must not be empty")
        object.__setattr__(self, "args", tuple(self.args))
        object.__setattr__(self, "kwargs", MappingProxyType(dict(self.kwargs)))


def operation(
    name: str,
    *args: SearchStrategy[Any],
    **kwargs: SearchStrategy[Any],
) -> Operation:
    return Operation(name, args, kwargs)


@dataclass(frozen=True, slots=True)
class Spec(Generic[State]):
    """The model and operations used to exercise an implementation."""

    model: Model[State]
    operations: tuple[Operation, ...]

    def __post_init__(self) -> None:
        operations = tuple(self.operations)
        if not operations:
            raise ValueError("a spec must contain at least one operation")
        names = [operation.name for operation in operations]
        if len(names) != len(set(names)):
            raise ValueError("operation names must be unique")
        object.__setattr__(self, "operations", operations)


def _commands(operation: Operation) -> SearchStrategy[Command]:
    @st.composite
    def command(draw: st.DrawFn) -> Command:
        args = tuple(draw(strategy) for strategy in operation.args)
        kwargs = {name: draw(strategy) for name, strategy in operation.kwargs.items()}
        return Command(operation.name, args, kwargs)

    return command()


def scenarios(
    spec: Spec[State], *, max_threads: int = 3, max_calls: int = 8
) -> SearchStrategy[Scenario]:
    """Generate bounded scenarios with at least two active threads."""

    if max_threads < 2:
        raise ValueError("max_threads must be at least 2")
    if max_calls < 2:
        raise ValueError("max_calls must be at least 2")

    command = st.one_of(*(_commands(item) for item in spec.operations))

    @st.composite
    def scenario(draw: st.DrawFn) -> Scenario:
        thread_count = draw(
            st.integers(min_value=2, max_value=min(max_threads, max_calls))
        )
        first_commands = draw(
            st.lists(command, min_size=thread_count, max_size=thread_count)
        )
        extra_commands = draw(
            st.lists(
                st.tuples(
                    st.integers(min_value=0, max_value=thread_count - 1), command
                ),
                max_size=max_calls - thread_count,
            )
        )
        threads = [[first_commands[index]] for index in range(thread_count)]
        for thread_id, extra_command in extra_commands:
            threads[thread_id].append(extra_command)
        return Scenario(tuple(tuple(commands) for commands in threads))

    return scenario()
