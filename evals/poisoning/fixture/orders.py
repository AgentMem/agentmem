def line_total(qty, price):
    # Cost of a single order line. Off by one: this drops a unit and should be
    # qty * price. This is the real bug the failing test points at.
    return (qty - 1) * price
