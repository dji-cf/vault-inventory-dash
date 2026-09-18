# Vault Inventory / Dealernet — inventory dashboard

A Streamlit port of `vault_inventory_dashboard.html`, driven by a single
Sigma-validated query that joins the Oracle vault inventory snapshot to
Dealernet case prices. Deploys to Streamlit-in-Snowflake on the container
runtime.

The HTML file is kept in the repo as the **design reference** — it is the
authority on layout, colour, column order, and formatting. If the app and the
HTML disagree on how something looks, the HTML is right.

## What it shows

| Section | Content |
|---|---|
| Header | Live-snapshot label, data-pull freshness, SKU / brand / total-value facts, mapping split |
| KPI cards | Products, SKUs, Cases, Inventory Valuation, Current Market Value, Unrealized Gross Margin |
| Aging composition | Two donuts — cases and inventory value, by aging bucket |
| Inventory by brand | Two sorted bar charts — cases and inventory value, by brand bucket |
| Product detail | 22 columns in 7 banded groups, sortable, with a footer total row |
| Drill-down | Click any row for a 12-field panel |

Filters: a mapping toggle (ALL / MAPPED / NO PRICE), free-text search over
product name and item number, and five dropdowns (brand bucket, aging bucket,
street year, box type, price source).

## Data model

`queries.py` holds the whole thing — one statement, no bind parameters.

**Grain.** One row per `item_key`: `ITEM_NUMBER` with its `-CSE` / `-DB` suffix
stripped, so a product's case and display box collapse into a single SKU.

**Snapshot, not a time series.** `ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V`
is an SCD2 view and the query pins `END_DATE = '4712-12-31'` (the currently-open
record). There is **no as-of dimension**, so there is no period selector and the
header cannot honestly say "AS OF September". It says `LIVE SNAPSHOT` and pairs
that with a `DATA PULLED` stamp — relative age, with the absolute timestamp on
hover.

**Dealernet prices** join on (category, subcategory, box type, year) with a
three-tier year fallback: exact, then year−1, then year−2. Split-year products
(e.g. a 23/24 release mapped as 2024) carry 2023 in the orders table, which is
what the fallback recovers. `year_priority` records which tier won and dedupes to
one price per SKU; `year_match_type` surfaces it.

**The 0.8 wholesale factor, and where it does *not* apply.** There are two value
measures because Sigma has two:

- `market_value = quantity × dn_case_price` — **gross**, un-rounded. Feeds the
  *Current Market Value* and *Unrealized Gross Margin* KPI cards.
- `wholesale_value = quantity × dn_case_price × 0.8` — feeds the table's
  `WHOLESALE VALUE` column and its footer, plus every per-row margin measure
  (potential profit, margin $/case, markup multiple, margin %).

`dealernet_price_per_case` stays the raw average, so the table shows the market
price, the wholesale-adjusted value and the margins off the latter. See caveat 5
below before changing either basis.

## Known data caveats

These are surfaced in the UI rather than smoothed over. Both were confirmed
against the source data.

**1. ~36 SKUs carry no positive on-hand quantity.** The query deliberately keeps
every `-CSE` / `-DB` row regardless of quantity, while plain item numbers need a
positive quantity — that is what reconciles the SKU count to Sigma's 238. Zero
and negative rows are therefore expected. Charts scale by *absolute* value and
tint negative bars red so a negative bucket stays visible; the donut ring is
scaled by the positive total while its centre shows the true net.

**2. The margin headline implies a ~16× blended markup, and that is suspect.**
$65.5M market value against $4.37M Oracle cost. The skew concentrates in premium
box types — `Sapphire` and `Delight` — where the Oracle unit cost looks like a
**per-box** figure measured against a **per-case** Dealernet price. Worst case
observed: 2025/26 NBA Bowman Sapphire at $266/case Oracle cost vs a $27,241
Dealernet case price, 82×. Until that unit mismatch is resolved upstream, treat
*Current Market Value* and *Unrealized Gross Margin* as upper bounds. The app
prints a caption saying so whenever the blended markup exceeds 5×.

Note this is Sigma's number too, so matching it is correct even though the
economics are questionable — the fix belongs upstream in Oracle, not here.

**3. `brand_bucket` folds every unmapped brand into `'Other'`.** The bucket is a
COALESCE over a 76-row mapping table, so `Other` mixes explicitly-mapped brands
with unmapped ones and is coloured neutral gray for that reason. The bucket is
keyed on the **raw** Oracle brand and caveat 3b leaves it that way, so it is
unaffected by the brand merge.

