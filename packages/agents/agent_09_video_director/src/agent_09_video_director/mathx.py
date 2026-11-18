"""Integer arithmetic helpers: all times are integer ms, rounding is ``round_half_up`` (6.2)."""


def round_half_up(num: int, den: int) -> int:
    """``round(num / den)`` with halves rounded up, for non-negative num and positive den."""
    return (2 * num + den) // (2 * den)


def ceil_div(num: int, den: int) -> int:
    return -(-num // den)
