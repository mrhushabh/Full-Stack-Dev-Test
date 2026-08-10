# Field Estimate Tool

An on-site estimate builder for HVAC technicians. Pick the customer, tap the job,
show them the number.

The original brief is preserved in [BRIEF.md](BRIEF.md).

---

## Running it

```bash
./dev.sh
```

That creates the virtualenv, installs both halves, and starts both servers. Safe
to re-run.

On first run it creates `api/field_estimate.db` (SQLite) and imports the files in
`data/` into it. Delete that file to start over from the original dataset.

| | |
|---|---|
| App | http://localhost:5173 |
| API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |

Requires **Python 3.10+** and **Node 18+**. If your default `python3` is too old
or too new, `PYTHON=python3.12 ./dev.sh` overrides it.

Running the two halves separately:

```bash
cd api && .venv/bin/uvicorn app.main:app --reload   # :8000
cd web && npm run dev                               # :5173, proxies /api
```

Tests:

```bash
cd api && .venv/bin/python -m pytest    # 166 tests
```

### Running against Postgres

SQLite is the default so that setup is nothing. Postgres needs one extra install
and one environment variable — no code changes:

```bash
pip install -r api/requirements-postgres.txt
export FIELD_ESTIMATE_DATABASE_URL="postgres://user:pass@host/dbname"
./dev.sh
```

The connection string can be pasted exactly as a hosting provider prints it.
Neon, Supabase, Render and Heroku all hand out `postgres://…`, which SQLAlchemy
rejects because it wants an explicit driver; the app rewrites the scheme itself
rather than making anyone know that.

### Deploying

[`render.yaml`](render.yaml) defines both halves as a Render Blueprint:

| Service | What | Why |
|---|---|---|
| `field-estimate-web` | Static site on Render's CDN | The bundle is cached at the edge and never touches the API server |
| `field-estimate-api` | FastAPI web service | Talks to Postgres |

The static site **rewrites `/api/*` through to the API**, so the browser only ever
sees one domain. Two consequences worth having: there is no CORS to configure, and
no API URL baked into the build — the frontend keeps calling relative paths
exactly as it does locally.

Assets are cached hard (hashed filenames, one year, immutable) while `index.html`
is explicitly not, so a deploy can't leave browsers holding a stale shell that
points at files which no longer exist.

The database URL is marked `sync: false`, meaning Render prompts for it and stores
it as a secret rather than it living in the repo.

---

## The problem I decided I was solving

The brief says techs lose 10–45 minutes per estimate. Reading it closely, that
time isn't going into arithmetic — multiplying a rate by hours is not what takes
half an hour. It's going into **decisions** (which labor rate, how many hours, is
this repair even worth doing) and into **presentation** (the brief complains twice
about writing it up "in a way the customer can actually read" and the wait feeling
"less professional").

So a fast calculator would have missed most of the problem. What I built instead
does three things:

1. **Derives what it can from the customer record**, so the tech confirms rather
   than assembles
2. **Proposes the judgment calls, with its reasoning attached**, and puts the
   alternative one tap away
3. **Ends in a screen you can turn around**, with a hard boundary between what the
   tech sees and what the customer sees

---

## The `level` problem

This was the most interesting thing in the dataset. `labor_rates.json` keys on
`jobType` + `level`, but **`level` means three different things** depending on the
job type:

| | Job types | How it gets decided |
|---|---|---|
| **Derived** | install (residential / commercial / mini-split) | Falls out of the customer record |
| **Declared** | ductwork (repair / new-install) | Scope question only the tech can answer |
| **Judged** | diagnostic, repair, maintenance | Subjective severity |

The three get handled differently, because they *are* different:

**Derived** levels are inferred from the property and the tech just confirms.

**Declared** is deliberately *not* inferred. Nothing in a customer record predicts
whether ductwork is a repair or a new run, so `propose_levels()` returns no
proposal for ductwork at all. Guessing there would be noise dressed up as help.

**Judged** is where the tool earns its keep. Minor vs. major repair is
`$110/h × 0.5–2h` against `$135/h × 2–6h` — **a fifteen-fold spread hiding behind
one dropdown**. Asking a tech to pick blind invites an arbitrary answer to a
question worth hundreds of dollars.

