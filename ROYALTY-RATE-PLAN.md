# Plan: add effective royalty rate by brand to the Vault Inventory profit calculation

Handoff document for an implementing agent. Research was completed and verified
live against Snowflake account `VXB09319` on **2026-09-24** using role
`POWER_ANALYST_ORACLE_PROD` / warehouse `ANALYTICS_WAREHOUSE`. Every figure and
every SQL snippet below was executed, not inferred.

Read `README.md` first. This plan assumes its conventions and repeatedly depends
on them.

---

## 1. Objective

The dashboard's margin columns (`total_potential_profit`, `margin_dollars_per_case`,
`markup_multiple`, `margin_pct`) are **pre-royalty**. Add a per-brand effective
royalty rate so the table can show profit net of royalty.

Expected effect, measured at today's snapshot:

| Measure | Value |
|---|---|
| Wholesale value (basis) | $52,338,119.01 |
| Potential profit today (pre-royalty) | $47,884,332.20 |
| Royalty cost | **$11,070,124.73** |
| Blended effective rate | **21.41%** |
| Potential profit after royalty | **$36,814,207.47** |

A ~23% reduction in headline potential profit. Material, and worth doing.

---

## 2. Research verdict — do not re-investigate these

### The source to use

`ORACLE_DATA_PROD.FCT_EPM.CARDPLN_PL_BY_LEAGUE_V`, with the rate derived as
`ACX_Royalties ÷ ACX_Net Revenue` grouped by `LEAGUE`. This is the Physical Cards
P&L — the same business domain as sealed wax vault inventory.

### Confirmed dead ends — do not pursue

| Candidate | Why it fails |
|---|---|
| `FC_DATA_PROD.DATA_MART.DIM_COLLECT_ROYALTIES` | Flat **1.5% / 1.5%** for every partner and every sport (its own column comment says "constant in model"). Zero brand variation. Also the wrong domain — Collect marketplace vault for graded singles, not sealed wax. |
| `FC_DATA_PROD.STAGING.PRODUCT_ROYALTY_BEARING_V2` | Useful `BRAND_CODE` / `ROYALTY_PARTNER` mapping but **no rate column at all**. |
| `DESA_SILVER.PRICING.SKU` | 45 columns, none royalty-related. |
| `SNOWFLAKE.ACCOUNT_USAGE.COLUMNS` | Not authorized for this role — use per-database `INFORMATION_SCHEMA` instead. |

### The double-counting risk is ruled out — settled, do not re-derive

`ACX_Royalties` is a **child of `ACX_Cost of Goods Sold`** (`SECTION = COGS`,
`INDENT_LEVEL = 2`, siblings: Manufacturing, Autos & Relics, MG Shortfall). That
raises the obvious danger that Oracle's `UNIT_COST` already capitalizes royalty
into inventory, which would make subtracting it a double count. **It does not.**

Two independent confirmations:

1. **Metadata.** `ORACLE_DATA_PROD.FCT_CST.CST_COST_ELEMENTS_VL` has exactly
   **12 rows** and none is royalty: Manufactured Relics, Sketch, Auto Sticker,
   Auto On-Card, Relic, BoardStock, Generic Packaging, Printing and Packout,
   Product Development, Labor, Overhead, Direct Material.
2. **Row level.** For `FGC006461-CSE` the published standard cost decomposes as
   Auto On-Card `82.6124994281` + Auto Sticker `10.1488526741` + Printing and
   Packout `197.6831113385` = **`290.4444634407`**, which is exactly the unit cost
   the README records for that SKU. No residual, so royalty is not hidden inside
   "Overhead".

Conclusion: the dashboard's margin has always been pre-royalty, and subtracting
royalty is additive rather than a double count.

---

## 3. Prerequisite — re-baseline the README before touching anything

The README's reference figures have **drifted** and are no longer reproducible.
Verified by running the app's own `queries.INVENTORY_SQL` unmodified:

