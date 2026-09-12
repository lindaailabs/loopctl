from calculator import add, subtract


def test_add() -> None:
    assert add(1, 2) == 3


def test_subtract() -> None:
    assert subtract(5, 3) == 2
