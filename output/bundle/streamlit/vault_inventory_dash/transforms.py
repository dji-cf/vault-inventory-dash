"""Formatters, filtering, and aggregation — the measure layer.

Everything here is a pure function over the snapshot frame from ``data.py``.
The formatters are deliberate ports of the JavaScript in
``vault_inventory_dashboard.html`` and reproduce its output character for
character, including its asymmetries (``fmt_abbr`` switches to K at 1e3 while
``fmtq_abbr`` waits until 1e4). If a figure renders differently from the HTML
template, that is a bug here, not a design change.

Design contract, inherited from the sibling relic dashboard: **only additive
measures are ever summed, and every ratio is derived at render time from those
sums.** Averaging a column of per-row ratios gives a different (wrong) answer for
footer and KPI figures, so ``table_totals`` recomputes ``margin_pct`` as
Σprofit / Σwholesale rather than averaging the per-SKU margins.
"""
from __future__ import annotations

import io
import math

import pandas as pd

# ── null rendering ────────────────────────────────────────────────────────────
# The template's em dash. Every formatter returns it for None/NaN so an unpriced
# SKU reads as "no data" instead of "$0".
NULL_CELL = "—"


def _is_null(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):  # arrays / non-scalars are never "null" here
        return False


def _jsround(v: float) -> int:
    """JavaScript ``Math.round`` semantics: halves go toward +infinity.

    Python's built-in ``round`` is banker's rounding (``round(2.5) == 2``), which
    would disagree with the HTML template on exact-half cents. Used for every
    money and quantity figure so the two renderings tie out.
    """
    return math.floor(float(v) + 0.5)


# ── formatters (ports of fmt / fmtAbbr / fmtQ / fmtQAbbr / fmtPct / fmtMult) ──
def fmt(v) -> str:
    """Whole dollars: ``$1,234``."""
    if _is_null(v):
        return NULL_CELL
    return "$" + f"{_jsround(v):,}"


def fmt_abbr(v) -> str:
    """Abbreviated dollars: ``$1.2B`` / ``$1.2M`` / ``$12K`` / ``$123``.

    Note the K branch rounds to whole thousands (matching the template), so
    $12,400 reads ``$12K`` — not ``$12.4K``.
    """
    if _is_null(v):
        return NULL_CELL
    v = float(v)
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.1f}B"
    if a >= 1e6:
        return f"${v / 1e6:.1f}M"
    if a >= 1e3:
        return "$" + f"{_jsround(v / 1e3):,}" + "K"
    return "$" + f"{_jsround(v):,}"


def fmtq(v) -> str:
    """Whole quantity: ``1,234``."""
    if _is_null(v):
        return NULL_CELL
    return f"{_jsround(v):,}"


def fmtq_abbr(v) -> str:
    """Abbreviated quantity: ``1.2M`` / ``12K`` / ``123``.

    The K threshold is 1e4, not 1e3 — so 11,292 cases reads ``11K`` while 999
    stays ``999``. That asymmetry against ``fmt_abbr`` is in the template.
    """
    if _is_null(v):
        return NULL_CELL
    v = float(v)
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e4:
        return f"{_jsround(v / 1e3):,}K"
    return f"{_jsround(v):,}"


def fmt_pct(v) -> str:
    """Fraction to one decimal: ``0.1234`` -> ``12.3%``."""
    if _is_null(v):
        return NULL_CELL
    return f"{float(v) * 100:.1f}%"


def fmt_mult(v) -> str:
    """Multiple: ``2.34×``."""
    if _is_null(v):
        return NULL_CELL
    return f"{float(v):.2f}×"


_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(v) -> str:
    """``Sep 1, 2026`` — no zero padding on the day, matching the template."""
    if _is_null(v):
        return NULL_CELL
    ts = pd.Timestamp(v)
    return f"{_MON[ts.month - 1]} {ts.day}, {ts.year}"


def fmt_int(v) -> str:
    """Pack-config integers. Blank (not an em dash) when absent, since the
    template prints these bare next to '×' separators."""
    if _is_null(v):
        return NULL_CELL
    return f"{int(float(v)):,}"


# ── ordered categories + the shared aging encoding ────────────────────────────
# Sequential ramp, oldest = most saturated. The donut arcs and the table's Aging
# Bucket chips read from this one map, which is what makes them a shared encoding.
AGING_ORDER = ["0-3 Months", "3-6 Months", "6-12 Months", "12-24 Months", "24+ Months"]
AGING_UNKNOWN = "Unknown"