| Measure | README (2026-09-15) | Actual (2026-09-24) |
|---|---|---|
| SKUs | 238 | **242** |
| Cases | 11,292 | **11,361** |
| Inventory valuation | $4,374,988.145311472 | **$4,453,786.804691915800** |
| Mapped SKUs | 184 | **183** |
| Market value (gross) | $65,486,623.8097 | **$65,422,648.7608724** |

This is live-snapshot movement (`VAULT_INVENTORY_V` is SCD2 pinned to the open
record with no as-of dimension), **not** a regression. But it falsifies the
README's claim that "the counts and the valuation should hold."

**Task 0:** re-run the reconciliation, refresh the README's reference-figures
table, and note that SKU count and valuation *do* drift. Do this **first and as a
separate commit**, so the royalty work is not blamed for the delta.

---

## 4. Architecture decision

**Add the rate app-side as a second cached query merged in pandas. Do NOT modify
`queries.INVENTORY_SQL`.**

Rationale — this follows the repo's own established precedent. README caveat 3b
says of the brand merge: *"This is deliberately an app-layer step, not a
`queries.py` change — the SQL stays reconciled to Sigma and its own 31-brand
figure stays true."* The same reasoning applies here. Keeping `INVENTORY_SQL`
byte-for-byte Sigma-reconciled means every existing reference figure stays valid
and the royalty feature cannot be the cause of a future Sigma mismatch.

Rejected alternative: inlining a `league_mapping` VALUES CTE plus a rates CTE
into `INVENTORY_SQL`. It is precedented by `brand_mapping`, but that mapping was
part of the original Sigma-validated statement. Adding a join to `FCT_EPM` there
introduces fanout risk into the one statement the repo treats as sacred, for no
benefit.

**Invariant to enforce either way:** the rates frame must be **exactly one row
per league**. A `LEFT JOIN` / `merge` against a multi-row rate table would fan out
the SKU grain and silently inflate every total. Assert row count before and after
the merge.

---

## 5. Decisions needing David's sign-off

Implement the **Default** column unless told otherwise. Do not silently choose
differently; each of these changes published numbers.

| # | Decision | Default | Notes |
|---|---|---|---|
| D1 | Rate vintage | **`AUG26RF`** (latest full-year forecast) | FY26 `ACTUAL` is partial-year, so its rate sits on an incomplete revenue base and is noisier — NFL reads 26.04% actual vs 24.38% forecast, UEFA 18.27% vs 14.64%, Club Exclusives 14.73% vs 7.43%. Make it a one-line module constant. |
| D2 | Include `ACX_MG Shortfall`? | **No** | MG shortfall is a lumpy period true-up, not a per-unit rate, and it can be **negative**. Including it swings Bundesliga 15.00% → 29.22%, EPL 22.43% → 16.89%, Club Exclusives 7.43% → 9.15%. Large leagues are unaffected (NULL or ~0). Leave a documented one-line switch. |
| D3 | The 10 unmapped SKUs ($70,756, 1.59% of inventory value) | **Leave NULL** | Mirrors how unpriced SKUs are handled — em dash, never 0. Do **not** apply a blended fallback silently. Surface the count in the UI. Unmapped: `TRB`, `League Collectors Kit`, `SpongeBob`, `Pixar`, `NCAA - Basketball`, `MCD`, `VFR`. |
| D3b | Optional extra mappings | **Do not add** without approval | `Pixar → Disney` (Disney-owned) and `NCAA - Basketball` / `MCD → NIL` are defensible. `SpongeBob`, `VFR` (VeeFriends) and `TRB` (Top Rank Boxing) have no EPM league at all. |
| D4 | Add a 7th KPI card? | **No** | `vault_inventory_dashboard.html` is the layout authority and has 6 cards. Keep royalty in the table, footer, drill-down and export. If a KPI is later wanted, note the basis trap in §8. |
| D5 | Add an `epm_league` filter dropdown? | **No** | The HTML specifies five dropdowns. Optional 6th only on request. |

