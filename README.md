# Field Estimate Tool

An on-site estimate builder for HVAC technicians. Pick the customer, tap the job,
show them the number.

**Live:** https://field-estimate-web.onrender.com — built for a phone.
The original brief is in [BRIEF.md](BRIEF.md).

---

## Running it

```bash
./dev.sh
```

Creates the virtualenv, installs both halves, starts both servers. Needs Python
3.10+ and Node 18+.

| | |
|---|---|
| App | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Tests | `cd api && .venv/bin/python -m pytest` — 188 tests |

First run creates `api/field_estimate.db` and imports `data/` into it. Delete that
file to start over.

SQLite is the local default so setup is one command. Postgres needs one env var
and no code changes:

```bash
pip install -r api/requirements-postgres.txt
export FIELD_ESTIMATE_DATABASE_URL="postgres://…"   # paste as your host prints it
```

---

## What I decided to build

The brief says techs lose 10–45 minutes per estimate. That time isn't arithmetic —
multiplying a rate by hours doesn't take half an hour. It goes into **decisions**
(which labour rate, how many hours, is this repair even worth doing) and into
**presentation** — the brief complains twice about writing it up "in a way the
customer can actually read".

So the tool derives what it can from the customer record, proposes the judgement
calls with its reasoning attached, and ends in a screen you can turn around.

---

## The `level` problem

The most interesting thing in the dataset. `labor_rates.json` keys on `jobType` +
`level`, but **`level` means three different things**:

| | Job types | Decided by |
|---|---|---|
| Derived | install | The property — inferred, tech confirms |
| Declared | ductwork | Scope only the tech knows — deliberately not inferred |
| Judged | diagnostic, repair, maintenance | Subjective severity |

The third is where the tool earns its keep. Minor vs major repair is `$110/h ×
0.5–2h` against `$135/h × 2–6h` — **a fifteen-fold spread behind one dropdown**.
Asking a tech to pick blind invites an arbitrary answer to a question worth
hundreds of dollars.

So severity is **anchored to the part**. The tech already said what they're
replacing; a capacitor is twenty minutes with a screwdriver, a compressor is a day
with a recovery machine. Category drives it, with a cost threshold for the cases
category can't split:

```
EQ013  Emerson 1/4 HP Condenser Fan Motor   $185  →  minor
EQ029  Regal Beloit ECM Blower Motor 3/4 HP $650  →  major
```

**Propose, don't decide.** Every proposal carries its reason, a confidence rating,
and the alternatives it rejected. The clearest case is CUST007 — a *commercial*
property running *mini-splits*, where both rates have a fair claim and it's a ~3×
swing. The tool proposes the more specific match, marks itself low confidence, and
offers the alternative. It never silently resolves an ambiguity the data doesn't
settle.

---

## The messy data

| Where | What |
|---|---|
| `equipment.json` | EQ012, EQ028 use `base_cost`; the other 28 use `baseCost` |
| `customers.json` | CUST008 uses `property_type` / `sqft` |
| `customers.json` | `phone`, `systemAge`, `lastServiceDate` missing from some records |

Tolerance is declared once, on the fields, at import time:

```python
cost: Decimal = Field(validation_alias=AliasChoices("baseCost", "base_cost"))
```

**Absent fields stay `None`, never a default.** Defaulting a missing `systemAge`
to 0 would make an unknown system read as brand new and silently suppress the
repair-vs-replace advice. `tests/test_normalization.py` pins each case.

---

## Money

Every amount is a `Decimal`, `ROUND_HALF_UP`, and crosses the wire as a **string** —
serializing as a JSON number hands it to JavaScript as a float and reintroduces
the exact problem `Decimal` solves.

```
equipment = qty × cost × markup
labour    = rate × hours
total     = equipment + labour − diagnostic credit + tax
```

Evaluated three times — minimum, chosen and maximum hours — because the source
data gives hour *ranges*, and collapsing that to one number invents precision.

**Worked example** (Patricia Nguyen, failed compressor), pinned in the tests:

```
Copeland Scroll Compressor 3-Ton              $850.00
Diagnostic · complex   2.0h × $125            $250.00
Repair · major         4.0h × $135            $540.00
                                subtotal    $1,640.00
                    diagnostic waived         −$250.00
                                   TOTAL    $1,390.00
```

---

## Assumptions

