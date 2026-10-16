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
| Header | Live-snapshot label, data-pull freshness, ↻ Refresh, SKU / licensor / total-value facts |
| KPI cards | Products, SKUs, Cases, Inventory Value, Wholesale Value, Potential Profit (with markup chip) |
| Aging composition | Two donuts — cases and inventory value, by aging bucket |
| Inventory & market value by brand | Two sorted bar charts by brand bucket, each with a toggle: Inventory (# of cases / inventory value) and Market (wholesale value / markup ×) |
| Product detail | 15 columns (a pinned product name plus 4 banded groups), sorted by clicking a header, 25 rows then scroll, with a footer total row |
| Drill-down | Click any row for a 12-field panel |

Filters: four dropdowns (brand bucket, aging bucket, street year, box type) drive
the whole page. The charts are a second way in: clicking an aging slice or legend
row, or a brand bar, sets that dropdown (clicking it again clears it), and each
chart ignores its own filter so it keeps showing every bucket with the pick
highlighted. A free-text search over product name and item number sits above
the table and narrows only the table, its footer, the export and the drill-down
list; the cards and charts do not move with it. There is no mapping toggle and no
price-source filter: the Wholesale Value card carries the not-priced count. How
the figures are built is in [`DISCLAIMERS.md`](DISCLAIMERS.md).

## Data model

`queries.py` holds the whole thing — one statement, no bind parameters.

**Grain.** One row per `item_key`: `ITEM_NUMBER` with its `-CSE` / `-DB` / `-PCK`
suffix stripped, so a product's case, display box and pack collapse into a single
SKU. Each row is counted in its own unit: a `-CSE` or plain row counts cases, a
`-DB` row counts display boxes and a `-PCK` row counts packs. `quantity_cases`
reports **case-equivalents** (5 boxes at 10 a case = 0.50), with the physical
`display_boxes` / `loose_packs` alongside. The item number shown prefers the case
row. A box or pack row that cannot be converted (no boxes per case, or for a pack
no packs per box) counts zero cases and makes its key No Price
(`unconverted_rows`).

**Snapshot, not a time series.** `ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V`
is an SCD2 view and the query pins `END_DATE = '4712-12-31'` (the currently-open
record). There is **no as-of dimension**, so there is no period selector and the
header cannot honestly say "AS OF September". It says `LIVE SNAPSHOT` and pairs
that with a `DATA PULLED` stamp — relative age, with the absolute timestamp on
hover.

**Dealernet prices** join on (category, subcategory, box type, year) with a
three-tier year fallback: exact, then year−1, then year−2. Split-year products
(e.g. a 23/24 release mapped as 2024) carry 2023 in the orders table, which is
what the fallback recovers. Both Dealernet units are read (`UOM` `case` and
`box`; there is no pack market), deduped to at most one case price and one box
price per SKU, each with its own tier. `year_priority` records which tier won
(the case tier when there is one); `year_match_type` surfaces it. Cases take the
case price. A display box takes the **box** price, or case ÷ boxes per case when
the SKU has no box market (David, 2026-09-29), and a pack takes that box rate ÷
packs per box.

**The 0.8 wholesale factor.** The query carries two value measures because Sigma
has two. The app headlines the wholesale one:

- `market_value = quantity × dn_case_price` — **Market Value**, the unadjusted
  (gross) Dealernet figure, un-rounded. Shown only in the *Wholesale Value*
  card's hover tooltip, plus the export and Sigma reconciliation. Sigma's two KPI
  cards read it (caveat 5).
- `wholesale_value = quantity × dn_case_price × 0.8` — **Wholesale Value**, 80%
  of the DN price. Feeds the *Wholesale Value* and *Potential Profit* KPI cards
  and the markup chip, the table's `WHOLESALE VALUE` column and its footer, the
  Market Value by Brand bars, plus every per-row margin measure (potential
  profit, margin $/case, markup multiple, margin %).

`dealernet_price_per_case` stays the raw case average for keys holding only cases.
For a key holding boxes or packs it is the blended per-case figure (market value ÷
case-equivalents), so quantity × price = market value on every row;
`dealernet_price_per_box` carries the raw box average. See caveat 5 below before
changing either basis.

## Known data caveats

These are documented rather than smoothed over; `DISCLAIMERS.md` has the short
version for readers. Both were confirmed against the source data.

**1. The app drops SKUs with no positive on-hand quantity.** The query
deliberately keeps every `-CSE` / `-DB` row regardless of quantity, while plain
item numbers need a positive quantity. That is what reconciles its SKU count to
Sigma's 238, so the SQL stays as it is. `data.load_inventory` then drops every
SKU whose `quantity_cases` is not positive, so the app counts only SKUs with
stock, and its SKU count no longer ties to Sigma. On the 2026-10-16 pull that
was 36 of 250 SKUs, all `-CSE` rows at exactly zero, carrying no cases and no
value, so every case and dollar figure is unchanged. Charts still scale by
*absolute* value and tint negative bars red, as a guard; the donut ring is
scaled by the positive total while its centre shows the true net.

**2. The markup chip is high (~13× wholesale over cost), and the cost basis is
sound.** `UNIT_COST` is Oracle standard **manufacturing** cost (COGS) **per case**,
not a purchase price and not a per-box figure. The evidence, from live queries on
2026-09-29 (`plans/01-data-basis-and-cost-fixes.md`, Context, and
`plans/README.md`, question 2):

- Within a product line the cost tracks box count and tier. A 2025 NFL Chrome
  Value Box case (40 boxes) costs $227, i.e. $5.68 a box; were $227 per box, the
  box would cost more than it sells for.
- Plain item numbers cost per case like `-CSE` rows (per-box medians by box type
  match), and `FGC006461-CSE` decomposes exactly into its cost elements (Auto
  On-Card + Auto Sticker + Printing and Packout = $290.44).
- The markup is broad-based, not a Sapphire quirk: hobby cases run a ~10× median
  gross markup, Sapphire ~32× and Delight ~22×, which fits product tier. Dealernet
  is internally consistent too (2025 Bowman Sapphire: $27,241 a case against
  $2,618 a box, ~10.4× for a 10-box case).

The one real unit error was on the three **`-DB` (display box)** rows, and it is
**fixed** (plan 01, 2026-10-01). One `-DB` unit is one box, with a per-box cost,
but the query used to count it as a case and price it at the case price. That
overstated value by about **0.2%** ($127,892 gross, $102,314 wholesale, 21.8
cases on the 2026-10-01 pull); inventory value was already right. Now a box
converts to case-equivalents and takes the Dealernet box price, and a key without
a case row scales its box cost up to a case. `FGC006035` (5 boxes, no case row)
moves from a 36.42× markup to 3.87×, and from Stale to Live on its box sales.
`-PCK` packs follow the same path; none has had stock yet, so their per-pack
`UNIT_COST` is an assumption to re-check on the first stocked pack (it moves
markup and margin, not value). `DISCLAIMERS.md` documents the conversion.

**3. `brand_bucket` folds every unmapped brand into `'Other'`.** The bucket is a
COALESCE over a 76-row mapping table, so `Other` mixes explicitly-mapped brands
with unmapped ones and is coloured neutral gray for that reason. The SQL keys
the bucket on the **raw** Oracle brand; caveat 3b covers the app-layer
correction on top of it.

**3b. Oracle sends one brand under two spellings, and the app merges them.**
`MLB` and `MAJOR LEAGUE BASEBALL` are one brand; so are `NBA`/`NATIONAL
BASKETBALL ASSOCIATION`, `NFL`, `UFC`, `WWE`, `DIS`/`Disney`, `MRV`/`Marvel`,
`STW`/`Star Wars`, `TEN`/`Tennis`, `CHP`/`UEFA Champions League`,
`FOR`/`Formula 1 Racing` and `VFR`/`Brand Other`. Left raw, each one split into
two table rows, two sort positions and two entries in the header's brand count.
`transforms.BRAND_CANON` folds each long form onto the acronym and
`data.load_inventory` applies it, so **31 raw spellings read as 20 brands**.
The verbatim value survives as `brand_oracle` and as the export's
*Licensor (Oracle raw)* column.

This is deliberately an **app-layer** step, not a `queries.py` change — the SQL
stays reconciled to Sigma and its own 31-brand figure stays true. Two
consequences to know:

* The SQL's `brand_mapping` keys the bucket off the raw brand and maps `CHP` →
  `Other` but `UEFA CHAMPIONS LEAGUE` → `Soccer` (and `TRB` → `Other` while
  `TOP RANK BOXING` → `Contact Sports`). The bucket is corrected in the **app
  layer** (David, 2026-09-29): `transforms.canonical_bucket` puts the merged
  `CHP` brand in `Soccer` and `TRB` in `Combat`, and renames `Contact Sports` to
  `Combat`. So the app's `brand_bucket` **diverges from Sigma** for CHP and TRB.
  On the 2026-09-15 data CHP's 13 SKUs (355 cases, $167,167.40 inventory,
  $997,633.10 wholesale) move from `Other` to `Soccer`; TRB is one zero-quantity
  SKU. The SQL's (Sigma's) bucket survives as `brand_bucket_oracle` for
  reconciliation; it is not exported.