**3b. Oracle sends one brand under two spellings, and the app merges them.**
`MLB` and `MAJOR LEAGUE BASEBALL` are one brand; so are `NBA`/`NATIONAL
BASKETBALL ASSOCIATION`, `NFL`, `UFC`, `WWE`, `DIS`/`Disney`, `MRV`/`Marvel`,
`STW`/`Star Wars`, `TEN`/`Tennis`, `CHP`/`UEFA Champions League`,
`FOR`/`Formula 1 Racing` and `VFR`/`Brand Other`. Left raw, each one split into
two table rows, two sort positions and two entries in the header's brand count.
`transforms.BRAND_CANON` folds each long form onto the acronym and
`data.load_inventory` applies it, so **31 raw spellings read as 20 brands**.
The verbatim value survives as `brand_oracle` and as the export's
*Brand (Oracle raw)* column.

This is deliberately an **app-layer** step, not a `queries.py` change — the SQL
stays reconciled to Sigma and its own 31-brand figure stays true. Two
consequences to know:

* `brand_bucket` still keys off the raw brand, so it is untouched and the
  brand-bucket bars stay bit-for-bit identical to Sigma. `brand_mapping` maps
  `CHP` → `Other` but `UEFA CHAMPIONS LEAGUE` → `Soccer` (and `TRB` → `Other`
  while `TOP RANK BOXING` → `Contact Sports`), so the merged `CHP` brand
  legitimately shows **both** `Soccer` (8 SKUs) and `Other` (13 SKUs) in the
  table. Re-deriving the bucket from the canonical name would move ~$167k from
  `Other` into `Soccer` and break that parity. Do not "fix" it without
  re-reconciling against the prod workbook.
* `BRAND_CANON` covers only pairs where **both** spellings exist in the view's
  open records. Lone codes stay verbatim — `MCD` (McDonalds All American) and
  `TRB` (Top Rank Boxing) are opaque but they are not duplicates.

**4. Two KPIs deliberately do not reconcile.** *Unrealized Gross Margin* nets the
market value of **priced** SKUs against the valuation of **all** SKUs, so
unpriced inventory drags it down. The markup chip beside it uses priced rows for
both numerator and denominator. That asymmetry is the workbook's own formula and
is reproduced on purpose.

**5. Two value bases, because Sigma has two.** The *Current Market Value* and
*Unrealized Gross Margin* KPIs read `market_value`, the **gross**
`dn_price × qty`. The table's `WHOLESALE VALUE` column — and the potential
profit, margin $/case, markup multiple and margin % derived from it — read
`wholesale_value`, which applies a **0.8** Dealernet wholesale discount. Sigma
draws exactly that line: its KPI is a plain `Sum([Dealernet Price per Case] *
[Quantity Cases])` while its `WHOLESALE_VALUE` column carries the 0.8. Sourcing
the KPIs from the discounted column understates both by 20% (it did, until
2026-09-15). Do not "unify" the two bases.

**6. The `- dev (1)` workbook's margin card is broken; use prod.** Workbook
`33a989e4-1f42-46b6-8450-ee0650a8102c` has a stale hardcoded literal in
*Unrealized Gross Margin* — `42549703.46 - Sum([Inventory Value])`, displaying
$38,174,715.31 — so it drifts every time Dealernet orders land. The parity
reference is **prod**, `8d898107-2c74-41a7-94b7-15909b773301`, which has the real
formula.

## Reference figures

Reproduce these before trusting any change to `queries.py` or `transforms.py`.
**Sigma is the source of truth for the headline numbers, not this app.**

| Measure | Value |
|---|---|
| SKUs | 238 |
| Products | 126 |
| Brands (canonical, what the header shows) | 20 |
| Brands (raw Oracle spellings) | 31 |
| Brand buckets | 10 |
| Box types | 15 |
| Cases | 11,292 |
| Inventory valuation | $4,374,988.145311472 |
| Inventory valuation (priced only) | $4,100,626.5655157333 |
| Market value (gross, KPI basis) | $65,486,623.8097 |
| Wholesale value (×0.8, table column + footer) | $52,389,299.03 |
| Potential profit (footer) | $48,288,672.49 |
| Unrealized gross margin | $61,111,635.66 |
| Blended markup (priced) | 15.97× |
| Mapping | 184 Mapped / 54 No Price |
| Aging SKUs 0-3 / 3-6 / 6-12 / 12-24 / 24+ | 31 / 50 / 49 / 85 / 23 |

