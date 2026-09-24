"""Vault Inventory / Dealernet dashboard — layout, state, and interaction.

A Streamlit port of ``vault_inventory_dashboard.html``, in the template's own
order: header → KPI cards → context echo → filters → aging composition →
inventory by brand → product detail → row drill-down.

Two intentional departures from the template, both flagged in its own comments:

* **Pagination is replaced by a scroll cap.** The template pages 12 rows at a
  time AND ships sticky-header CSS it never uses; its comments say the port
  should scroll instead. A rows-per-view control drives the cap, and the footer
  totals then cover exactly what is on screen.
* **The XLS export is real.** The template's ``exportTable()`` is an ``alert()``
  stub that names ``st.download_button`` as its replacement.
* **The Mapping toggle sits just below the header rather than inside it.** The
  template carries it in the header's second row, but a native Streamlit widget
  cannot live inside an HTML string, so that row becomes a navy strip closing the
  header card: same chrome, one extra element. The header card renders above the
  controls that produce its numbers because the chrome is emitted into containers
  reserved ahead of them - see the slot block below.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import data
import interactive
import style
import transforms as tx

st.set_page_config(page_title="Vault Inventory Dashboard", page_icon="◆", layout="wide")
style.inject_css()

df_all, pulled_at = data.load_inventory()
if df_all.empty:
    st.error("The inventory query returned no rows. Check warehouse access and the "
             "VAULT_INV.VAULT_INVENTORY_V grant, then hit Refresh.")
    st.stop()

ss = st.session_state

# ── session state ────────────────────────────────────────────────────────────
# Public widget keys are plain names; `_{key}_last` shadows a segmented control's
# last good value so `_sticky` can restore it (see below).
ss.setdefault("mapping", "All")
ss.setdefault("_mapping_last", ss["mapping"])
ss.setdefault("f_search", "")
for _key, _col, _all_label in tx.FILTER_SPECS:
    ss.setdefault(_key, "")
ss.setdefault("sort_col", "inventory_value")   # the gold column, descending
ss.setdefault("sort_dir", "↓ Desc")
ss.setdefault("_sort_dir_last", ss["sort_dir"])
ss.setdefault("selected_item", "—")
ss.setdefault("rows", 25)

OPTIONS = tx.filter_options(df_all)

# A filter value can vanish between refreshes (a SKU sells out, a price source
# disappears). Reset it BEFORE the widget is built — Streamlit raises if a keyed
# selectbox's session value is not in its options list.
for _key, _col, _all_label in tx.FILTER_SPECS:
    if ss[_key] and ss[_key] not in OPTIONS[_key]:
        ss[_key] = ""


def _sticky(key: str) -> None:
    """Keep exactly one segment selected.

    ``st.segmented_control`` returns None when the user clicks the already-active
    segment, which would blank the control and silently widen the view. Restore
    the last value instead.
    """
    if ss[key] is None:
        ss[key] = ss[f"_{key}_last"]
    else:
        ss[f"_{key}_last"] = ss[key]


def _clear_filters() -> None:
    ss["f_search"] = ""
    for key, _col, _all_label in tx.FILTER_SPECS:
        ss[key] = ""
    ss["selected_item"] = "—"


# Approximate row / (header + footer) heights for the custom table, used to turn
# a rows-per-view choice into a max-height in px.
ROWS_OPTS = [10, 25, 50, 100, "All"]
_ROW_PX, _HEAD_PX = 30, 44


def _cap_px(rows) -> int | None:
    return None if rows == "All" else int(_HEAD_PX + int(rows) * _ROW_PX)


# ── reserved slots, in the TEMPLATE's order ──────────────────────────────────
# A container's on-screen position is fixed where it is DECLARED, not where it is
# filled, so the chrome can render ABOVE the controls that produce the numbers it
# reports. The template reads header -> MAPPING strip -> KPI cards -> context echo
# -> filter bar, and Streamlit has to execute that backwards: every card measures
# the frame the controls produce.
hdr_slot = st.container(key="chrome_hdr", gap=None)
map_slot = st.container(key="chrome_map", gap=None)
kpi_slot = st.container(key="chrome_kpi", gap=None)
ctx_slot = st.container(key="chrome_ctx", gap=None)
flt_slot = st.container(key="chrome_flt", gap=None)

# ── filter + measure ─────────────────────────────────────────────────────────
# Every control is read out of session_state rather than from its widget's return
# value, so the measures can be computed before the widgets below are built.
mapping_code = tx.MAPPING_OPTS[ss["mapping"]]
selections = {key: ss[key] for key, _c, _a in tx.FILTER_SPECS}
flt = tx.apply_filters(df_all, mapping=mapping_code, search=ss["f_search"],
                       selections=selections)

any_filter = bool(ss["f_search"].strip()) or any(selections.values())
cards = tx.stat_cards(flt)
meta = tx.header_meta(flt)
view_label = (f"{tx.fmtq(len(flt))} of {tx.fmtq(len(df_all))} SKUs"
              if any_filter else "All Products")

# ── chrome: header, KPI cards, context echo ──────────────────────────────────
style.render(style.header_html(meta, pulled_at), container=hdr_slot)
style.render(style.stat_cards_html(cards), container=kpi_slot)
style.render(style.context_bar_html(mapping_code, view_label, any_filter),
             container=ctx_slot)

# ── controls: the navy MAPPING strip, then the filter bar ────────────────────
# Built BEFORE the empty-result guard below. A widget that does not execute on a
# given run disappears from the page, so filtering down to zero rows must not take
# the filter bar with it — there would be nothing left to click to get back.
with map_slot:
    m1, m2, m3, m4 = st.columns([0.55, 2.0, 2.2, 0.9])
    style.render(style.mapping_label_html(), container=m1)
    with m2:
        st.segmented_control(
            "Mapping", list(tx.MAPPING_OPTS.keys()), key="mapping",
            on_change=_sticky, args=("mapping",), label_visibility="collapsed",
            help="Mapped = a Dealernet case price was found for the SKU",
        )
    style.render(style.mapping_counts_html(meta), container=m3)
    with m4:
        if st.button("↻ Refresh", key="refresh", width="stretch",
                     help="Clear cached data and re-query Snowflake"):
            st.cache_data.clear()
            st.rerun()

with flt_slot:
    fcols = st.columns([1.6, 1, 1, 1, 1, 1, 0.8, 0.7])
    fcols[0].text_input("Search", key="f_search",
                        placeholder="Product or item number…",
                        label_visibility="collapsed")
    for i, (key, _col, all_label) in enumerate(tx.FILTER_SPECS):
        fcols[i + 1].selectbox(
            all_label, [""] + OPTIONS[key], key=key,
            format_func=lambda v, _a=all_label: _a if v == "" else v,
            label_visibility="collapsed",
        )
    fcols[6].button("✕ Clear", key="clear", width="stretch",
                    on_click=_clear_filters,
                    help="Reset the search box and all five filters")
    if any_filter:
        style.render(style.filter_badge_html(), container=fcols[7])

if flt.empty:
    st.warning("No SKUs match these filters. Clear one to bring rows back.")
    st.stop()

# Two honest caveats about the figures above, rather than leaving the reader to
# discover them. Both were confirmed against the source data.
notes = []
zero_qty = tx.nonpositive_qty_count(flt)
if zero_qty:
    notes.append(
        f"**{zero_qty} of {len(flt)} SKUs carry no positive on-hand quantity.** The query "
        "keeps every `-CSE` / `-DB` row regardless of quantity to match Sigma, so these are "
        "expected. Charts scale by absolute value so a negative bucket stays visible."
    )
if cards["markup"] is not None and cards["markup"] >= 5:
    notes.append(
        f"**Unrealized Gross Margin implies a {tx.fmt_mult(cards['markup'])} blended markup.** "
        "This is concentrated in premium box types (Sapphire, Delight) where the Oracle unit "
        "cost looks like a per-box figure against a per-case Dealernet price. Sort by "
        "*Markup Multiple* — available in the export — to see the outliers. Treat the margin "
        "card as an upper bound until that unit mismatch is resolved upstream."
    )
if notes:
    st.caption("  \n".join(notes))

# ── aging composition ────────────────────────────────────────────────────────
style.render(style.section_label_html("Aging Composition"), style.legend_html())
a1, a2 = st.columns(2)
# raw=True: these are the only SVG on the page, and st.html's DOMPurify profile
# carries no svg tag set, so the rings would be stripped. See style.render().
style.render(style.donut_card_html(
    "Aging composition by", "# of Cases",
    tx.aging_composition(flt, "quantity_cases"), tx.fmtq_abbr, "Cases"),
    container=a1, raw=True)
style.render(style.donut_card_html(
    "Aging composition by", "Inventory Value",
    tx.aging_composition(flt, "inventory_value"), tx.fmt_abbr, "Value"),
    container=a2, raw=True)

# ── inventory by brand ───────────────────────────────────────────────────────
# Sorted bars, not donuts: Brand Bucket has 10 categories.
style.render(style.section_label_html("Inventory by Brand"))
b1, b2 = st.columns(2)
style.render(style.hbars_card_html(
    "Inventory by brand —", "# of Cases",
    tx.brand_composition(flt, "quantity_cases"), tx.fmtq), container=b1)
style.render(style.hbars_card_html(
    "Inventory by brand —", "Inventory Value",
    tx.brand_composition(flt, "inventory_value"), tx.fmt_abbr), container=b2)

# ── market value by brand ────────────────────────────────────────────────────
style.render(style.section_label_html("Market Value by Brand"))
m1, m2 = st.columns(2)
style.render(style.hbars_card_html(
    "Market value by brand —", "Current Market Value",
    tx.brand_composition(flt, "market_value"), tx.fmt_abbr), container=m1)
style.render(style.hbars_card_html(
    "Market value by brand —", "Unrealized Gross Margin",
    tx.brand_margin_composition(flt), tx.fmt_abbr), container=m2)

# ── product detail ───────────────────────────────────────────────────────────
style.render(style.section_label_html("Product Detail"))

_SORT_LABELS = {k: h for k, h in style.SORT_OPTIONS}
_ASC, _DESC = "↑ Asc", "↓ Desc"
s1, s2, s3, s4 = st.columns([2, 1, 1, 1.2])
s1.selectbox("Sort by", [k for k, _h in style.SORT_OPTIONS], key="sort_col",
             format_func=lambda k: _SORT_LABELS[k], label_visibility="collapsed",
             help="Or click any column header in the table")
s2.segmented_control("Direction", [_DESC, _ASC], key="sort_dir",
                     on_change=_sticky, args=("sort_dir",),
                     label_visibility="collapsed")
s3.selectbox("Rows per view", ROWS_OPTS, key="rows", label_visibility="collapsed",
             help="Rows shown before the table scrolls")

payload, ext, mime = tx.to_excel(tx.export_frame(flt))
s4.download_button(f"⬇ Export {ext.upper()}", payload, key="export",
                   file_name=f"vault_inventory_{pulled_at:%Y%m%d}.{ext}",
                   mime=mime, width="stretch",
                   help="The filtered rows, with raw values rather than formatted text")

# Sort in pandas. Nulls always sort LAST whichever direction the column is going
# — an unpriced SKU is not "the cheapest", which is what na_position would
# otherwise imply on an ascending price sort.
sort_col = ss["sort_col"] if ss["sort_col"] in df_all.columns else "inventory_value"
sort_asc = ss["sort_dir"] == _ASC
view = flt.sort_values(sort_col, ascending=sort_asc,
                       na_position="last", kind="mergesort")

totals = tx.table_totals(flt)
selected = None if ss["selected_item"] == "—" else ss["selected_item"]

clicked, sort_click = interactive.table(
    style.product_table_html(view, totals, selected=selected,
                             sort_col=sort_col, sort_asc=sort_asc),
    key="product_tbl",
    nonce=f"{sort_col}:{sort_asc}:{len(view)}",
    max_height=_cap_px(ss["rows"]),
)

# A header click re-sorts; clicking the ACTIVE column flips direction, matching
# the template's sortBy(). A fresh column starts ascending for text and
# descending for numbers, which is the useful default in each case.
if sort_click and sort_click in style.COLUMN_BY_KEY:
    if sort_click == sort_col:
        ss["sort_dir"] = _DESC if sort_asc else _ASC
    else:
        ss["sort_col"] = sort_click
        ss["sort_dir"] = _ASC if style.COLUMN_BY_KEY[sort_click]["sort"] == "text" else _DESC
    ss["_sort_dir_last"] = ss["sort_dir"]
    st.rerun()

# A row click opens the drill-down; re-clicking the open row closes it.
item_options = ["—"] + view["item_number"].astype(str).tolist()
if clicked is not None and clicked in set(item_options):
    ss["selected_item"] = "—" if clicked == ss["selected_item"] else clicked
    st.rerun()

# The selection is OWNED by this selectbox, with the table click as a second
# input to the same session key. That keeps the two interchangeable and gives the
# drill-down a keyboard-accessible path for free.
if selected is not None and selected not in item_options:
    item_options.append(selected)  # sorting/filtering must not invalidate the widget
st.selectbox("Drill into SKU", item_options, key="selected_item",
             label_visibility="collapsed",
             help="Or click any row in the table above")

if ss["selected_item"] != "—":
    match = view[view["item_number"].astype(str) == ss["selected_item"]]
    if not match.empty:
        style.render(style.detail_panel_html(match.iloc[0]))