* `BRAND_CANON` covers only pairs where **both** spellings exist in the view's
  open records. Lone codes stay verbatim — `MCD` (McDonalds All American) and
  `TRB` (Top Rank Boxing) are opaque but they are not duplicates.

**4. The value tiles and the footer share one formula.** With the search box
empty, each tile equals its footer total to the cent:

- *Wholesale Value* is Σ`wholesale_value` over **priced** SKUs
  (`transforms.priced_mask`, i.e. `wholesale_value` not null) — the footer's
  *Wholesale Value*.
- *Potential Profit* is Σ`total_potential_profit` (0.8 × market minus cost) over
  priced SKUs — the footer's *Potential Profit*. Unpriced SKUs are excluded, not
  counted at zero.
- The markup chip is `transforms.markup_ratio` (Σwholesale ÷ Σinventory over
  priced rows) — the footer's Markup Multiple. It is omitted unless that cost is
  positive.

The Market card's bars (both toggles; `transforms.brand_markup` for Markup ×)
are on the same basis, so a bucket's bar equals the footer filtered to it. The
unpriced count shows once, on the *Wholesale Value* card ("N SKUs not priced"),
and the unpriced cost is in the *Potential Profit* card's tooltip. The
*Wholesale Value* tooltip carries the gross Market Value. A view with no priced
SKU reads "—" on both value cards and in the footer, not $0
(`transforms._sum_or_none`). The search narrows only the table, so the tie holds
only with the search empty.