So severity is **anchored to the part**. The tech already told us what they're
replacing; a capacitor is twenty minutes with a screwdriver and a compressor is a
day with a recovery machine. Category drives the proposal, with a cost threshold
to split cases the category can't:

```
EQ013  Emerson 1/4 HP Condenser Fan Motor   $185  ->  minor
EQ029  Regal Beloit ECM Blower Motor 3/4 HP $650  ->  major
```

Same category. Opposite answers. That's the case a category-only map gets wrong.

### Propose, don't decide

Every proposal carries its reason, a confidence rating, and the alternatives it
rejected. The tech is the expert on site and carries the liability — the tool's
job is to make the obvious choice one tap away and its reasoning visible enough to
argue with.

The clearest case is **CUST007, Brewed Awakening Coffee**: a *commercial* property
running *mini-splits*. Both levels have a fair claim, and it's a ~3× swing on the
labor total. The tool proposes mini-split as the more specific match, marks itself
**low confidence**, and offers the commercial rate with the reason you'd pick it.
It never silently resolves an ambiguity the data doesn't settle.

---

## The messy data

Three inconsistencies exist in the provided files:

| Where | What |
|---|---|
| `equipment.json` | EQ012 and EQ028 use `base_cost`; the other 28 use `baseCost` |
| `customers.json` | CUST008 uses `property_type` and `sqft`; the rest use `propertyType` / `squareFootage` |
| `customers.json` | `phone`, `systemAge`, `lastServiceDate` absent from some records |

Tolerance is declared **once, on the fields themselves**, rather than scattered as
`or` fallbacks through the application. This now runs at **import time**, when the
JSON is seeded into the database — which is where it belongs. Reconciling an
export from an older system is a one-off migration problem, not something the
application should re-solve on every request:

```python
cost: Decimal = Field(validation_alias=AliasChoices("baseCost", "base_cost"))
square_footage: int = Field(validation_alias=AliasChoices("squareFootage", "sqft"))
```

Everything downstream of validation sees one guaranteed shape and never needs to
know the source was uneven. A record that fails validation stops the import — a missing
cost that reaches the pricing engine becomes a wrong number on a customer's
estimate. Seeding only runs against an empty table, so customers added through
the app survive a restart.

**Absent optional fields stay `None`, never a default.** Brewed Awakening has no
`systemAge`; defaulting it to 0 would make an unknown system read as brand new and
silently suppress the repair-vs-replace advisory. Instead the tool says so and
withholds the advice that depended on it.

`tests/test_normalization.py` pins each of these against the specific records that
differ, so a later "tidy-up" of the normalization layer fails loudly.

---

## Everything lives in the database

Nothing the app serves is compiled in. The JSON files in `data/` are imported on
first run, and the presets and pricing assumptions — which began as Python
constants — are seeded into their own tables and read from there afterwards.

| Table | Source | Why it's stored |
|---|---|---|
| `customers`, `equipment`, `labor_rates` | `data/*.json` | The provided dataset |
| `presets` (+ lines) | `services/presets.py` | A shop can add or retire a common job without a redeploy |
| `pricing_config` | `config.py` | Markup was a code change; now it's a setting |
| `estimates` (+ lines) | written by the app | Only the ones a tech acts on |

Seeding runs **only against an empty table**, so a shop's edits are never reverted
by a restart. There's a test for that specifically.

Moving the config out of code fixed a real problem: the settings panel used to
live in browser state alone, so changing the markup updated every total on screen
and then silently reverted on refresh — leaving the figure the tech was looking at
disagreeing with the one the server would actually quote.

---

## Customers and saved estimates

**Search finds nobody → add them.** Five fields are required: name, address,
property type, square footage, system type. Phone, system age and last service
date are optional — **the same three that are missing from real records in the
provided dataset**, and the three a tech at an unfamiliar property is least
likely to know. Requiring them would require a guess, and a guessed system age
silently drives the repair-vs-replace advice. A property added at the door is a
first-class customer immediately: same guidance, same proposals, same history.

