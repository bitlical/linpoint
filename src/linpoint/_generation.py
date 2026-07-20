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
_EMPTY_KWARGS: Mapping[str, SearchStrategy[Any]] = MappingProxyType({})


def _empty_kwargs() -> Mapping[str, SearchStrategy[Any]]:
    return _EMPTY_KWARGS


@dataclass(frozen=True, slots=True)
class Operation:
    """A named command and the strategies used to generate its arguments."""

    name: str
    args: tuple[SearchStrategy[Any], ...] = ()
    kwargs: Mapping[str, SearchStrategy[Any]] = field(default_factory=_empty_kwargs)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("operation name must not be empty")
        object.__setattr__(self, "args", tuple(self.args))
        kwargs = MappingProxyType(dict(self.kwargs)) if self.kwargs else _EMPTY_KWARGS
        object.__setattr__(self, "kwargs", kwargs)


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
        names: set[str] = set()
        for operation in operations:
            if operation.name in names:
                raise ValueError("operation names must be unique")
            names.add(operation.name)
        object.__setattr__(self, "operations", operations)


def _commands(operation: Operation) -> SearchStrategy[Command]:
    name = operation.name
    argument_strategies = operation.args
    keyword_strategies = operation.kwargs

    @st.composite
    def command(draw: st.DrawFn) -> Command:
        args = (
            tuple(draw(strategy) for strategy in argument_strategies)
            if argument_strategies
            else ()
        )
        if not keyword_strategies:
            return Command(name, args)
        kwargs = {
            keyword: draw(strategy) for keyword, strategy in keyword_strategies.items()
        }
        return Command(name, args, kwargs)

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
        threads = [[command] for command in first_commands]
        for thread_id, extra_command in extra_commands:
            threads[thread_id].append(extra_command)
        return Scenario(tuple(tuple(commands) for commands in threads))

    return scenario()
