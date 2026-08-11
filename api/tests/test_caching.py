"""Query counts and HTTP caching.

These assert *how* the app gets its data, not just what it returns. Both problems
they cover were invisible in the tests and only showed up when the app was running
against a hosted database, where every query is a network round trip.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.db import engine


@pytest.fixture
def count_queries():
    """Count SQL statements issued while the block runs."""

    class Counter:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def __enter__(self):
            event.listen(engine, "before_cursor_execute", self._record)
            return self

        def __exit__(self, *_):
            event.remove(engine, "before_cursor_execute", self._record)

        def _record(self, conn, cursor, statement, params, context, many):
            self.statements.append(statement)

        def __len__(self) -> int:
            return len(self.statements)

    return Counter


# ---------------------------------------------------------------------------
# Query counts
# ---------------------------------------------------------------------------


def test_presets_do_not_n_plus_one(client, count_queries):
    """Presets must not cost one query per row.

    Lazily loading each preset's equipment and labour lines meant 1 + 18x2 = 37
    round trips to serve 18 presets, which measured 1.9 seconds against hosted
    Postgres -- on the screen shown immediately after picking a customer.

    Three queries: the presets, their equipment lines, their labour lines. The
    count must not grow with the number of presets, which is the property that
    actually matters.
    """
    with count_queries() as counted:
        assert client.get("/api/presets").status_code == 200
    assert len(counted) <= 4, f"{len(counted)} queries: {counted.statements}"


def test_pricing_an_estimate_does_not_refetch_the_same_rows(client, count_queries):
    """One keystroke should not re-read the same catalog rows repeatedly.

    Pricing looks equipment up to price it, again for the sizing and warranty
    checks, and again inside the repair-vs-replace comparison -- which prices a
    second estimate through the same path. Request-scoped memoization on the
    repository collapses those to one read each.
    """
    with count_queries() as counted:
        response = client.post(
            "/api/estimates",
            json={
                "customerId": "CUST006",
                "equipment": [{"equipmentId": "EQ011", "quantity": 1}],
                "labor": [
                    {"jobType": "diagnostic", "level": "standard", "hours": "1"},
                    {"jobType": "repair", "level": "major", "hours": "4"},
                ],
            },
        )
    assert response.status_code == 200
    assert len(counted) <= 8, f"{len(counted)} queries: {counted.statements}"


def test_more_line_items_do_not_multiply_queries(client, count_queries):
    """Adding parts must not add a query each.

    The whole catalog is already loaded by the replacement search, so every
    subsequent lookup is a cache hit.
    """
    def price(equipment_ids):
        with count_queries() as counted:
            client.post(
                "/api/estimates",
                json={
                    "customerId": "CUST006",
                    "equipment": [
                        {"equipmentId": e, "quantity": 1} for e in equipment_ids
                    ],
                    "labor": [{"jobType": "repair", "level": "major", "hours": "4"}],
                },
            )
        return len(counted)

    one = price(["EQ011"])
    many = price(["EQ011", "EQ018", "EQ023", "EQ014", "EQ022"])
    assert many <= one + 1, f"1 part: {one} queries, 5 parts: {many}"


# ---------------------------------------------------------------------------
# HTTP caching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/api/equipment", "/api/equipment/categories", "/api/labor-rates", "/api/presets"],
)
def test_reference_data_is_cacheable(client, path):
    response = client.get(path)
    assert "max-age=300" in response.headers["cache-control"]
    assert response.headers["etag"]


@pytest.mark.parametrize(
    "path", ["/api/equipment", "/api/labor-rates", "/api/presets", "/api/config"]
)
def test_unchanged_data_returns_304_with_no_body(client, path):
    first = client.get(path)
    repeat = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert repeat.status_code == 304
    assert repeat.content == b""


@pytest.mark.parametrize("prefix", ["", "W/"])
def test_weak_validators_still_match(client, prefix):
    """A proxy that compresses the response downgrades the ETag to weak.

    Render does this, so a tag sent as `"abc"` comes back as `W/"abc"`. Comparing
    exactly meant every revalidation missed and returned a full body -- which
    passed locally, because nothing sits between the test client and the app.
    RFC 7232 requires weak comparison for If-None-Match.
    """
    etag = client.get("/api/presets").headers["etag"].lstrip("W/")
    repeat = client.get("/api/presets", headers={"If-None-Match": prefix + etag})
    assert repeat.status_code == 304


def test_wildcard_and_multiple_etags_are_handled(client):
    etag = client.get("/api/presets").headers["etag"]
    assert client.get("/api/presets", headers={"If-None-Match": "*"}).status_code == 304
    assert (
        client.get(
            "/api/presets", headers={"If-None-Match": f'"stale", {etag}'}
        ).status_code
        == 304
    )


def test_a_different_etag_still_returns_the_body(client):
    response = client.get("/api/presets", headers={"If-None-Match": '"nonsense"'})
    assert response.status_code == 200
    assert response.content


def test_etag_changes_when_the_data_does(client):
    """A stale price is a worse failure than a slow request."""
    before = client.get("/api/config").headers["etag"]
    client.put(
        "/api/config",
        json={**client.get("/api/config").json(), "equipmentMarkup": "1.6"},
    )
    assert client.get("/api/config").headers["etag"] != before


def test_settings_always_revalidate(client):
    """Every total depends on these, so the browser must never reuse them blind."""
    assert "max-age=0" in client.get("/api/config").headers["cache-control"]


@pytest.mark.parametrize(
    "path", ["/api/customers", "/api/customers/CUST006/guidance"]
)
def test_customer_data_is_never_cached(client, path):
    """Customers and their history change while the app is open."""
    assert "cache-control" not in client.get(path).headers


def test_writes_are_never_cached(client):
    response = client.post(
        "/api/estimates",
        json={"labor": [{"jobType": "repair", "level": "minor", "hours": "1"}]},
    )
    assert "cache-control" not in response.headers