**An estimate is only stored when the tech acts on it.** Building and showing a
quote leaves no trace. After the customer-facing screen there are three choices:

| | |
|---|---|
| **Going ahead** | saved as `approved` |
| **Thinking about it** | saved as `held` |
| **Not interested** | discarded, nothing written |

Most quotes are conversations, not records. A history cluttered with every number
ever shown on a doorstep is a history nobody reads — so the ones that survive are
exactly the ones worth seeing next visit. Held estimates can be approved later,
and anything saved can be deleted.

### Saved estimates snapshot their prices

This is the part that would have been expensive to retrofit.

A stored estimate copies its unit prices, labour rates, hours **and the pricing
assumptions in force at the time** onto its own rows. It does not reference the
live catalog. A quote is a promise made on a particular day: if a compressor's
cost changes next month, the estimate a customer is holding must not quietly
change with it. `test_saved_prices_survive_a_catalog_change` pins this — it saves
a quote, raises the part's cost by $400, and asserts the saved figure is unmoved
while a *new* estimate picks up the new price.

For the same reason, saved line items keep `equipment_id` as a plain column rather
than a foreign key: the record has to survive the part being discontinued.

And `POST /estimates/save` accepts line items, never a total. **The server
re-prices and stores what it calculated** — the browser is not the authority on
what a job costs.

---

## Money

**Every monetary value is a `Decimal`, never a float**, and money crosses the wire
as a *string*.

This isn't ceremony. The product of this app is a number a customer gets billed
from, and binary floating point fails at exactly that job:

```python
>>> 0.1 + 0.2
0.30000000000000004
>>> round(1.005, 2)     # the half-cent is gone before rounding happens
1.0
```

Rounding is `ROUND_HALF_UP` (how invoices round) rather than Python's default
banker's rounding, and it happens **once per line and once per total** rather than
compounding at each step.

Serializing to JSON as a number would hand the value to JavaScript as an IEEE-754
double and reintroduce on the client precisely the problem `Decimal` solves on the
server. So the API emits `"1390.00"`, and the frontend calls `Number()` only at
the final render, where a representation error can't propagate into anything.

### The formula

```
equipment line = quantity × cost × markup
labor line     = hourly_rate × hours
subtotal       = equipment + labor + misc
credit         = diagnostic labor, when work is approved on the spot
tax            = tax_rate × taxable base
total          = subtotal − credit + tax
```

Evaluated **three times** — at minimum, chosen, and maximum hours — because the
source data expresses duration as a range, and collapsing that to one number would
invent precision the dataset doesn't have. The UI leads with the expected figure
and keeps low/high as the honest fallback when a customer asks "could it be more?"

### Worked example — Patricia Nguyen (CUST006), failed compressor

```
  Copeland Scroll Compressor 3-Ton (EQ011)              $850.00
  Diagnostic · complex        2.0h × $125               $250.00
  Repair · major              4.0h × $135               $540.00
                                            subtotal  $1,640.00
                       diagnostic waived on approval    −$250.00
                                               TOTAL  $1,390.00

  Range at published hour bounds:            $1,120.00 – $1,660.00
```

This case is pinned in `tests/test_pricing.py`. The diagnostic resolves to
*complex* because Patricia has multiple systems and 22-year-old equipment — and
because a credited diagnostic washes out entirely, the total is the same as it
would be at the standard rate. The credit is a real modelling decision, not
cosmetic.

---

## Assumptions

The dataset gives equipment costs and labor rates and nothing else — no margin, no
tax, no business policy. Rather than bury guesses in the pricing code, all of them
live in `api/app/config.py`, ship with conservative defaults, are overridable
per-request, and are **exposed in the UI** so a tech can see which are in play.