**5. The KPI cards diverge from Sigma's KPI cards, on purpose.** Prod workbook
`8d898107-2c74-41a7-94b7-15909b773301` headlines the gross basis: `Sum([DN Price
per Case] * [Quantity Cases])` for *Current Market Value*, and gross market minus
all inventory for *Unrealized Gross Margin*. It applies its 0.8 Dealernet
discount only in the `WHOLESALE VALUE` table column. The app headlines the
wholesale basis instead (*Wholesale Value*, *Potential Profit*), so the cards tie
to the table (caveat 4). History: plan 02 option A moved the cards on
2026-09-30, it was reverted on 2026-10-01 for Sigma parity, and it was re-adopted
on 2026-10-15 at the owner's request. On the 2026-10-15 pull Sigma's cards would
read about $70.7M / $66.1M against the app's $56.6M / $52.2M. To realign, Sigma's
two KPI formulas become `Sum([Wholesale Value])` and `Sum([Potential Profit])`.

For keys holding only cases the query's measures match Sigma, so Sigma's KPI
cards and its `WHOLESALE_VALUE` and profit columns tie to the app to the cent on
those rows. Keys holding `-DB` boxes (or `-PCK` packs) diverge: the app values
boxes at the box price (caveat 2), so the figures differ by those rows ($127,892
gross, $102,314 wholesale on 2026-10-01) until the workbook takes the same
change. Use prod for parity: the `- dev (1)` workbook
(`33a989e4-1f42-46b6-8450-ee0650a8102c`) has a stale hardcoded literal in its
margin card, `42549703.46 - Sum([Inventory Value])`, which drifts every time
Dealernet orders land.