AGING_COLOR = {
    "0-3 Months": "#93b4dc",
    "3-6 Months": "#4d7ab8",
    "6-12 Months": "#2f5d96",
    "12-24 Months": "#b5822a",
    "24+ Months": "#a8332b",
    AGING_UNKNOWN: "#b8c2d4",
}

# 'Unknown' sorts last: the SQL emits it only for a NULL street date, which is an
# absence of information rather than a point on the age ramp.
_AGING_CATEGORIES = AGING_ORDER + [AGING_UNKNOWN]


def as_aging_category(s: pd.Series) -> pd.Series:
    """Aging bucket as an ORDERED categorical, so ramp order survives groupby.

    Any value the SQL did not produce (it should produce none) falls to
    ``Unknown`` rather than NaN, which keeps it visible and keeps totals whole.
    """
    out = pd.Series(pd.Categorical(s, categories=_AGING_CATEGORIES, ordered=True),
                    index=s.index)
    # AGING_UNKNOWN is always one of the declared categories, so this fill cannot
    # widen the category set or disturb the ordering.
    return out.fillna(AGING_UNKNOWN)


# Categorical palette carried over verbatim from the template (LINE_PALETTE) and
# the sibling relic dashboard's charts.py — identical values in all three places.
LINE_PALETTE = [
    "#4d7ab8", "#16a34a", "#dc2626", "#b5822a", "#7c3aed", "#0891b2",
    "#be185d", "#4b5563", "#ca8a04", "#059669", "#9333ea", "#e11d48",
    "#2563eb", "#65a30d", "#c2410c", "#0f766e", "#a21caf", "#78716c",
    "#1d4ed8", "#15803d",
]
OTHER_GRAY = "#9ca3af"

# Workbook ordering. Indexing colour by THIS list rather than by the filtered
# result means a bucket keeps its colour no matter what the filter leaves behind.
BRAND_ORDER = ["Baseball", "Basketball", "Entertainment", "Football", "Other",
               "Contact Sports", "Soccer", "NIL", "Formula One", "Tennis"]


def brand_color(bucket) -> str:
    """Stable colour per brand bucket; 'Other' is always gray.

    'Other' is a catch-all — the SQL COALESCEs every unmapped brand into it — so
    it deliberately reads as the neutral residual rather than as a real category.
    """
    if bucket == "Other":
        return OTHER_GRAY
    label = str(bucket)
    try:
        i = BRAND_ORDER.index(label)
    except ValueError:
        i = len(BRAND_ORDER)
    return LINE_PALETTE[i % len(LINE_PALETTE)]


# ── brand naming drift ────────────────────────────────────────────────────────
# Oracle sends one brand under two spellings — an acronym and the spelled-out
# name — and the vault view stores whichever the order used. Left alone that
# splits a brand in two everywhere the raw brand column surfaces: the table's
# BRAND cell, the sort, the export, and the Brands header fact (31 instead of
# 20). Each key below is a long form folded onto the acronym Oracle itself uses;
# the acronyms need no entry, they are already the target.
#
# Deliberately covers ONLY pairs where BOTH spellings exist in the source view's
# open records. Lone codes are left verbatim — MCD (McDonalds All American) and
# TRB (Top Rank Boxing) are opaque but they are not duplicates, and inventing a
# label for them here would be a second, unrelated change. Keys are UPPER+TRIM
# because Oracle's casing drifts, which is also why ``brand_mapping`` in
# queries.py carries 'major league baseball' next to 'MAJOR LEAGUE BASEBALL'.
# Every decoding came from the code's own PRODUCT_NAME in the vault view.
BRAND_CANON = {
    "MAJOR LEAGUE BASEBALL": "MLB",
    "NATIONAL BASKETBALL ASSOCIATION": "NBA",
    "NATIONAL FOOTBALL LEAGUE": "NFL",
    "ULTIMATE FIGHTING CHAMPIONSHIP": "UFC",
    "WORLD WRESTLING ENTERTAINMENT": "WWE",
    "DISNEY": "DIS",
    "MARVEL": "MRV",
    "STAR WARS": "STW",
    "TENNIS": "TEN",
    "UEFA CHAMPIONS LEAGUE": "CHP",
    # FOR's rows are hidden by the dashboard's own quantity > 0 rule today, so
    # only the long form currently reaches the table. Folded anyway: both
    # spellings are live in the view's open records, and the split would
    # reappear the moment a FOR row gains quantity.
    "FORMULA 1 RACING": "FOR",
    # 'Brand Other' is not a brand, it is the VeeFriends line under a
    # placeholder label; VFR is the same product. Both bucket to 'Other'.
    "BRAND OTHER": "VFR",
}


