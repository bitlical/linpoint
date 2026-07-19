from linpoint import Command, Returned, class_model


class CounterModel:
    def __init__(self) -> None:
        self.value = 0

    def fetch_add(self, amount: int) -> int:
        previous = self.value
        self.value += amount
        return previous


def test_class_model_clones_state_before_applying_a_command() -> None:
    model = class_model(CounterModel)
    initial = model.initial()

    legal, next_state = model.step(initial, Command("fetch_add", (2,)), Returned(0))

    assert legal
    assert initial.value == 0
    assert next_state.value == 2