## Reference figures

Reproduce these before trusting any change to `queries.py` or `transforms.py`.
**Sigma is the source of truth for the query's figures, not this app.** The
exception is the `-DB` / `-PCK` keys, which the app now values in their own unit
(caveat 2).

> **These are the 2026-09-15 Sigma baseline**, taken before the `-DB` fix. A
> re-baseline against live data after plan 01 is still to do.
>
> The count rows (SKUs, Products, Box types, Priced / not priced, Aging SKUs) are
> the **query's**. The app drops zero-quantity SKUs after the query (caveat 1),
> so its cards read lower on those counts. Every case and dollar figure still
> holds, since the dropped SKUs carry no quantity or value.

| Measure | Value |
|---|---|
| SKUs | 238 |
| Products | 126 |
| Brands (canonical, what the header shows) | 20 |
| Brands (raw Oracle spellings) | 31 |
| Brand buckets | 10 |
| Box types | 15 |
| Cases | 11,292 |
| Inventory value (card + footer) | $4,374,988.145311472 |
| Inventory value (priced only) | $4,100,626.5655157333 |
| Market Value, gross (Wholesale Value card tooltip; = Sigma's Current Market Value KPI) | $65,486,623.8097 |
| Sigma's Unrealized Gross Margin KPI (gross − all inventory; not shown in the app) | $61,111,635.66 |
| Markup chip = footer Markup Multiple (wholesale ÷ priced inventory) | 12.78× |
| Wholesale Value card = footer (×0.8) | $52,389,299.03 |
| Potential Profit card = footer (priced SKUs) | $48,288,672.49 |
| Priced / not priced (Wholesale Value card) | 184 priced / 54 not priced |
| Aging SKUs 0-3 / 3-6 / 6-12 / 12-24 / 24+ | 31 / 50 / 49 / 85 / 23 |

Chart-level references, so a regression in one donut or bar is detectable rather
than hidden inside a matching grand total:

| Chart | Values |
|---|---|
| Aging by cases | 0-3 `1,228` · 3-6 `1,815` · 6-12 `2,894` · 12-24 `3,693` · 24+ `1,662` |
| Aging by inventory value | `550,879.32` · `757,814.32` · `1,191,910.75` · `1,338,493.52` · `535,890.24` |
| Brand bucket by cases | Baseball `5,814` · Basketball `1,799` · Entertainment `866` · Football `866` · Combat `589` · NIL `529` · Other `446` · Soccer `183` · Formula One `180` · Tennis `20` |
| Brand bucket by inventory value | Baseball `1,955,584.05` · Basketball `1,153,271.91` · Football `314,275.38` · Entertainment `296,810.26` · Other `190,362.90` · Combat `189,516.94` · NIL `98,288.73` · Soccer `89,225.18` · Formula One `74,652.19` · Tennis `13,000.60` |

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

The bucket correction of caveat 3b also sits downstream, but it moves two of the
bars. The brand-bucket rows above are Sigma's buckets (`brand_bucket_oracle`),
with `Contact Sports` shown under its app name `Combat` (same figures, since TRB
adds no cases or value). The app's `brand_bucket` moves CHP from `Other` to
`Soccer`, so its bars read Other `91` cases / `23,195.50` and Soccer `538` /
`256,392.58`.

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
- **Component CSS ships separately.** The table, the four charts and the
  drill-down panel render in shadow DOMs, which page styles cannot pierce, so
  `style.TABLE_CSS`, `style.CHART_CSS` and `style.DETAIL_CSS` are injected into
  their components while `style.CSS` handles page chrome. Rules needed on more
  than one side (chips, status pills, design tokens) live in shared blocks.
  Adding a table, chart or panel rule to `_CHROME_CSS` will silently do nothing. Keep each component's inline CSS and JS multi-line:
  CCv2 reads a single-line string holding `/`, `*`, `[` or `]` as a file path and
  then demands an `asset_dir`.
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
  rings vanish silently while their legends stay. The donuts are the page's only
  SVG, and they go out through `interactive.chart`: the component sets its HTML
  via `innerHTML` inside its shadow root, where DOMPurify never runs. Everything
  `style.render` emits stays on `st.html`, the stricter channel, which also
  avoids re-parsing free text as markdown, so keep SVG out of it.
- **No inline event handlers.** The SiS content-security policy forbids
  `onclick` and `eval`. Row and header clicks travel back through the table
  component's `select` and `sort` triggers, and chart clicks through the chart
  component's `pick` trigger, all bound with `addEventListener`.
- **Trigger values are transient and absent until first fired.** Read them with
  `res.get("sort")`, never `res.sort` — attribute access raises on first render.
- **A chart pick is applied on the next run, not where it is clicked.** By the
  time a chart reports a click, its filter's selectbox exists, and writing a
  widget's key after that raises `StreamlitWidgetAlreadyInstantiatedError`. So
  the pick is stashed in `_pending_pick` and applied at the top of the next run,
  before any widget. That rerun fires at the *end* of the script: `st.rerun()`
  counts as a finished run, so Streamlit drops the state of every widget the run
  did not reach, and rerunning from the charts would clear the table search and
  close the drill-down. A header sort defers its rerun to the same place, since
  the drill-down selectbox sits below the table. The same pattern is the safe way
  to write any widget key after it has been drawn.
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
| `interactive.py` | Clickable + sortable table, click-to-filter charts and the self-scrolling drill-down panel via `st.components.v2` |
| `snowflake.yml` | Deployment manifest (container runtime) |
| `.streamlit/config.toml` | Theme tokens matching the HTML palette |
| `vault_inventory_dashboard.html` | Design reference — the authority on appearance |
| `DISCLAIMERS.md` | How the figures are built (moved out of the in-app note) |

## Deliberate departures from the HTML template

| HTML | Here | Why |
|---|---|---|
| `wholesale = dnPrice × qty` | `wholesale_value` `× 0.8` for the KPI cards, the markup chip, the table column, the footer, the brand bars and the margins; gross `market_value` only in the Wholesale Value card's tooltip | The mock predates the validated query and its 0.8 Dealernet factor. The cards tie to the table (caveats 4, 5) |
| `AS OF: Sep 2026` | `As Of` `Live Snapshot` + `Data Pulled` | No as-of dimension exists in the view |
| Bebas Neue + Inter + DM Mono | **Inter only** | Bebas went in `53b8fcd`; DM Mono followed — as the micro-label face it read as a competing typeface beside the native widgets. `font-variant-numeric: tabular-nums` replaces its digit alignment |
| ALL-CAPS labels, wide tracking | **Title Case**, tracking 0 | Requested directly. Every `text-transform: uppercase` is gone and the paired `letter-spacing` was zeroed with it — tracking existed to open up caps. Acronyms (SKUs, DN, CSV, UTC, NIL) and the Oracle brand codes stay upper |
| `.logo` 28px Bebas, muted `/ Dealernet` | 24px Inter **500**, `/ Dealernet` size-only | Unbolded on request; the qualifier now shares the title's face, weight and white |
| `.header-row` centers everything | `.hdr-title-group` baseline-aligns title + freshness | One `align-items` cannot serve both a 24px title and the two-line `.hdr-meta` stack |
| 12-row pagination | Fixed 25-row scroll cap, measured in the browser | The template's own comments specify this for the port |
| `onclick` sortable headers | `data-sort` + component trigger | Same behaviour; SiS forbids inline handlers |
| `exportTable()` alert stub | `st.download_button` | The template flags it as a stub for the port |
| Sticky full-bleed `<header>` | Rounded header card | Streamlit owns the scroll container |


To deploy:

```bash
snow streamlit deploy vault_inventory_dash --replace --role POWER_ANALYST_ORACLE_PROD
```