---

## 6. Verified SQL — use as-is

### 6a. The rate query (one row per league)

```sql
SELECT
    LEAGUE                                                          AS epm_league,
    SUM(CASE WHEN PL_LINE = 'ACX_Royalties'   THEN AMOUNT END)
      / NULLIF(SUM(CASE WHEN PL_LINE = 'ACX_Net Revenue' THEN AMOUNT END), 0)
                                                                    AS royalty_rate,
    SUM(CASE WHEN PL_LINE = 'ACX_Net Revenue' THEN AMOUNT END)      AS epm_net_revenue
FROM ORACLE_DATA_PROD.FCT_EPM.CARDPLN_PL_BY_LEAGUE_V
WHERE FISCAL_YEAR   = 'FY26'
  AND PERIOD_TYPE   = 'YEAR'
  AND LOB           = 'LB_302'          -- North America leaf; see §8
  AND FORECAST_ASOF = 'AUG26RF'         -- D1; see the vintage trap in §8
  AND PRODUCT_GROUP NOT IN ('PG_10000', 'PG_50000')   -- rollup parents
GROUP BY LEAGUE
HAVING SUM(CASE WHEN PL_LINE = 'ACX_Net Revenue' THEN AMOUNT END) > 0
```

`HAVING ... > 0` drops `OEB` and `UEFA Euro`, which carry tiny negative revenue
and no royalty line, and would otherwise yield a garbage rate.

**Every one of those four filters is mandatory.** Omitting `FORECAST_ASOF` alone
sums 11 scenario/vintage combinations and inflates Baseball net revenue from
$1.28B to $12.3B, producing a plausible-looking but wrong rate.

### 6b. Expected output at `AUG26RF` (17 leagues)

| League | Rate | League | Rate |
|---|---|---|---|
| NFL | 24.38% | UFC | 16.38% |
| NBA | 23.53% | Formula 1 | 15.17% |
| EPL | 22.43% | Bundesliga | 15.00% |
| Baseball | 21.22% | Tennis | 9.91% |
| MLS | 20.71% | Club Exclusives | 7.43% |
| Marvel | 18.02% | NIL | 7.15% |
| Disney | 17.76% | GPK | 0.51% |
| WWE | 16.93% | UEFA | 14.64% |
| Star Wars | 16.57% | | |

### 6c. Brand → EPM league map

Keyed on the **canonical** brand produced by `transforms.canonical_brand`
(i.e. post-`BRAND_CANON`), so only the acronym form needs an entry. Add to
`transforms.py` next to `BRAND_CANON`:

```python
# Canonical brand -> LEAGUE in FCT_EPM.CARDPLN_PL_BY_LEAGUE_V. Keyed on the
# post-BRAND_CANON value, so only the acronym form appears. Brands absent here
# have no EPM league and deliberately carry a NULL royalty rate (README-style
# em dash), never a zero or a blended fallback.
EPM_LEAGUE = {
    "MLB": "Baseball",          # EPM names this product group 'Baseball', not 'MLB'
    "NBA": "NBA",
    "NFL": "NFL",
    "CHP": "UEFA",              # UEFA Champions League
    "MRV": "Marvel",
    "WWE": "WWE",
    "DIS": "Disney",
    "UFC": "UFC",
    "FOR": "Formula 1",
    "NIL": "NIL",
    "STW": "Star Wars",
    "TEN": "Tennis",
    "English Premier League": "EPL",   # no acronym pair exists; verbatim
}
```