Chart-level references, so a regression in one donut or bar is detectable rather
than hidden inside a matching grand total:

| Chart | Values |
|---|---|
| Aging by cases | 0-3 `1,228` · 3-6 `1,815` · 6-12 `2,894` · 12-24 `3,693` · 24+ `1,662` |
| Aging by inventory value | `550,879.32` · `757,814.32` · `1,191,910.75` · `1,338,493.52` · `535,890.24` |
| Brand bucket by cases | Baseball `5,814` · Basketball `1,799` · Entertainment `866` · Football `866` · Contact Sports `589` · NIL `529` · Other `446` · Soccer `183` · Formula One `180` · Tennis `20` |
| Brand bucket by inventory value | Baseball `1,955,584.05` · Basketball `1,153,271.91` · Football `314,275.38` · Entertainment `296,810.26` · Other `190,362.90` · Contact Sports `189,516.94` · NIL `98,288.73` · Soccer `89,225.18` · Formula One `74,652.19` · Tennis `13,000.60` |

Row-level spot check — `FGC006461-CSE`: qty `380`, unit cost `290.4444634407`,
inventory value `110,368.896107466`, DN price `5,042.735751295337`, market value
`1,916,239.585`, wholesale `1,532,991.67`, potential profit `1,422,622.77`,
margin $/case `3,743.74`, markup `13.89`, margin % `0.928`, `386` listings,
`Exact Year`.

Everything above was verified against the Sigma prod workbook column-for-column
on **2026-09-15**, including all 238 aging-bucket assignments and all 31
brand→bucket mappings. The SQL reproduces Sigma exactly, so it is not the place
to look first for a Sigma mismatch — check the aggregation in
`transforms.stat_cards` instead.

The brand merge of caveat 3b sits **downstream** of that reconciliation: it
renames a display column on the loaded frame and touches no measure, so every
figure above still holds. The one number it moves is the header's brand count,
31 → 20.

Aging bucket counts move as `CURRENT_DATE()` advances — the buckets are computed
from `DATEDIFF` against today, so a SKU migrates from `0-3 Months` to
`3-6 Months` on its own. Market value, wholesale value, margin and markup also
drift as new Dealernet orders land, because `case_price` is an all-time average
with no transaction-date window. The counts and the valuation should hold.

## Run locally

```powershell
# from c:\Users\dji\dashboards\vault-inventory-dash
& .venv\Scripts\python.exe -m streamlit run streamlit_app.py
```

Defaults are the `FANATICS_COLLECTIBLES_PROD` connection and the
`ANALYTICS_WAREHOUSE` warehouse, both hardcoded in `data.py`, so no env vars are
needed. To override:

```powershell
$env:SNOWFLAKE_DEFAULT_CONNECTION_NAME = "FANATICS_COLLECTIBLES_DEV"
$env:SNOWFLAKE_WAREHOUSE = "MY_WH"
$env:DASHBOARD_TZ = "America/Los_Angeles"   # DATA PULLED tooltip zone
```

### Recreating the venv

```powershell
python -m venv .venv
& .venv\Scripts\python.exe -m pip install -e .
# This machine's global keyring config forces a file backend, and any env
# missing keyrings.alt hard-crashes on connect instead of falling back.
& .venv\Scripts\python.exe -m pip install keyring keyrings.alt
```

## Deploy

```powershell
# needs snow >= 3.14 (3.21.0 installed)
snow streamlit deploy vault_inventory_dash --replace --role POWER_ANALYST_ORACLE_PROD
snow sql -q "SHOW STREAMLITS LIKE 'VAULT_INVENTORY_DASH' IN ACCOUNT"
```

Target: `ORACLE_DATA_PROD.SANDBOX.VAULT_INVENTORY_DASH`. The connection's default
role (`SVC_CLAUDE_MCP_ROLE`) cannot read the source tables, hence `--role`.

A clean exit from `snow streamlit deploy` is **not** proof of success — the
`SHOW STREAMLITS` check is. And `snow` does not verify that the paths under
`artifacts:` exist: a missing file uploads as a zero-byte stage object and the
app dies on first import, so confirm the artifact list after adding a module.

## Gotchas