The dataset gives costs and rates — no margin, no tax, no policy. All of it lives
in `config.py`, is stored in the database, and is **editable in the UI**.

| Knob | Default | Why |
|---|---|---|
| `equipment_markup` | **1.0×** | See below |
| `tax_rate` | **0** | Jurisdiction-specific; shown as "not configured" |
| `credit_diagnostic_on_approval` | on | Near-universal practice; changes the number the customer hears |
| `end_of_life_years` | 15 | Typical HVAC service life |
| `replace_cost_ratio` | 0.40 | Repair at ≥40% of replacement warrants the conversation |

**On markup:** labour rates are described as *"what we charge"*. Equipment says
**`baseCost`** — a wholesale figure with a price built on top. The two files are
priced on different bases, so adding them raw earns nothing on parts. I don't know
which reading is right, so the default applies **no markup** rather than quietly
inflating a bill on my guess, with a warning shown while it's at cost.

---

## Where it takes a position

Repair-vs-replace is the one place this stops being arithmetic. It's deliberately
conservative: the well-known **$5,000 rule** (age × repair cost) is *supporting
evidence only*. A $1,390 compressor job on an 8-year-old heat pump scores $11,120
and clears that rule easily, despite repair obviously being right — used alone it
turns the tool into an upsell machine.

The replacement matches **the system that failed**, not a string match on the
record. Patricia has "Central AC + Gas Furnace"; a compressor compares against the
AC, an ignitor against the furnace. My first version got this wrong and offered to
replace her furnace when her AC died.

Also: a **warranty prompt** when a major part fails on a system under ~10 years,
and a **sizing check** against square footage.

---

## Architecture

```
api/     FastAPI · SQLAlchemy · Pydantic
  models/     domain models + database schema
  services/   pricing · inference · advisory · presets · settings
  config.py   every assumption, in one place
web/     React · TypeScript · Vite
data/    the provided files, untouched
```

**Everything is in the database** — the JSON files, and the presets and pricing
config that started as Python constants. Seeding only runs on empty tables, so
edits survive restarts.

**Pricing is server-side.** Markup and thresholds are business rules, and business
rules that ship to the browser are rules a customer can edit with devtools open.

**Money adapts to the backend.** Postgres gets real `NUMERIC`; SQLite has no
decimal type and SQLAlchemy silently degrades to float there, so it stores text.
Either way the API emits identical bytes — `tests/test_database_portability.py`
sweeps every endpoint to prove it.

**Deployment** ([`render.yaml`](render.yaml)): a CDN static site plus the API. The
static site rewrites `/api/*` to the API, so there's no CORS and no API URL baked
into the build.

### Performance

Measured against hosted Postgres before changing anything:

| | Before | After |
|---|---|---|
| `GET /api/presets` | 37 queries · 1,916 ms | 3 queries · **433 ms** |
| `POST /api/estimates` | 10 queries · ~800 ms | 5 queries · **495 ms** |

Presets wasn't a caching problem — it was an N+1 loading each preset's line items
separately. Caching it would have hidden a slow query behind a stale copy. Only
after fixing the queries did caching go on: ETag and `Cache-Control` on reference
data, nothing on anything that writes. Tests assert **query counts**, because both
problems were invisible to a suite that only checked responses.

---

## What I'd do differently

**Offline support.** The most realistic omission — techs work in basements with no
signal. Doing it properly means the pricing engine runs on the client, which
conflicts with keeping business rules server-side. The honest answer is a signed
rules bundle cached locally and re-verified before an estimate is sent.

**Migrations.** `create_all` has no upgrade path; the first schema change against
real data needs Alembic.

**Navigation.** Back from the build screen currently discards the estimate, and the
OS back gesture leaves the app — there's no history integration. That's the worst
remaining bug.

**Generated API types.** `web/src/types.ts` is hand-written and could drift;
`openapi-typescript` would make that a compile error.

**Presets are my judgement, not data.** A real deployment would derive them from
"your eight most-quoted jobs this quarter" — the `estimates` table already holds
what's needed.

**Data the dataset lacks.** No after-hours or emergency rates, and no consumables —
a compressor swap needs refrigerant and there's nowhere to put it, hence the
free-text misc line. And `jobType`+`level` as a composite key with non-uniform
semantics is a schema smell worth normalizing into three separate axes.

**Multi-tech reality.** No auth, no per-tech attribution. `next_customer_id()`
would race under concurrent writes.
