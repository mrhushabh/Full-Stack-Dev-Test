"""Money helpers.

Everything monetary in this codebase is a `Decimal`, never a float. Estimates are
the product of the app -- a number a customer will be billed from -- so binary
floating point is not acceptable here. The classic failure is small and silent:

    >>> 0.1 + 0.2
    0.30000000000000004
    >>> round(1.005, 2)      # float: the half-cent is already lost before rounding
    1.0

Decimal arithmetic is exact, and `ROUND_HALF_UP` matches how humans (and invoices)
round, unlike Python's default banker's rounding.
"""

from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")

ZERO = Decimal("0")


def plain(value: Decimal) -> Decimal:
    """Strip a database's storage scale off a decimal, without going exponential.

    Postgres NUMERIC(16,6) hands back Decimal('4.000000') where SQLite's text
    column returns Decimal('4'). Left alone, that reaches the UI as an hours field
    reading "4.0000".

    `normalize()` alone is not the fix: it turns Decimal('20.000000') into
    Decimal('2E+1'), which serializes as "2E+1". Round-tripping through
    fixed-point notation gives a clean value on either backend.
    """
    return Decimal(format(value.normalize(), "f"))


def to_money(value: Decimal) -> Decimal:
    """Quantize to cents using half-up rounding.

    Applied at presentation boundaries only. Intermediate arithmetic keeps full
    precision so that rounding happens once, at the end, rather than accumulating
    at every step.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)
