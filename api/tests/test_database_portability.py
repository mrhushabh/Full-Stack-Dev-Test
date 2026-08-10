"""The app has to behave identically on SQLite and on Postgres.

The default is SQLite so that `./dev.sh` works with nothing installed. Hosting
means Postgres, because free hosting platforms have disposable filesystems and a
SQLite file does not survive a deploy.

These tests cover the two places the databases differ in ways that would reach a
user: how connection URLs are spelled, and how decimals come back.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.db import _normalize_url
from app.services.estimate_store import _money, _plain


# ---------------------------------------------------------------------------
# Connection URLs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        # Neon, Supabase, Render and Heroku all print one of these two forms.
        # SQLAlchemy rejects both: it wants an explicit driver.
        (
            "postgres://u:p@host/db",
            "postgresql+psycopg://u:p@host/db",
        ),
        (
            "postgresql://u:p@host/db",
            "postgresql+psycopg://u:p@host/db",
        ),
        # Already explicit -- leave it alone.
        (
            "postgresql+psycopg://u:p@host/db",
            "postgresql+psycopg://u:p@host/db",
        ),
        # SQLite is untouched.
        ("sqlite:///./field_estimate.db", "sqlite:///./field_estimate.db"),
    ],
)
def test_provider_urls_are_usable_as_pasted(given, expected):
    """A URL copied straight from a hosting dashboard must just work."""
    assert _normalize_url(given) == expected


def test_normalization_only_rewrites_the_scheme():
    """Passwords and query strings must survive intact.

    Neon's URLs carry `?sslmode=require`, and passwords routinely contain
    characters a careless replace would mangle.
    """
    url = "postgres://user:p%40ss:w0rd@ep-cool-1.aws.neon.tech/main?sslmode=require"
    result = _normalize_url(url)
    assert result.endswith(
        "user:p%40ss:w0rd@ep-cool-1.aws.neon.tech/main?sslmode=require"
    )
    assert result.startswith("postgresql+psycopg://")


# ---------------------------------------------------------------------------
# Decimal formatting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored,expected",
    [
        # What SQLite's text column returns.
        (Decimal("1390.00"), "1390.00"),
        # What Postgres NUMERIC(16,6) returns for the same value.
        (Decimal("1390.000000"), "1390.00"),
        (Decimal("850"), "850.00"),
        (Decimal("0"), "0.00"),
        # Half-cent rounds up, matching how invoices round.
        (Decimal("47.475"), "47.48"),
    ],
)
def test_money_reads_the_same_from_either_database(stored, expected):
    """The API must emit identical bytes whichever backend is behind it."""
    assert _money(stored) == expected


def test_labour_hours_never_carry_the_storage_scale(client):
    """Hours are echoed straight back into an editable field in the UI.

    Postgres NUMERIC(16,6) turns 4 hours into Decimal('4.000000'), which reached
    the build screen as an hours box reading "4.0000".
    """
    priced = client.post(
        "/api/estimates",
        json={"labor": [{"jobType": "repair", "level": "major", "hours": "4"}]},
    ).json()
    line = priced["estimate"]["laborLines"][0]

    assert line["hours"] == "4"
    assert line["minHours"] == "2"
    assert line["maxHours"] == "6"


def test_preset_hours_are_clean_too(client):
    """Preset hours come out of the database on the same path."""
    request = client.get("/api/presets/compressor/request").json()
    assert [l["hours"] for l in request["labor"]] == ["1", "4"]


@pytest.mark.parametrize(
    "stored,expected",
    [
        (Decimal("2"), "2"),
        (Decimal("2.000000"), "2"),  # Postgres form of the same hours value
        (Decimal("1.5"), "1.5"),
        (Decimal("1.500000"), "1.5"),
        # Postgres returns 20 hours as 20.000000; normalize() alone makes that
        # 2E+1, which would land in the JSON response as "2E+1".
        (Decimal("20.000000"), "20"),
        (Decimal("1.115000"), "1.115"),  # markup
        (Decimal("0.087500"), "0.0875"),  # tax rate
    ],
)
def test_non_money_decimals_never_serialize_in_scientific_notation(stored, expected):
    assert _plain(stored) == expected