| Knob | Default | Why |
|---|---|---|
| `equipment_markup` | **1.0×** | See below |
| `tax_rate` | **0.0** | Jurisdiction-specific and absent from the data. Surfaced as "not configured", not as a real $0.00 line |
| `credit_diagnostic_on_approval` | **on** | Near-universal HVAC practice; materially changes the number the customer hears |
| `end_of_life_years` | **15** | Typical residential HVAC service life is 15–20 years |
| `replace_cost_ratio` | **0.40** | Repair at ≥40% of replacement warrants the conversation |
| `major_repair_cost_threshold` | **$500** | Splits categories that span both severities |
| `sqft_per_ton` | **500** | Rule-of-thumb cooling load; a sanity check, not a Manual J |

### On markup

`labor_rates.json` is described as *"what we charge"* — already customer-facing.
`equipment.json` calls its field **`baseCost`**, which reads as a wholesale figure
with a customer price built on top. **The two files are priced on different
bases.** Adding them raw quotes equipment at cost and earns nothing on parts —
about $425 left on the table on the example above, and thousands on a rooftop unit.

I don't know which reading is right, and the brief doesn't say. So the default is
**1.0× — no markup** — because the tool should not quietly inflate a customer's
bill on the strength of my guess about someone else's margins. The capability is
built, the control is visible in the UI with this explanation attached, and every
estimate carries a warning while it's at cost. Set it to the real number and
everything updates.

---

## Where the tool takes a position

The repair-vs-replace comparison is the one place this stops being arithmetic.

It is deliberately conservative. The well-known **"$5,000 rule"** (age × repair
cost) is *supporting evidence only* — it cannot trigger the recommendation alone.
An $1,390 compressor job on an 8-year-old heat pump scores $11,120 and clears that
rule easily, despite that system having a decade of life left and repair being
obviously right. Used alone the rule turns the tool into an upsell machine, which
is exactly what would make a tech stop trusting it. Triggering requires the system
to be at end of life **or** the repair to be a large fraction of replacement cost.

The replacement is matched to **the system that actually failed**, not to a string
match on the customer record. Patricia's `systemType` is `"Central AC + Gas
Furnace"` — two systems. A compressor lives in the condenser, so it must compare
against the air conditioner:

```
compressor (EQ011) -> Goodman 3-Ton Central AC      $3,300
ignitor    (EQ023) -> Bryant Legacy Line Furnace    $2,800
```

Same customer, different part, correctly different system. My first version got
this wrong and offered to replace her furnace when her AC died.

It also says so when **repair wins** — which lets a tech tell a customer "I
checked, and fixing it is the better value."

Two smaller advisories: a **warranty prompt** when a major component fails on a
system under ~10 years (quoting a part the manufacturer would replace free is an
expensive mistake), and a **sizing sanity check** against square footage, which
only applies to whole systems — a 3-ton coil in a 5-ton system is a legitimate
repair the tool has no business second-guessing.

---

## Two themes, for two working conditions

Light is the default: warm paper tones, near-black text, deep green accents. It is
tuned for **daylight** — on a roof or a driveway a light screen wins, because
reflected ambient light works with you rather than against the backlight. The
common assumption that dark mode helps outdoors is backwards.

Dark mode exists for the other half of the job: **basements, crawlspaces, attics
and evening calls**, where a white screen is genuinely blinding. It is warm-toned
rather than the usual cold blue, so the two feel like one product.

The theme follows the device by default and can be overridden per-device from the
toolbar, because a tech walking down into a basement shouldn't have to leave the
app to change it. The choice is applied by a tiny inline script before first paint
— reading it in React would flash the wrong theme for a frame, which in a dark
basement is a face full of white.

The interface is also deliberately built for the conditions rather than for a
screenshot: 44px minimum touch targets because techs wear gloves, 16px minimum on
inputs because iOS Safari zooms the viewport below that, and the running total
pinned to the bottom of the viewport because "what does it come to" is the only
question actually being asked.

---

## Architecture

```
api/                 FastAPI + Pydantic + SQLAlchemy
  app/models/
    domain.py        Pydantic models; the normalization boundary
    tables.py        database schema
  app/services/      pricing · inference · advisory · presets · estimate_store
  app/seed.py        one-time JSON import
  app/config.py      every assumption, in one place
  tests/             166 tests
web/                 React + TypeScript + Vite
data/                the provided files, untouched
```

