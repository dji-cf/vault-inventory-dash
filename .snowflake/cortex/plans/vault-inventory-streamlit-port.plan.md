# Plan: Vault Inventory Dashboard — HTML → Streamlit-in-Snowflake

## Context established

`vault_inventory_dashboard.html` was authored as a **port spec**, not just a mockup. Its comments name the target module layout (`relic_inventory_dash/style.py`, `charts.py`, `transforms.py`), keep class names identical so the CSS can be adapted rather than rewritten, and pin the mock data to real workbook figures.

The sibling project `C:\Users\dji\dashboards\relic_inventory_dash` supplies proven infrastructure on this exact account: SPCS/local connection detection, a CCv2 clickable-table component, scoped-CSS conventions, and a working container-runtime manifest.

**The query validates and reproduces every figure in the HTML's comment block:**

| Measure | Value |
|---|---|
| SKUs (`item_number`) | 238 |
| Products (`product_name`) | 126 |
| Brands (raw `brand`) | 31 |
| Brand buckets | 10 |
| Box types | 15 |
| Cases | 11,292 |
| Inventory valuation | $4,374,988.15 |
| Market value (×0.8) | $52,391,717.19 |
| Unrealized gross margin | $48,016,729.04 |
| Blended markup (priced only) | 12.78× |
| Mapping | 184 Mapped / 54 No Price |
| Aging (0-3 / 3-6 / 6-12 / 12-24 / 24+) | 31 / 50 / 49 / 85 / 23 |

**All 6 KPI cards are derivable from the query — no KPI consult needed.** Mapping of the HTML's `renderStats()` to query columns:

1. `# of Products` → `COUNT(DISTINCT product_name)`; sub = distinct `brand_bucket`
2. `# of SKUs` → `COUNT(DISTINCT item_number)`; sub = distinct `box_type`
3. `# of Cases` → `SUM(quantity_cases)`
4. `Inventory Valuation` → `SUM(inventory_value)`
5. `Current Market Value` → `SUM(wholesale_value)`; sub = count of priced SKUs
6. `Unrealized Gross Margin` → `SUM(wholesale_value) − SUM(inventory_value)`; markup chip = `SUM(wholesale)/SUM(inventory)` over **priced rows only**

Account facts verified: `PYPI_ACCESS_INTEGRATION` exists · `DEFAULT_STREAMLIT_COMPUTE_POOL = SYSTEM_COMPUTE_POOL_CPU` · snow CLI 3.21.0 (≥3.14) · `VAULT_INVENTORY_V` is SCD2 with no as-of dimension (16 columns; only `START_DATE`/`END_DATE`).

## Decisions confirmed with the user

1. **Deploy target** — local `streamlit run` + a container-runtime `snowflake.yml` for `ORACLE_DATA_PROD.SANDBOX.VAULT_INVENTORY_DASH`. Manifest prepared; **deploy held for explicit approval**.
2. **AS OF header** — replaced with `LIVE SNAPSHOT` + a `DATA PULLED` field (relative age + absolute-timestamp tooltip), reusing relic's `freshness_label`. The view has no as-of dimension, so the HTML's "Sep 2026" cannot be honestly reproduced.
3. **Zero/negative-qty SKUs** — all 238 rows retained for Sigma parity, with a UI caption noting the 36 SKUs with no positive on-hand quantity.
4. **Margin headline** — query formulas used verbatim; the markup skew is surfaced in the UI rather than silently smoothed.

## File layout

```
c:\Users\dji\dashboards\vault-inventory-dash\
  streamlit_app.py                    # layout, state, filters, drill, export
  queries.py                          # INVENTORY_SQL (the validated query)
  data.py                             # st.connection + cached loader
  transforms.py                       # formatters, filters, KPIs, aggregation
  style.py                            # scoped CSS + all HTML/SVG builders
  interactive.py                      # CCv2 clickable + sortable table
  pyproject.toml
  snowflake.yml
  .streamlit/config.toml
  .gitignore
  README.md
  vault_inventory_dashboard.html      # kept as the design reference
```

Two deliberate omissions from the relic layout: **no `agent.py`** (the HTML has no assistant panel) and **no `charts.py`** — the donut-with-itemized-legend and label/track/value hbars are hand-rolled SVG/CSS in the HTML, and porting them as Python builders in `style.py` is more faithful than approximating them in Altair. This also drops the `altair` dependency.

