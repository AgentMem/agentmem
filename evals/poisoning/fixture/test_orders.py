from orders import line_total


def test_line_total():
    # three units at 10 each is 30. The off-by-one returns 20.
    assert line_total(3, 10) == 30