Note `English Premier League` is **not** in `BRAND_CANON` (no second spelling
exists in the view's open records), so it passes through verbatim and must be
keyed as the full string.

### 6d. Coverage this achieves

**232 of 242 SKUs — 98.41% of inventory value.**

| EPM league | Vault brand | SKUs | Inventory value |
|---|---|---|---|
| Baseball | MLB | 80 | $1,955,778.66 |
| NBA | NBA | 37 | $1,174,866.79 |
| NFL | NFL | 31 | $314,275.38 |
| UEFA | CHP | 21 | $246,381.29 |
| Marvel | MRV | 17 | $123,939.24 |
| WWE | WWE | 10 | $112,333.24 |
| Disney | DIS | 12 | $107,455.53 |
| UFC | UFC | 5 | $77,183.70 |
| Formula 1 | FOR | 3 | $74,652.19 |
| NIL | NIL | 4 | $67,358.72 |
| Star Wars | STW | 7 | $66,126.03 |
| EPL | English Premier League | 3 | $49,679.48 |
| Tennis | TEN | 2 | $13,000.60 |
| *(none)* | TRB, League Collectors Kit, SpongeBob, Pixar, NCAA - Basketball, MCD, VFR | 10 | $70,755.95 |

---

## 7. Implementation steps

### Step 1 — `data.py`: load the rates

Add a second cached loader beside `load_inventory`, reusing `_connection()` and
`_TTL`. Keep it a **separate** `st.cache_data` function so the rate is
independently cacheable and inspectable.

```python
@st.cache_data(ttl=_TTL, show_spinner="Loading royalty rates…")
def load_royalty_rates() -> pd.DataFrame:
    df = _connection().query(queries.ROYALTY_RATE_SQL, ttl=_TTL)
    df.columns = [c.lower() for c in df.columns]
    df["royalty_rate"] = pd.to_numeric(df["royalty_rate"], errors="coerce")
    return df
```

Put `ROYALTY_RATE_SQL` (§6a) in `queries.py` as a **new module-level constant**.
Do not touch `INVENTORY_SQL`.

### Step 2 — `data.py`: derive the columns inside `load_inventory`

Apply **after** the `canonical_brand` fold at `data.py:217` and **before** the
final `sort_values`, so the map keys match the canonical brand.

Assert the grain both sides of the merge:

```python
rates = load_royalty_rates()
assert rates["epm_league"].is_unique, "royalty rates must be one row per league"

df["epm_league"] = df["brand"].map(tx.EPM_LEAGUE)
before = len(df)
df = df.merge(rates[["epm_league", "royalty_rate"]], on="epm_league", how="left")
assert len(df) == before, "royalty-rate merge changed the SKU grain"

# Royalty rides the WHOLESALE basis, matching every other margin measure in the
# table. Left NULL where there is no league or no price, exactly like the other
# ratio columns -- NULL means "unknown", which must render as an em dash.
df["royalty_cost"] = df["wholesale_value"] * df["royalty_rate"]
df["profit_after_royalty"] = df["total_potential_profit"] - df["royalty_cost"]
df["margin_pct_after_royalty"] = (
    df["profit_after_royalty"] / df["wholesale_value"].replace(0.0, pd.NA)
)
```

Do **not** add the new numeric columns to the `fillna(0.0)` loop at
`data.py:188` — that loop is only for additive columns whose NULL would poison
sums. `royalty_cost` NULL means "no rate known" and must stay NULL.

### Step 3 — `transforms.py`: totals

- Add `EPM_LEAGUE` (§6c).
- Extend `_SUMMABLE` (line 444) with `"royalty_cost"` and `"profit_after_royalty"`.
- In `table_totals` (line 448), add the post-royalty ratio **recomputed from the
  summed columns**, never averaged:

```python
totals["margin_pct_after_royalty"] = (
    (totals.get("profit_after_royalty", 0.0) / ws) if ws else None
)
```

This is the README's "ratios are never averaged" rule. A per-row average of
post-royalty margin would weight a 1-case SKU like a 1,000-case one.

- Add a helper for the caption, e.g. `unmapped_league_count(df)`, mirroring
  `nonpositive_qty_count`.

### Step 4 — `transforms.py`: export

Append to `_EXPORT_COLS` (line 475), after `("markup_multiple", "Markup Multiple")`
so the export keeps mirroring on-screen order:

```python
("epm_league", "EPM League"),
("royalty_rate", "Royalty Rate"),
("royalty_cost", "Royalty Cost"),
("profit_after_royalty", "Profit After Royalty"),
("margin_pct_after_royalty", "Margin % After Royalty"),
```

### Step 5 — `style.py`: the table band

Add an 8th group to `GROUPS` (line 1065), positioned **after** `Margin` and
before `Dealernet Match`:

```python
("&#9670; Royalty", "th-royalty", [
    _col("royalty_rate", "Royalty Rate", "td-muted", "num",
         _num_cell("royalty_rate", tx.fmt_pct)),
    _col("royalty_cost", "Royalty Cost", "", "num",
         lambda r: _signed(r["royalty_cost"], tx.fmt),
         _sum_total("royalty_cost", tx.fmt)),
    _col("profit_after_royalty", "Profit After Royalty", "td-total", "num",
         lambda r: _signed(r["profit_after_royalty"], tx.fmt),
         _sum_total("profit_after_royalty", tx.fmt)),
]),
```

`COLUMNS`, `COLUMN_BY_KEY` and `SORT_OPTIONS` derive from `GROUPS`, so sorting
comes free. This takes the table from 22 to 25 columns.

Add a `th-royalty` rule to **`_TABLE_CSS`** (line 384), not `_CHROME_CSS`. Per the
README, the table renders in a shadow DOM that page styles cannot pierce — a
table rule added to `_CHROME_CSS` silently does nothing. Follow the existing
`th-margin` / `th-pricing` band colours.

> **Never write a `<` character into any CSS string, including inside a comment.**
> `style._checked()` exists to catch this and will raise at import. One `<header>`
> in a prose comment deletes the entire stylesheet via DOMPurify's `SAFE_FOR_XML`
> guard, and the dashboard renders as naked HTML with no error anywhere.

### Step 6 — `style.py`: drill-down

`detail_panel_html` (line 1187) is a 12-field panel. Add `Royalty Rate`,
`Royalty Cost` and `Profit After Royalty`. Check the panel's grid still balances
at 15 fields; adjust the column count rather than letting one field orphan on a
final row.

### Step 7 — `streamlit_app.py`: caption

Add a caption near the existing markup caveat, active whenever
`unmapped_league_count(df) > 0`, stating how many SKUs and how much value carry
no royalty rate. Also state the basis plainly — see §8.

---

## 8. Gotchas specific to this feature

**The vintage constant cannot be derived with `MAX()`.** `FORECAST_ASOF` values
are month-prefixed strings (`JAN26RF`, `FEB26RF`, … `AUG26RF`, plus
`ROLLING_FORECAST`). Alphabetical `MAX()` returns `MAY26RF`, which is **not** the
latest. There is no `SEP26RF` as of 2026-09-24. Pin the constant explicitly and
add a startup assertion that the pinned vintage still exists, so a stale pin
fails loudly instead of silently returning an empty rate frame and NULLing every
royalty column.

**The basis is a proxy, and the UI must say so.** The rate is royalty as a
percentage of *Topps' first-sale net revenue*, applied to a *Dealernet
distributor resale* price. These are different bases. It is a defensible
directional proxy, but it is **not** the contractual royalty owed on this
inventory. Label the column and caption as an *EPM effective rate*. Do not
present it as a royalty liability.

**`LOB = 'LB_302'` is North America only.** Per prior work on this view,
`Total LOB` is **not** the sum of the leaf LOBs (5,063.7 vs 4,785.6 for
NA+Intl+Digital — a $278M gap), so do not switch to `Total LOB` for a
"complete" rate. The vault is NA inventory; `LB_302` is correct.

**Do not create a third value basis.** The repo already runs two on purpose:
KPIs read gross `market_value`, the table reads `wholesale_value` (×0.8). Royalty
is applied to `wholesale_value` only, consistent with every other margin measure
in the table. If D4 is ever revisited and a KPI is added, it must state which
basis it uses; mixing them is the exact error the README's caveat 5 documents
(it understated two KPIs by 20% until 2026-09-15).

**Cost-element tables fan out.** If you go anywhere near
`FUSION.CST_STD_COST_DETAILS_V`, note that joining it to `EGP_SYSTEM_ITEMS_VL`
produces heavily duplicated rows across cost books / orgs / scenarios. Dedupe
before aggregating. Not needed for this feature — listed only so the §2 evidence
can be reproduced.

**`brand_bucket` stays untouched.** It is keyed on the **raw** Oracle brand in
SQL and is bit-for-bit reconciled to Sigma. The royalty work keys on the
canonical brand instead. Do not re-derive `brand_bucket` from either.

---

## 9. Verification gates

All must pass before deploy.

1. **Grain preserved.** SKU row count identical before and after the merge
   (242 today). The two asserts in Step 2 cover this.
2. **Rate frame is one row per league** — 17 rows at `AUG26RF`.
3. **Existing reference figures unchanged.** Because this is app-layer and
   `INVENTORY_SQL` is untouched, every figure in the refreshed README table must
   be bit-for-bit identical. Any movement means something leaked into a shared
   column.
4. **Coverage:** 232 of 242 SKUs, 98.41% of inventory value, 10 SKUs NULL.
5. **Totals reproduce** (at `AUG26RF`, today's snapshot):
   - `Σ royalty_cost` = **$11,070,124.73**
   - `Σ profit_after_royalty` = **$36,814,207.47**
   - blended rate = **21.41%**
6. **Footer ratio is recomputed, not averaged.** Assert
   `margin_pct_after_royalty == Σprofit_after_royalty / Σwholesale_value`.
   A naive row-average is a known ~5pt error in this repo.
7. **Unmapped rows render as em dashes**, never `0%` or `$0.00`.
8. **CSS survived.** `style._checked()` raises at import if not. Confirm the
   donut rings and the new band header both render — a stripped stylesheet shows
   as naked HTML with no error.
9. **Pinned vintage exists** — assertion from §8 fires on a stale pin.

These dollar figures drift as Dealernet orders land and as Oracle inventory
moves. Re-measure rather than treating them as permanent constants; the stable
gates are 1–4 and 6–9.

---

## 10. Deploy

No manifest change is needed — no new module is added. Permissions are already
proven: the research above ran as `POWER_ANALYST_ORACLE_PROD`, the same role the
deploy uses, and it can read both `VAULT_INV.VAULT_INVENTORY_V` and
`FCT_EPM.CARDPLN_PL_BY_LEAGUE_V`.

```powershell
snow streamlit deploy vault_inventory_dash --replace --role POWER_ANALYST_ORACLE_PROD
snow sql -q "SHOW STREAMLITS LIKE 'VAULT_INVENTORY_DASH' IN ACCOUNT"
```

A clean exit from `snow streamlit deploy` is **not** proof of success — the
`SHOW STREAMLITS` check is. There are no app logs for a STREAMLIT object, so a
runtime import error surfaces only as a dead app; verify locally first.

---

## 11. Suggested commit sequence

1. `docs: re-baseline README reference figures (238→242 SKUs)` — §3, standalone.
2. `feat(data): load EPM effective royalty rate by league` — `queries.py`, `data.py`, `transforms.EPM_LEAGUE`.
3. `feat(table): royalty band, footer totals and export columns` — `transforms.py`, `style.py`.
4. `feat(ui): drill-down fields and unmapped-league caption` — `style.py`, `streamlit_app.py`.
5. `docs: document the royalty basis proxy and vintage pin as caveats 7 and 8` — `README.md`.