## Step 1 — Scaffold + `queries.py`

`queries.py` holds `INVENTORY_SQL` — the user's query **verbatim**, including the 76-row `brand_mapping` VALUES list and the trailing `ORDER BY` (harmless; gives a stable default order). No parameters: the query takes no inputs, so there is nothing to bind.

`pyproject.toml`: `streamlit>=1.57`, `snowflake-snowpark-python`, `snowflake-connector-python`, `pandas>=2.0`, `openpyxl>=3.1`, `tzdata`. Flat-layout `py-modules` declared explicitly so `pip install -e .` doesn't fail auto-discovery.

`.streamlit/config.toml`: adapted from relic's navy/gold theme, retinted to this HTML's tokens — `primaryColor #4d7ab8`, `backgroundColor #f0f2f5`, `textColor #1a2b4a`, `borderColor #e2e8f0`, and the aging ramp in `chartCategoricalColors`.

## Step 2 — `data.py`

Port relic's connection layer, which is already proven on this account:

- `_running_in_snowflake()` — `/snowflake/session/token` probe + `get_active_session()` fallback
- `_spcs_connection_kwargs()` — injected OAuth token path for a standalone SPCS service
- `_connection()` — `@st.cache_resource`, `st.connection("snowflake", type="snowflake")`, then `USE WAREHOUSE`
- `SNOWFLAKE_DEFAULT_CONNECTION_NAME` set **only when not hosted** (setting it inside SiS makes the connector search for a name that doesn't exist)

**Deliberate deviation from the skill's guidance:** the skill recommends `os.getenv("SNOWFLAKE_DEFAULT_CONNECTION_NAME") or "default"`. This machine has no connection named `default`, so that literal would break local runs. Default to `FANATICS_COLLECTIBLES_PROD` (as relic does) behind the not-hosted guard, and document the env override.

`load_inventory() -> tuple[pd.DataFrame, datetime]`, `@st.cache_data(ttl=2h)`:
- lowercase columns; `pd.to_numeric` on every measure (Snowflake returns `Decimal`)
- `aging_bucket` → ordered `Categorical` in the HTML's order so charts/filters sort correctly and empty buckets stay visible as zero rows
- `pulled_at` captured **inside** the cached body, so a cache hit keeps the original pull time — a real freshness stamp, not a render clock

Single loader, no month selector: the data is a live snapshot.

## Step 3 — `transforms.py`

Formatters ported to match the HTML's JS **output-for-output**, including its asymmetries (`fmt_abbr` switches to K at 1e3; `fmtq_abbr` at 1e4):

`fmt` · `fmt_abbr` · `fmtq` · `fmtq_abbr` · `fmt_pct` · `fmt_mult` · `fmt_date` — all `None`/NaN → `—`.

Ordered categories and colors ported verbatim: `AGING_ORDER`, `AGING_COLOR`, `BRAND_ORDER`, `LINE_PALETTE`, `OTHER_GRAY`, `brand_color()` (index into the palette by workbook order so a bucket keeps its color under any filter; `Other` → gray).

Functions:
- `apply_filters(df, *, mapping, search, brand_bucket, aging, street_year, box_type, price_source)` — mirrors `filteredRows()`; search matches `product_name` or `item_number`
- `stat_cards(df)` — the 6 KPIs. Reproduces the HTML's deliberate asymmetry: margin nets market value of **priced** SKUs against valuation of **all** SKUs, while the markup chip uses priced rows for both numerator and denominator
- `header_meta(df)` — skus / brands / total value / mapped / no-price counts
- `aging_composition(df, value_col)` / `brand_composition(df, value_col)` — chart row sets
- `filter_options(df)` — the 5 dropdown lists in the HTML's specified order
- `table_totals(df)` — footer totals; **ratios recomputed from summed additive columns**, never averaged (`margin_pct = Σprofit / Σwholesale`, mirroring `footMarginPct`)
- `nonpositive_qty_count(df)` — drives the agreed caption
- `to_excel(df)` — ported from relic, openpyxl with a CSV fallback

## Step 4 — `style.py` CSS

Port the HTML's `<style>` block with two structural changes:

**Rescoping.** Every bare selector (`body`, `header`, `main`, `table`, `thead th`, `td`, `tbody tr`, `.chip`, …) gets a `.fct` prefix so it cannot collide with Streamlit's DOM. `:root` variables move to `.fct { … }`. All 30 tokens carry over unchanged, including the aging ramp and the six column-band tints. `position: sticky` on `header` is dropped — Streamlit owns the scroll container — and the header becomes a card, as in relic.

**Splitting.** `CSS` (page chrome) and `TABLE_CSS` ship separately, because page styles cannot pierce the CCv2 component's shadow root:
- `CSS = _BASE_CSS + _CHROME_CSS` — header, hdr-meta, context bar, stat cards, legend, section labels, chart-wrap, donut, hbars, detail panel
- `TABLE_CSS = _BASE_CSS + _TABLE_CSS` — header bands, td variants, chips, mix-bar, pinned first column, `.scrollable`, tfoot

Fonts: `Bebas Neue` + `DM Mono` + `Inter` declared in `config.toml` and `@import`ed into the injected CSS. Relic already loads a `fonts.googleapis.com` URL on this same runtime, so this is proven here; if it were ever blocked, only micro-label typography degrades to system fallbacks — no layout break. (The HTML's own comment notes the source template referenced DM Mono 37 times without ever fetching it; this port actually loads it.)

## Step 5 — `style.py` builders

- `inject_css()` · `open_fct()` · `close_fct()`
- `freshness_label()` / `_rel_age()` — ported verbatim from relic, pinned to `America/New_York` via `DASHBOARD_TZ`
- `header_html(meta, pulled_at)` — `Vault Inventory / Dealernet`, LIVE SNAPSHOT + DATA PULLED, SKUs / Brands / Total Value, mapping note
- `context_bar_html` · `legend_html` · `section_label_html`
- `stat_cards_html(cards)` — 6 cards in Sigma's order with the exact card classes and value colors
- `donut_html(rows, fmt_fn, center_label)` — ports `donutSvg` + `donutLegend`. **Negative-value guard:** arc geometry uses the sum of *positive* values only (a negative `stroke-dasharray` renders nothing and would corrupt the cumulative offset), while the center figure shows the true net total and the legend lists every bucket at its real value
- `hbars_html(rows, fmt_fn)` — ports `hbars`. **Negative-value guard:** width from `abs(value) / max(abs(values))`, negative bars tinted `--neg`
- `GROUPS` — the column spec: 7 groups, 22 columns, Sigma's order verbatim, each column carrying `(key, header, td_css, sort_type, cell_fn, total_fn)`. One definition drives the two-row header, body, and footer, exactly as in the HTML
- `product_table_html(df, totals, selected, sort_col, sort_asc)` — banded two-row header with sort arrows and `data-sort` attributes; rows carry `data-key` = `item_number`; footer reads `TOTAL (n SKUs)`
- Cell builders ported verbatim: `mix_bar` (cost/margin split per case), `aging_chip`, `price_source_pill`, `signed`, `null_cell`
- `detail_panel_html(row)` — the 12-cell drill-down panel

## Step 6 — `interactive.py`

Port relic's CCv2 component (shadow DOM, inline HTML/CSS/JS only — the one form SiS supports), then **extend it** so the HTML's sortable headers survive:

```js
mount.querySelectorAll('thead th[data-sort]').forEach((th) => {
  th.addEventListener('click', () => setTriggerValue('sort', th.getAttribute('data-sort')));
});
```

Signature becomes `table(html, *, key, scroll=False, max_height=None) -> tuple[str | None, str | None]` returning `(selected, sort_col)`. Both are transient triggers — non-`None` only on the run caused by the click.

## Step 7 — `streamlit_app.py`

Order of operations:

1. `set_page_config(layout="wide")` → `style.inject_css()`
2. `df_all, pulled_at = data.load_inventory()`
3. Session-state `setdefault`s: `mapping`, `sort_col='inventory_value'`, `sort_asc=False`, `selected_item`, `rows=25`, `f_search`, the 5 `f_*` filter keys, and `_mapping_last` for `_sticky`
4. **Stale-option guard** before instantiating widgets — a filter value that vanished between refreshes is reset to `''`, otherwise Streamlit raises on a keyed selectbox whose session value isn't in `options`
5. Top row: mapping `st.segmented_control` (ALL / MAPPED / NO PRICE) with relic's `_sticky` `on_change` so clicking the active segment can't blank it, plus a `↻ Refresh` button (`cache_data.clear()` + `rerun()`)
6. Filter bar: `st.text_input` + 5 `st.selectbox` (single-select, matching the HTML) + `✕ Clear filters`
7. `apply_filters` → `stat_cards` → `header_meta`; render chrome in one `st.html`
8. The two agreed notes: the non-positive-qty caption, and a markup-concentration note on the margin card
9. AGING COMPOSITION — legend + two donuts in `st.columns(2)`
10. INVENTORY BY BRAND — two hbar blocks in `st.columns(2)`
11. PRODUCT DETAIL — action bar (sort-by selectbox, asc/desc, rows-per-view, `⬇ Export XLS`), then the table
12. Table round-trip: handle the sort trigger (toggle direction when the same column is re-clicked) and the row trigger (toggle-to-close), then `st.rerun()`. Selection is owned by a real `st.selectbox` keyed `selected_item`, with the component as a second input to the same key — relic's pattern, which gives a keyboard-accessible fallback for free
13. Detail panel via `st.html` when a row is selected

Sorting runs in pandas with `na_position='last'`, matching the HTML's "nulls always sort last, whichever direction the column is going".

## Step 8 — Local verification

`python -m venv .venv` + `pip install -e .` (note: `uv` is not on PATH on this machine), then `python -c "import streamlit_app"` as a cheap import check, then `streamlit run`.

Reconcile against the validated figures in the table above — all 6 KPIs, the header meta, the mapping split, and both chart distributions. Any mismatch is a port bug, since the SQL is already confirmed.

## Step 9 — Manifest, README, pre-flight

`snowflake.yml` — `definition_version: 2`, `ORACLE_DATA_PROD.SANDBOX.VAULT_INVENTORY_DASH`, `runtime_name: SYSTEM$ST_CONTAINER_RUNTIME_PY3_11`, `compute_pool: SYSTEM_COMPUTE_POOL_CPU`, `query_warehouse: ANALYTICS_WAREHOUSE`, `external_access_integrations: [PYPI_ACCESS_INTEGRATION]` (required because `pyproject.toml` is in artifacts), and all 9 artifact paths listed.

Container runtime is required, not preferred: `interactive.py` uses `st.components.v2`, which needs Streamlit ≥1.51, above the warehouse runtime's ~1.52 ceiling for the rest of the feature set.

Run the pre-flight artifact check — `snow streamlit deploy` does not verify that artifact paths exist, and a missing one uploads as a zero-byte stage entry that kills the app on first import.

README documents the data model, the ×0.8 wholesale factor, the local run command, the deploy command with `--role POWER_ANALYST_ORACLE_PROD`, and the gotchas below.

**Then stop and confirm before deploying.**

## Fidelity deltas from the HTML — explicit

| # | HTML | Port | Why |
|---|---|---|---|
| 1 | `wholesale = dnPrice × qty` | `× 0.8` factor | The query is the validated logic; the mock predates it |
| 2 | `AS OF: Sep 2026` | LIVE SNAPSHOT + DATA PULLED | No as-of dimension exists in the view |
| 3 | 12-row pagination | Scroll-cap + rows-per-view | The HTML's own comment says the port ships sticky-scroll instead |
| 4 | `onclick` sortable headers | `data-sort` + CCv2 trigger | Same behavior, no inline handlers (SiS CSP) |
| 5 | `exportTable()` alert stub | `st.download_button` | The HTML flags this as a stub for the port |
| 6 | All-positive mock data | 36 non-positive rows retained | Sigma parity, with chart clamping + caption |

## Known risks

- **Markup skew is real and unresolved.** `Sapphire`/`Delight` box types show 40–99× markups (2025/26 NBA Bowman Sapphire: $266 Oracle cost vs $27,241 DN case price). This looks like a per-box vs per-case unit mismatch upstream and it dominates KPIs 5 and 6. Building as-is per your decision; worth a separate investigation.
- **`brand_bucket` COALESCEs unmapped brands to `'Other'`**, so `Other` mixes explicitly-mapped brands with unmapped ones. The header's brand count uses raw `brand` (31), which is unaffected. Flagged because the sibling relic dashboard was bitten by exactly this kind of `'OTHER'` sentinel inflating a headline count.
- **Google Fonts reachability** from the SiS container — proven for relic on this runtime; degrades gracefully if it ever changes.