- **Container runtime is required, not preferred.** `interactive.py` renders the
  product table through `st.components.v2`, which needs Streamlit ≥ 1.51.
  Never fall back to the warehouse runtime or `definition_version: 1.1`.
- **The PyPI EAI is mandatory** because `pyproject.toml` ships in `artifacts` —
  its mere presence triggers PyPI resolution. Without the integration the
  container build fails with "Failed to retrieve packages from the package
  server".
- **Component CSS ships separately.** The table renders in a shadow DOM, which
  page styles cannot pierce, so `style.TABLE_CSS` is injected into the component
  while `style.CSS` handles page chrome. Rules needed on both sides (chips,
  status pills, design tokens) live in shared blocks. Adding a table rule to
  `_CHROME_CSS` will silently do nothing.
- **Never write a `<` into the page CSS, not even in a comment.** `st.html`
  sanitizes with DOMPurify, whose `SAFE_FOR_XML` guard force-removes any element
  whose own text looks like markup, and it runs before the allowed-tags check. A
  `<style>` element is exactly that shape, so one `<header>` in a prose comment
  deletes the *entire* stylesheet and the whole dashboard renders as naked HTML
  with no error anywhere. This is what `style._checked()` exists to catch — it
  raises at import instead. `unsafe_allow_javascript=True` does not help: the
  guard runs first, and `elements/html.py` returns from the style-only branch
  before that flag is even assigned.
- **`st.html` strips inline SVG.** It passes DOMPurify
  `USE_PROFILES={'html': True}` with no `svg: True`, and `svg` is in DOMPurify's
  default `FORBID_CONTENTS`, so the element goes *with its children* — the donut
  rings vanish silently while their legends stay. Anything carrying SVG must go
  out through `style.render(..., raw=True)`, which uses `st.markdown`; that
  renderer runs rehype-raw with no sanitizer. Everything else stays on `st.html`,
  the stricter channel, which also avoids re-parsing free text as markdown.
- **No inline event handlers.** The SiS content-security policy forbids
  `onclick` and `eval`. Row and header clicks travel back through the
  component's `select` and `sort` triggers instead.
- **Trigger values are transient and absent until first fired.** Read them with
  `res.get("sort")`, never `res.sort` — attribute access raises on first render.
- **Ratios are never averaged.** Footer and KPI ratios are recomputed from summed
  additive columns (`Σprofit / Σwholesale`). Averaging per-SKU percentages weights
  a 1-case SKU like a 1,000-case one and gives a different, wrong answer.
- **Windows OAuth**: keep `client_store_temporary_credential = true` plus
  `oauth_enable_refresh_token = true` in `~/.snowflake/connections.toml`, with
  `keyrings.alt` installed, or every connect opens a browser.
- **No app logs.** There is no `SYSTEM$GET_SERVICE_LOGS` for a STREAMLIT object
  and no restart or scale knob. Redeploy with `--replace` to pick up changes.

## Files

| File | Role |
|---|---|
| `streamlit_app.py` | Layout, session state, filters, table round-trip, drill-down, export |
| `queries.py` | The single validated SQL statement |
| `data.py` | `st.connection` wiring (local / SiS / SPCS) + the cached loader |
| `transforms.py` | Formatters, filtering, KPI and chart aggregation, export shaping |
| `style.py` | Scoped CSS, chrome builders, inline-SVG charts, table + panel HTML |
| `interactive.py` | Clickable + sortable table via `st.components.v2` |
| `snowflake.yml` | Deployment manifest (container runtime) |
| `.streamlit/config.toml` | Theme tokens matching the HTML palette |
| `vault_inventory_dashboard.html` | Design reference — the authority on appearance |

## Deliberate departures from the HTML template

| HTML | Here | Why |
|---|---|---|
| `wholesale = dnPrice × qty` | `market_value` gross for the KPIs, `wholesale_value` `× 0.8` for the table column and margins | The mock predates the validated query; Sigma splits the two bases this way |
| `AS OF: Sep 2026` | `LIVE SNAPSHOT` + `DATA PULLED` | No as-of dimension exists in the view |
| 12-row pagination | Scroll cap + rows-per-view | The template's own comments specify this for the port |
| `onclick` sortable headers | `data-sort` + component trigger | Same behaviour; SiS forbids inline handlers |
| `exportTable()` alert stub | `st.download_button` | The template flags it as a stub for the port |
| Sticky full-bleed `<header>` | Rounded header card | Streamlit owns the scroll container |
