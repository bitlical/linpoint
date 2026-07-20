# Linpoint

Model-based linearizability testing for Python objects.

[![CI](https://github.com/bitlical/linpoint/actions/workflows/ci.yml/badge.svg)](https://github.com/bitlical/linpoint/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Typing: typed](https://img.shields.io/badge/typing-typed-2F74C0)](src/linpoint/py.typed)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Linpoint generates operations with Hypothesis, runs them against one shared
object from several threads, records the resulting history, and checks whether
that history agrees with a sequential reference model.

Linpoint is an alpha project. Its public API may change before 1.0.

## Why Linpoint

Running a test several times in parallel can expose crashes and unsafe global
state, but it cannot tell whether a shared data structure returned a legal set
of results. Linpoint checks those results against the behavior you specified.

A failed check includes a call-deletion-minimal history and the longest legal
prefix found by the checker. The captured history is deterministic evidence of
the violation even when the thread schedule is not reproducible.

## Installation

Linpoint requires Python 3.11 or newer. Hypothesis is its only runtime
dependency.

```console
python -m pip install git+https://github.com/bitlical/linpoint.git
```

After the first PyPI release, installation becomes:

```console
python -m pip install linpoint
```

For local development with uv:

```console
uv sync --group dev
uv run pytest
```

## Quick Start

Define a small sequential model with the same operation names as the object
under test:

```python
import threading

from hypothesis import strategies as st

import linpoint


class CounterModel:
    def __init__(self) -> None:
        self.value = 0

    def fetch_add(self, amount: int) -> int:
        previous = self.value
        self.value += amount
        return previous

    def read(self) -> int:
        return self.value


class Counter:
    def __init__(self) -> None:
        self.value = 0
        self.lock = threading.Lock()

    def fetch_add(self, amount: int) -> int:
        with self.lock:
            previous = self.value
            self.value += amount
            return previous

    def read(self) -> int:
        with self.lock:
            return self.value


counter_spec = linpoint.Spec(
    model=linpoint.class_model(CounterModel),
    operations=(
        linpoint.operation("fetch_add", st.integers(min_value=1, max_value=3)),
        linpoint.operation("read"),
    ),
)


def test_counter_is_linearizable() -> None:
    linpoint.verify(
        implementation=Counter,
        spec=counter_spec,
        max_threads=3,
        max_calls=8,
        attempts=5,
        run_timeout=10.0,
    )
```

Each generated scenario has at least two active threads. Every attempt creates
a fresh `Counter`, while all threads in that attempt share that instance.

## Scheduling

`run()` and `verify()` use `scheduling="stress"` by default. Stress scheduling
aligns operations in rounds, synchronizes the first source-line boundaries of
concurrent Python methods, and adds bounded bytecode-level yields for methods
defined on one executable source line. This increases the chance of exposing
short race windows that normal GIL scheduling often misses.

Use `scheduling="native"` to observe only the runtime's natural scheduling:

```python
history = linpoint.run(Counter, scenario, scheduling="native")
```

Stress scheduling deliberately changes timing. It improves race detection but
does not guarantee that every concurrency bug will be triggered or reproduce
an exact thread schedule.

## Pure Models

Mutable model classes are copied before every checker branch. For more control,
define the model as a pure transition function:

```python
def counter_step(
    state: int,
    command: linpoint.Command,
    observed: linpoint.Outcome,
) -> tuple[bool, int]:
    if command.name == "fetch_add":
        amount, = command.args
        return observed == linpoint.Returned(state), state + amount

    if command.name == "read":
        return observed == linpoint.Returned(state), state

    return False, state


model = linpoint.Model(
    initial=lambda: 0,
    step=counter_step,
    state_key=lambda state: state,
)
```

The boolean returned by `step` says whether the observed outcome is legal. The
second value is the next model state. A `state_key` enables memoization; states
may share a key only when they are equivalent to the checker.

`class_model()` uses `copy.deepcopy()` by default. Pass `clone=` when the model
needs another copying strategy, or `outcomes_equal=` when returned values need
custom comparison.

## Checking Existing Histories

The checker and runner are also available separately:

```python
scenario = linpoint.Scenario(
    (
        (linpoint.Command("fetch_add", (1,)),),
        (linpoint.Command("read"),),
    )
)

history = linpoint.run(Counter, scenario, timeout=10.0)
result = linpoint.check_history(counter_spec.model, history, timeout=1.0)

if result.status is linpoint.CheckStatus.NON_LINEARIZABLE:
    minimal = linpoint.minimize_history(counter_spec.model, history)
```

`CheckStatus.UNKNOWN` means the checker reached its timeout. It is not a
successful result.

## Saving and Rechecking Evidence

Histories containing JSON-compatible values can be saved without pickle:

```python
encoded = history.to_json()
restored = linpoint.History.from_json(encoded)
result = linpoint.check_history(counter_spec.model, restored)
```

Use the explicit `encode=` and `decode=` callbacks for custom value types.
Unsupported values cause normal JSON serialization errors rather than an
unsafe or lossy fallback.

This replays the checker exactly. Re-running the same `Scenario` repeats the
workload, but Linpoint does not claim to reproduce the implementation's exact
internal thread schedule.

## Public API

| Name | Purpose |
| --- | --- |
| `verify()` | Generate scenarios and assert that every observed history is legal. |
| `Spec` and `operation()` | Define a model and Hypothesis argument strategies. |
| `Model` and `class_model()` | Define pure or mutable sequential reference behavior. |
| `run()` | Execute one explicit threaded `Scenario`. |
| `Scheduling` | Select stress scheduling or unmodified native scheduling. |
| `check_history()` | Check an existing `History` without running an implementation. |
| `minimize_history()` | Remove calls while preserving a proven violation. |
| `NonLinearizable` | Assertion containing the minimized history and checker result. |
| `RunTimedOut` | Timeout containing the partial history and active thread IDs. |
| `CheckStatus` | Distinguish linearizable, non-linearizable, and timed-out checks. |

Linpoint ships a `py.typed` marker, so type checkers use its inline annotations.

## Performance

Linpoint builds real-time precedence constraints in `O(n log n)` time and uses
an iterative depth-first search, so large sequential histories do not depend on
Python's recursion limit. Hashable model states are memoized automatically.
Provide `state_key=` for unhashable states so equivalent search branches can be
deduplicated.

## Free-Threaded Python

Linpoint works on regular and free-threaded CPython. Free-threaded builds are
available from Python 3.13 onward and can execute Python threads in parallel
when the GIL is disabled.

Run the same test suite on both builds. On a free-threaded build, verify the
runtime mode with:

```python
import sys

assert not sys._is_gil_enabled()
```

## Limits

- Linearizability checking is NP-hard. Keep generated histories small, provide
  a `state_key`, and set a checker timeout for untrusted workloads.
- Version 0.1 supports synchronous threads, not `asyncio`, processes, or
  distributed clients.
- Generated command arguments are independent. Values cannot yet refer to
  results returned by earlier generated commands.
- Stress scheduling coordinates Python source lines and yields at bytecode
  boundaries. C-extension methods and single-line operations may still require
  several attempts to expose a race.
- `verify()` limits each scenario to 10 seconds by default, and `run()` accepts
  an explicit timeout. Python cannot forcibly stop a blocked thread, so a timed-
  out worker remains a daemon until its operation returns. Keep a process-level
  timeout when testing hostile or permanently blocking code.
- The text report is intentionally small. HTML history visualization and
  partitioned checking are future work.

## License

Apache License 2.0. See [LICENSE](LICENSE).

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md),
[SECURITY.md](SECURITY.md), and [CHANGELOG.md](CHANGELOG.md).
