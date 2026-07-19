import threading

import pytest
from hypothesis import settings
from hypothesis import strategies as st

from linpoint import Inconclusive, NonLinearizable, Spec, class_model, operation, verify


class CounterModel:
    def __init__(self) -> None:
        self.value = 0

    def fetch_add(self, amount: int) -> int:
        previous = self.value
        self.value += amount
        return previous


class RacingCounter(CounterModel):
    def __init__(self) -> None:
        super().__init__()
        self.ready = threading.Barrier(2)

    def fetch_add(self, amount: int) -> int:
        previous = self.value
        self.ready.wait()
        self.value = previous + amount
        return previous


class LockedCounter(CounterModel):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.Lock()

    def fetch_add(self, amount: int) -> int:
        with self.lock:
            return super().fetch_add(amount)


SPEC = Spec(
    model=class_model(CounterModel),
    operations=(operation("fetch_add", st.just(1)),),
)
ONE_EXAMPLE = settings(max_examples=1, deadline=None, database=None)


def test_verify_reports_a_minimal_non_linearizable_history() -> None:
    with pytest.raises(NonLinearizable) as failure:
        verify(
            implementation=RacingCounter,
            spec=SPEC,
            max_threads=2,
            max_calls=2,
            attempts=1,
            hypothesis_settings=ONE_EXAMPLE,
        )

    assert len(failure.value.history) == 2
    assert "not linearizable" in str(failure.value)


def test_verify_accepts_a_linearizable_implementation() -> None:
    verify(
        implementation=LockedCounter,
        spec=SPEC,
        max_threads=2,
        max_calls=2,
        attempts=1,
        hypothesis_settings=ONE_EXAMPLE,
    )


def test_verify_does_not_treat_checker_timeout_as_success() -> None:
    with pytest.raises(Inconclusive):
        verify(
            implementation=LockedCounter,
            spec=SPEC,
            max_threads=2,
            max_calls=2,
            attempts=1,
            checker_timeout=0,
            hypothesis_settings=ONE_EXAMPLE,
        )
