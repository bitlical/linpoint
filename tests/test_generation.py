from hypothesis import given, settings
from hypothesis import strategies as st

from linpoint import Command, Model, Outcome, Scenario, Spec, operation, scenarios


def unchanged(state: None, command: Command, outcome: Outcome) -> tuple[bool, None]:
    return True, state


SPEC = Spec(
    model=Model(initial=lambda: None, step=unchanged),
    operations=(
        operation("put", st.integers(), replace=st.booleans()),
        operation("get"),
    ),
)


@given(scenarios(SPEC, max_threads=4, max_calls=7))
@settings(max_examples=50)
def test_generated_scenarios_respect_thread_and_call_bounds(
    scenario: Scenario,
) -> None:
    assert 2 <= len(scenario.threads) <= 4
    assert all(scenario.threads)
    assert sum(map(len, scenario.threads)) <= 7