**SQLite by default, Postgres when hosted.** Requiring Postgres locally would mean
Docker or an install before anyone can run this, and every extra setup step is
another chance the project doesn't start on someone else's machine. But a hosted
deployment has to be Postgres: free platforms have disposable filesystems, so a
SQLite file is deleted on every deploy and the app would silently re-seed itself,
losing every customer anyone had added.

Everything goes through SQLAlchemy, so that switch is a connection string. The
two places the databases actually differ are handled explicitly and tested in
`tests/test_database_portability.py`:

**Money storage adapts to the backend.** Postgres gets a real `NUMERIC` column,
because `NUMERIC` sorts and sums correctly — as text, `"9.00"` sorts above
`"1000.00"`, so a query like "every estimate over $2,000" would quietly return
nonsense. SQLite has no decimal type at all and SQLAlchemy's `Numeric` silently
degrades to float there, which would undo the whole exact-decimal chain at the
last step, so SQLite stores text. Either way the application only ever sees
`Decimal`, and the API emits identical bytes.

**Connections survive the database going to sleep.** Free-tier Postgres suspends
when idle, which leaves pooled connections dead. Without `pool_pre_ping` the
first request after a quiet period fails — and on a portfolio site, that is
exactly the request a visitor makes when they open the link.

**Why a backend at all**, for three static JSON files: markup, the diagnostic
credit and the replacement thresholds are business rules. Business rules that ship
to the browser are business rules a customer can edit with devtools open. Pricing
is recalculated server-side on every edit rather than mirrored in the client —
which also means one implementation to keep correct, not two.

`POST /api/estimates` returns the priced estimate *plus* level proposals, sizing
checks, warranty flag and the repair-vs-replace comparison in a single response.
The UI reprices on every keystroke, and a tech in a basement should pay one round
trip for that.

Python over Node was chosen on fit: Pydantic's `AliasChoices` addresses the messy
data declaratively, and `decimal.Decimal` addresses the money problem as a
language feature rather than a discipline you have to maintain.

---

## What I'd do differently with more time

**Migrations.** The schema is created with `create_all`, which is fine for a
project at this size but has no upgrade path — the first schema change against a
database with real estimates in it would need Alembic. That's the next thing I'd
add.

**Offline support.** The most realistic omission. Techs work in basements and
mechanical rooms with no signal, and an estimate tool that needs a network is an
estimate tool that fails on site. Doing it properly means the pricing engine has
to run on the client — which conflicts directly with the server-side reasoning
above. The honest resolution is probably a signed rules bundle cached locally and
re-verified server-side before an estimate is sent.

**Generated API types.** `web/src/types.ts` is hand-written and could drift from
the server. `openapi-typescript` against `/openapi.json` in a prebuild step would
make drift a compile error.

**Delivery.** Print-to-PDF works, but emailing or texting the estimate is what
actually closes the loop the brief describes.

**Good/better/best.** The replacement comparison offers the cheapest adequate
unit. Real replacement conversations are three options, not one.

**Data the dataset lacks.** No after-hours or emergency labor rates — for a 40-tech
field operation that's a real revenue line that simply doesn't exist in the table.
No consumables either: a compressor swap needs several pounds of refrigerant and
there's nowhere in the catalog to put it, so there's a free-text misc line as an
escape hatch rather than pretending it's zero. And `jobType`+`level` as a composite
key with non-uniform semantics is a schema smell — severity, property class and
scope are three different axes overloaded into one string, and I'd normalize them
into a proper taxonomy.

**Multi-tech reality.** No auth, no per-tech attribution, no roles. One shared
config rather than per-shop settings. `next_customer_id()` walks existing IDs to
continue the `CUST0NN` sequence, which keeps added records visually consistent
with the seeded ones but would race under concurrent writes — a UUID or a database
sequence the moment there's more than one tech.

**Service history vs. estimates.** Right now an approved estimate is the service
record. In reality the work performed often differs from what was quoted — parts
swapped, hours run over — so a completed-job record that references its estimate
but records what actually happened would be the honest model. That would also let
`lastServiceDate` be derived from real visits instead of staying a static field.