def canonical_brand(s: pd.Series) -> pd.Series:
    """Fold each long-form brand spelling onto its Oracle acronym.

    Anything absent from ``BRAND_CANON`` passes through verbatim, including
    NULL — an unrecognised brand must stay visible under its own name rather
    than collapse into a catch-all, which is the trap ``brand_bucket``'s 'Other'
    COALESCE already sets (README caveat 3).

    Deliberately does NOT touch ``brand_bucket``: that column is keyed on the
    RAW brand in SQL, and Sigma buckets CHP as 'Other' while bucketing UEFA
    CHAMPIONS LEAGUE as 'Soccer' (likewise TRB vs TOP RANK BOXING). Re-deriving
    the bucket from the canonical name here would move ~$167k out of 'Other'
    into 'Soccer' — defensible in the abstract, but it breaks brand-bucket
    parity with the prod workbook. So a merged brand can legitimately show two
    bucket values in the table, and that is why the bar charts are unaffected.
    """
    # astype(str) renders a null as the string "None", which is not a key, so a
    # null brand falls through the where() and stays null.
    key = s.astype(str).str.upper().str.strip()
    return s.where(~key.isin(BRAND_CANON), key.map(BRAND_CANON))


# Mapping-status toggle: display label -> code, and code -> the value to match.
MAPPING_OPTS = {"All": "A", "Mapped": "S", "No Price": "O"}
MAPPING_LABELS = {"A": "All Mapping", "S": "Mapped", "O": "No Price"}
_MAPPING_MATCH = {"S": "Mapped", "O": "No Price"}


# ── filtering (port of filteredRows) ─────────────────────────────────────────
# (session-state key, dataframe column) for the five dropdown filters, in the
# template's on-screen order.
FILTER_SPECS = [
    ("f_brand_bucket", "brand_bucket", "All Brand Buckets"),
    ("f_aging", "aging_bucket", "All Aging Buckets"),
    ("f_year", "street_date_year", "All Street Years"),
    ("f_box_type", "box_type", "All Box Types"),
    ("f_price_source", "price_source", "All Price Sources"),
]


def filter_options(df: pd.DataFrame) -> dict[str, list[str]]:
    """Dropdown options per filter, as strings, in the template's order.

    Derived from the FULL snapshot, not the filtered view, so the option lists
    stay stable as the user narrows down — the template does the same. NULLs are
    excluded, which is why picking a Price Source implicitly drops unmapped SKUs.
    """
    out: dict[str, list[str]] = {}
    for key, col, _all_label in FILTER_SPECS:
        vals = df[col].dropna().unique().tolist()
        if col == "aging_bucket":
            order = {v: i for i, v in enumerate(_AGING_CATEGORIES)}
            vals = sorted(vals, key=lambda v: order.get(v, len(order)))
        elif col == "brand_bucket":
            order = {v: i for i, v in enumerate(BRAND_ORDER)}
            vals = sorted(vals, key=lambda v: (order.get(v, len(order)), str(v)))
        else:
            # Numeric-aware ordering so street years sort 2023, 2024, 2026 and
            # not as zero-padded-less strings.
            try:
                vals = sorted(vals, key=lambda v: (0, float(v), ""))
            except (TypeError, ValueError):
                vals = sorted(vals, key=lambda v: (1, 0.0, str(v)))
        out[key] = [_opt_str(v) for v in vals]
    return out


def _opt_str(v) -> str:
    """Option value as the string the dropdown shows and the filter compares.

    Street year arrives as a nullable Int64 whose scalar is a float; ``2024.0``
    would neither read nor match correctly.
    """
    if isinstance(v, float) and float(v).is_integer():
        return str(int(v))
    return str(v)


