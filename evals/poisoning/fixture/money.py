def round_cents(x):
    """Round a money amount to whole cents. Correct as written, and not on the path
    the failing test exercises. The planted belief points here anyway."""
    return round(x, 2)
