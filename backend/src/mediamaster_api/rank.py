"""Fractional ranks: lexicographic base-62 keys with midpoint insertion.

Column order is rank ascending. rank_between(None, top) prepends,
rank_between(bottom, None) appends, rank_between(a, b) inserts between.
Mirrored in frontend/src/lib/rank.ts — keep the algorithms identical.
"""

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
BASE = len(DIGITS)


def _val(ch: str) -> int:
    return DIGITS.index(ch)


def rank_between(a: str | None, b: str | None) -> str:
    """A key strictly between a and b; None means an open end."""
    a = a or ""
    b = b or ""
    if a and b and a >= b:
        raise ValueError(f"rank_between requires a < b, got {a!r} >= {b!r}")

    result: list[str] = []
    i = 0
    while True:
        da = _val(a[i]) if i < len(a) else 0
        db = _val(b[i]) if i < len(b) else BASE  # open top behaves as base
        if db - da > 1:
            result.append(DIGITS[(da + db) // 2])
            return "".join(result)
        if db - da == 1:
            # lock in da; everything after only needs to exceed the rest of a
            result.append(DIGITS[da])
            j = i + 1
            while True:
                dj = _val(a[j]) if j < len(a) else 0
                if BASE - dj > 1:
                    result.append(DIGITS[(dj + BASE) // 2])
                    return "".join(result)
                result.append(DIGITS[dj])  # dj is the max digit; go deeper
                j += 1
        # equal digits: copy and continue
        result.append(DIGITS[da])
        i += 1


def evenly_spaced(n: int) -> list[str]:
    """n keys with wide, even gaps — for migrations and full re-sorts."""
    if n == 0:
        return []
    width = 2
    while BASE**width < (n + 1) * 2:
        width += 1
    total = BASE**width
    step = total // (n + 1)
    keys = []
    for k in range(1, n + 1):
        x = k * step
        digits = []
        for _ in range(width):
            x, r = divmod(x, BASE)
            digits.append(DIGITS[r])
        keys.append("".join(reversed(digits)))
    return keys