def apply_filters(df: pd.DataFrame, *, mapping: str = "A", search: str = "",
                  selections: dict[str, str] | None = None) -> pd.DataFrame:
    """The template's ``filteredRows``: mapping toggle, text search, then dropdowns.

    ``mapping`` is a code from ``MAPPING_OPTS``. ``search`` matches product name
    OR item number, case-insensitively. ``selections`` maps a ``FILTER_SPECS``
    key to a chosen option string; ``""`` means "all".
    """
    out = df
    want = _MAPPING_MATCH.get(mapping)
    if want is not None:
        out = out[out["mapping_status"] == want]

    q = (search or "").strip().lower()
    if q:
        hay = (out["product_name"].fillna("").astype(str).str.lower()
               + "\x00" + out["item_number"].fillna("").astype(str).str.lower())
        out = out[hay.str.contains(q, regex=False)]

    for key, col, _all_label in FILTER_SPECS:
        chosen = (selections or {}).get(key, "")
        if chosen:
            # Compare as strings, as the template does, so an Int64 street year
            # and its dropdown label agree without dtype juggling.
            out = out[out[col].map(lambda v: _opt_str(v) if not _is_null(v) else None) == chosen]
    return out


# ── aggregation ───────────────────────────────────────────────────────────────
def _dcount(df: pd.DataFrame, col: str) -> int:
    return int(df[col].dropna().nunique())


def header_meta(df: pd.DataFrame) -> dict:
    """The header's right-hand facts plus the mapping split.

    ``brands`` counts the CANONICAL brand — ``data.load_inventory`` folds
    Oracle's duplicate spellings (MLB / MAJOR LEAGUE BASEBALL) onto one label
    via ``canonical_brand``, so this reads 20 where the raw column has 31
    spellings. ``brand_oracle`` still carries the verbatim Oracle value.

    Counting ``brand_bucket`` instead would still be wrong, for the original
    reason: the bucket folds every unmapped brand into 'Other', which would
    understate the real brand spread.
    """
    mapped = int((df["mapping_status"] == "Mapped").sum())
    return {
        "skus": _dcount(df, "item_number"),
        "brands": _dcount(df, "brand"),
        "total_val": float(df["inventory_value"].sum()),
        "mapped": mapped,
        "no_price": int(len(df)) - mapped,
    }


def stat_cards(df: pd.DataFrame) -> dict:
    """The six KPI figures, in the workbook's order.

    Three subtleties carried over from the workbook on purpose:

    * The market figures read ``market_value`` (GROSS ``dn_price x qty``), not
      ``wholesale_value``. Sigma applies its 0.8 Dealernet discount in the
      WHOLESALE VALUE table column and NOT in these KPIs; sourcing them from the
      discounted column understates both by 20%. Verified against the workbook
      2026-09-15. Do not "unify" the two bases — the asymmetry is Sigma's.
    * ``margin`` nets the market value of PRICED SKUs against the valuation of
      ALL SKUs, so unpriced inventory drags it down. That is the workbook's own
      formula, not an oversight here.
    * ``markup`` uses priced rows for BOTH numerator and denominator, so it is a
      like-for-like multiple and does not inherit that drag.
    """
    priced = df[df["dealernet_price_per_case"].notna()]
    inv_val = float(df["inventory_value"].sum())
    mkt_val = float(df["market_value"].sum())
    priced_inv = float(priced["inventory_value"].sum())
    priced_mkt = float(priced["market_value"].sum())
    cases = float(df["quantity_cases"].sum())
    return {
        "products": _dcount(df, "product_name"),
        "brand_buckets": _dcount(df, "brand_bucket"),
        "skus": _dcount(df, "item_number"),
        "box_types": _dcount(df, "box_type"),
        "cases": cases,
        "inv_val": inv_val,
        "mkt_val": mkt_val,
        "priced_skus": int(len(priced)),
        "margin": mkt_val - inv_val,
        "markup": (priced_mkt / priced_inv) if priced_inv else None,
    }


def aging_composition(df: pd.DataFrame, value_col: str) -> list[dict]:
    """Rows for one aging donut: every bucket, in ramp order, zero-filled.

    Buckets with no rows are kept at 0 so the legend is a stable five (or six)
    entries regardless of the filter. 'Unknown' appears only if present.
    """
    grouped = df.groupby("aging_bucket", observed=False)[value_col].sum()
    buckets = list(AGING_ORDER)
    if float(grouped.get(AGING_UNKNOWN, 0.0)) != 0.0:
        buckets.append(AGING_UNKNOWN)
    return [{"label": b, "value": float(grouped.get(b, 0.0)), "color": AGING_COLOR[b]}
            for b in buckets]


def brand_composition(df: pd.DataFrame, value_col: str) -> list[dict]:
    """Rows for one brand-bucket bar chart, largest first.

    Zero-value buckets are dropped (an empty bar carries no information), but
    NEGATIVE ones are kept — they are real, caused by the retained non-positive
    quantity SKUs, and hiding them would break the tie to the KPI total.
    """
    grouped = df.groupby("brand_bucket", observed=True)[value_col].sum()
    rows = [{"label": str(k), "value": float(v), "color": brand_color(k)}
            for k, v in grouped.items() if float(v) != 0.0]
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows


# Columns whose footer total is a plain sum. Ratio columns are absent by design.
_SUMMABLE = ("quantity_cases", "inventory_value", "wholesale_value",
             "total_potential_profit", "dn_listing_count")


def table_totals(df: pd.DataFrame) -> dict:
    """Footer totals for the product table.

    ``margin_pct`` is recomputed from the summed additive columns
    (Σprofit / Σwholesale) rather than averaged across rows — averaging per-SKU
    margins would weight a 1-case SKU the same as a 1,000-case one.
    """
    totals = {c: float(df[c].sum()) for c in _SUMMABLE if c in df.columns}
    ws = totals.get("wholesale_value", 0.0)
    totals["margin_pct"] = (totals.get("total_potential_profit", 0.0) / ws) if ws else None
    totals["_rows"] = int(len(df))
    return totals


def nonpositive_qty_count(df: pd.DataFrame) -> int:
    """SKUs carrying no positive on-hand quantity.

    The query keeps every ``-CSE`` / ``-DB`` row regardless of quantity, so these
    are expected, not corrupt. Surfaced in the UI so zero and negative rows are
    not read as a bug.
    """
    return int((df["quantity_cases"] <= 0).sum())


# ── export ────────────────────────────────────────────────────────────────────
# Display order and headers mirror the on-screen table, so an exported file reads
# like a screenshot of it.
_EXPORT_COLS = [
    ("product_name", "Product Name (Oracle)"),
    ("dealernet_name", "Dealernet Name"),
    ("box_type", "Box Type"),
    ("item_number", "Item Number"),
    ("brand_bucket", "Brand Bucket"),
    ("quantity_cases", "Qty (Cases)"),
    ("street_date", "Street Date"),
    ("aging_bucket", "Aging Bucket"),
    ("brand", "Brand"),
    ("brand_oracle", "Brand (Oracle raw)"),
    ("inventory_value", "Inventory Value"),
    ("boxes_per_case", "Boxes / Case"),
    ("packs_per_box", "Packs / Box"),
    ("cards_per_pack", "Cards / Pack"),
    ("unit_cost_per_case", "Unit Cost / Case"),
    ("dealernet_price_per_case", "DN Price / Case"),
    ("market_value", "Market Value"),
    ("wholesale_value", "Wholesale Value"),
    ("margin_pct", "Margin %"),
    ("total_potential_profit", "Potential Profit"),
    ("margin_dollars_per_case", "Margin $ / Case"),
    ("markup_multiple", "Markup Multiple"),
    ("price_source", "Price Source"),
    ("dn_listing_count", "DN Listings"),
    ("dn_latest_date", "DN Latest"),
    ("year_match_type", "Year Match Type"),
]


def export_frame(df: pd.DataFrame) -> pd.DataFrame:
    """The filtered frame as raw typed values under display headers.

    Values stay numeric and dates stay dates — the point of an export is that the
    recipient can pivot and sum it, which formatted strings would prevent.
    """
    cols = [(c, h) for c, h in _EXPORT_COLS if c in df.columns]
    out = df[[c for c, _ in cols]].copy()
    out.columns = [h for _, h in cols]
    for c in ("Street Date", "DN Latest"):
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce").dt.date
    if "Aging Bucket" in out.columns:
        out["Aging Bucket"] = out["Aging Bucket"].astype(str)
    return out


def to_excel(df: pd.DataFrame) -> tuple[bytes, str, str]:
    """``(payload, filename_suffix, mime)`` for a download button.

    Degrades to CSV when openpyxl is unavailable (it is pinned in
    pyproject.toml, but the warehouse runtime ships a fixed dependency set).
    The suffix and MIME travel WITH the bytes so a CSV fallback is never served
    under an .xlsx name — a file that no spreadsheet will open.
    """
    buf = io.BytesIO()
    try:
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="inventory")
    except Exception:
        return (df.to_csv(index=False).encode("utf-8"), "csv", "text/csv")
    return (
        buf.getvalue(),
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
