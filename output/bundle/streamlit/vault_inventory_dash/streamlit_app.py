"""Vault Inventory / Dealernet dashboard — layout, state, and interaction.

A Streamlit port of ``vault_inventory_dashboard.html``, in the template's own
order: header → KPI cards → filters → aging composition →
inventory & market value by brand → product detail → row drill-down.

The charts filter the page: clicking an aging slice or a brand bar sets the same
filter as its dropdown, and clicking it again clears it. See ``_pending_pick``.

Two intentional departures from the template, both flagged in its own comments:

* **Pagination is replaced by a scroll cap.** The template pages 12 rows at a
  time AND ships sticky-header CSS it never uses; its comments say the port
  should scroll instead. The table shows a fixed 25 rows, then scrolls, and the
  footer totals cover the full filtered (and searched) set, not just the rows in
  view. Column headers are the only sort control.
* **The XLS export is real.** The template's ``exportTable()`` is an ``alert()``
  stub that names ``st.download_button`` as its replacement.

The header and KPI cards render above the controls that produce their numbers
because the chrome is emitted into containers reserved ahead of them - see the
slot block below.
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
    # Its own key: .st-key-refresh is styled for the navy header, not the page.
    st.button("↻ Refresh", key="refresh_empty", on_click=st.cache_data.clear)
    st.stop()

# Every table column must exist in the snapshot. A plan-ordering slip (a column
# spec that expects a field the loader does not derive yet) then fails loudly
# here instead of as a KeyError inside a cell lambda.
_missing = [k for k in style.COLUMN_BY_KEY if k not in df_all.columns]
if _missing:
    st.error("The product table expects columns the inventory snapshot does not "
             f"carry: {', '.join(_missing)}. Check data.load_inventory.")
    st.stop()

ss = st.session_state

# ── session state ────────────────────────────────────────────────────────────
# Public widget keys are plain names; `_{key}_last` shadows a segmented control's
# last good value so `_sticky` can restore it (see below).
ss.setdefault("f_search", "")
for _key, _col, _all_label in tx.FILTER_SPECS:
    ss.setdefault(_key, "")
# Table sort: plain keys owned by no widget (the header-click handler writes them
# after the table has been drawn, which a widget key would not allow).
ss.setdefault("tbl_sort_col", "inventory_value")   # the gold column, descending
ss.setdefault("tbl_sort_asc", False)
ss.setdefault("selected_item", "—")
# Bumped only when a SKU is OPENED (row click or the Drill into SKU selectbox).
# The panel's scroll token is f"{item}#{seq}", sent on every run, so the panel
# scrolls into view once per open and an unrelated rerun leaves it where it is.
ss.setdefault("_detail_seq", 0)

# A chart click cannot write its filter where it is read: by then that filter's
# selectbox has been built, and writing a widget's key after it exists raises
# StreamlitWidgetAlreadyInstantiatedError. So _chart() stashes the pick in this
# plain key, the run ends in a rerun, and the pick is applied HERE, before any
# widget exists, as a toggle: picking the active label clears it, and a second
# brand replaces the first. It lands before the reset loop below, so a label
# that is not a valid option is still blanked there.
_pp = ss.pop("_pending_pick", None)
if _pp is not None:
    _fkey, _label = _pp
    ss[_fkey] = "" if ss[_fkey] == _label else _label

# The brand cards' toggles (README decision 14: Cases for Inventory, $ for
# Market). Seeded here rather than via default=, which Streamlit warns about
# beside a Session State value. A toggle skipped by the empty-page stop loses its
# widget state, so it re-seeds from its `_last` shadow, not the default.
for _key, _default in (("seg_brand_inv", "cases"), ("seg_brand_mkt", "value")):
    ss.setdefault(_key, ss.get(f"_{_key}_last", _default))
    ss.setdefault(f"_{_key}_last", ss[_key])

OPTIONS = tx.filter_options(df_all)

# A filter value can vanish between refreshes (a SKU sells out, a box type
# disappears). Reset it BEFORE the widget is built — Streamlit raises if a keyed
# selectbox's session value is not in its options list.
for _key, _col, _all_label in tx.FILTER_SPECS:
    if ss[_key] and ss[_key] not in OPTIONS[_key]:
        ss[_key] = ""


def _sticky(key: str) -> None:
    """Keep exactly one segment selected.

    ``st.segmented_control`` returns None when the user clicks the already-active
    segment, which would blank the control and leave its card with no series.
    Restore the last value instead. Used by the two brand-card toggles.
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


def _on_pick_sku() -> None:
    """Drill into SKU on_change: a SKU picked there scrolls into view too."""
    if ss["selected_item"] != "—":
        ss["_detail_seq"] += 1


def _chart(html: str, *, key: str, fkey: str) -> None:
    """Mount one click-to-filter chart; a click becomes filter ``fkey``.

    The pick is stashed in ``_pending_pick`` and applied at the top of the next
    run (see above), never written to ``fkey`` here. The rerun that applies it
    fires at the END of this run, not here: see the last lines of the script.
    """
    pick = interactive.chart(html, key=key)
    if pick is not None and pick in OPTIONS[fkey]:   # belt and braces
        ss["_pending_pick"] = (fkey, pick)


def _pickable(frame: pd.DataFrame, fkey: str, col: str) -> frozenset[str]:
    """Labels a chart click may pick: a dropdown option WITH rows in ``frame``.

    ``frame`` is the chart's own cross-filtered frame, so the page after a pick
    is that frame narrowed to the label, which is never empty. It also keeps the
    donut's zero-filled legend rows from filtering to nothing. The builders keep
    the selected label clickable whatever this returns.
    """
    return frozenset(OPTIONS[fkey]) & frozenset(frame[col].astype(str).unique())


SEG_LABELS = {   # the toggle labels are markdown: escape a leading # and any $
    "cases": r"\# of Cases",
    "value": r"\$ Value",
    "markup": "Markup (×)",
}


# ── reserved slots, in the TEMPLATE's order ──────────────────────────────────
# A container's on-screen position is fixed where it is DECLARED, not where it is
# filled, so the chrome can render ABOVE the controls that produce the numbers it
# reports. The template reads header -> KPI cards -> filter bar, and Streamlit has
# to execute that backwards: every card measures the frame the controls produce.
# The header is a horizontal row that IS the navy card (.st-key-chrome_hdr): the
# title fragment, Refresh, a stretch spacer, then the facts fragment.
hdr_slot = st.container(key="chrome_hdr", horizontal=True,
                        vertical_alignment="center", gap="small")
kpi_slot = st.container(key="chrome_kpi", gap=None)
flt_slot = st.container(key="chrome_flt", gap=None)

# ── filter + measure ─────────────────────────────────────────────────────────
# Every control is read out of session_state rather than from its widget's return
# value, so the measures can be computed before the widgets below are built.
# Two frames: `page` (the dropdowns) feeds the tiles, header, charts (each
# with its own filter cleared; see _page below) and the detail lookup;
# `table_rows` (page plus the table search) feeds the table,
# its footer, the export and the drill-down options. Search never moves a tile.
selections = {key: ss[key] for key, _c, _a in tx.FILTER_SPECS}
page = tx.apply_filters(df_all, selections=selections)  # tiles, header, charts
q = ss["f_search"].strip()
table_rows = tx.search_rows(page, q)                    # table, footer, export
any_filter = any(selections.values())                   # FILTERED badge: dropdowns only
cards = tx.stat_cards(page)
meta = tx.header_meta(page)
# A drill-down whose SKU a dropdown filtered away closes. One hidden only by the
# search stays open. This runs before any widget, so the write is legal.
if (ss["selected_item"] != "—"
        and ss["selected_item"] not in set(page["item_number"].astype(str))):
    ss["selected_item"] = "—"

# ── chrome: header, KPI cards ────────────────────────────────────────────────
# Refresh uses on_click: callbacks run before the script body, so load_inventory
# re-queries in this same run and there is one render, not clear() + rerun().
style.render(style.header_title_html(pulled_at), container=hdr_slot, width="content")
hdr_slot.button("↻ Refresh", key="refresh", on_click=st.cache_data.clear,
                help="Clear cached data and re-query Snowflake")
hdr_slot.space("stretch")
style.render(style.header_meta_html(meta), container=hdr_slot, width="content")
style.render(style.stat_cards_html(cards), container=kpi_slot)

# ── controls: the filter bar ─────────────────────────────────────────────────
# Built BEFORE the empty-result guard below. A widget that does not execute on a
# given run disappears from the page, so filtering down to zero rows must not take
# the filter bar with it — there would be nothing left to click to get back.
# The column indices derive from the spec count, so a filter can be added or
# dropped without touching them.
with flt_slot:
    n = len(tx.FILTER_SPECS)
    fcols = st.columns([1] * n + [0.55, 0.55])
    for i, (key, _col, all_label) in enumerate(tx.FILTER_SPECS):
        fcols[i].selectbox(
            all_label, [""] + OPTIONS[key], key=key,
            format_func=lambda v, _a=all_label: _a if v == "" else v,
            label_visibility="collapsed",
        )
    fcols[n].button("✕ Clear", key="clear", width="stretch",
                    on_click=_clear_filters,
                    help="Reset the filters and the table search")
    if any_filter:
        style.render(style.filter_badge_html(), container=fcols[n + 1])

if page.empty:
    st.warning("No SKUs match these filters. Clear one to bring rows back.")
    st.stop()

# ── charts: click to filter ──────────────────────────────────────────────────
# A click on an arc, a legend row or a bar sets the same filter as its dropdown
# (f_aging, f_brand_bucket), so the dropdown, the FILTERED badge and ✕ Clear
# follow with no extra wiring. Each chart is drawn from the page frame with ITS
# OWN filter cleared: picking Baseball highlights one bar rather than collapsing
# the brand chart to it, and the rest of the page narrows. Search is table-only
# and never reaches these frames.
def _page(**clear: str) -> pd.DataFrame:
    return tx.apply_filters(df_all, selections={**selections, **clear})


aging_frame = _page(f_aging="") if ss["f_aging"] else page
brand_frame = _page(f_brand_bucket="") if ss["f_brand_bucket"] else page

# ── aging composition ────────────────────────────────────────────────────────
style.render(style.section_label_html("Aging Composition"), style.legend_html())
sel_aging = ss["f_aging"] or None
pick_aging = _pickable(aging_frame, "f_aging", "aging_bucket")
a1, a2 = st.columns(2)
with a1:
    _chart(style.donut_card_html(
        "Aging composition by", "# of Cases",
        tx.aging_composition(aging_frame, "quantity_cases", selected=sel_aging),
        tx.fmtq_abbr, "Cases", selected=sel_aging, pickable=pick_aging),
        key="chart_aging_cases", fkey="f_aging")
with a2:
    _chart(style.donut_card_html(
        "Aging composition by", "Inventory Value",
        tx.aging_composition(aging_frame, "inventory_value", selected=sel_aging),
        tx.fmt_abbr, "Value", selected=sel_aging, pickable=pick_aging),
        key="chart_aging_value", fkey="f_aging")

# ── inventory & market value by brand ────────────────────────────────────────
# Sorted bars, not donuts: Brand Bucket has 10 categories. Two cards, each with
# a toggle above it. $ Value on the Market card is wholesale_value, the table's
# basis: with no brand picked and the search empty its bars sum to the table
# footer and to the Wholesale Value tile.
style.render(style.section_label_html("Inventory & Market Value by Brand"))
sel_brand = ss["f_brand_bucket"] or None
pick_brand = _pickable(brand_frame, "f_brand_bucket", "brand_bucket")
b1, b2 = st.columns(2)
with b1:
    st.segmented_control("Inventory by Brand", ["cases", "value"], key="seg_brand_inv",
                         format_func=SEG_LABELS.get, on_change=_sticky,
                         args=("seg_brand_inv",), label_visibility="collapsed")
    if ss["seg_brand_inv"] == "value":
        bold, rows, fmt_fn = ("Inventory Value",
                              tx.brand_composition(brand_frame, "inventory_value"),
                              tx.fmt_abbr)
    else:
        bold, rows, fmt_fn = ("# of Cases",
                              tx.brand_composition(brand_frame, "quantity_cases"), tx.fmtq)
    _chart(style.hbars_card_html("Inventory by brand —", bold, rows, fmt_fn,
                                 selected=sel_brand, pickable=pick_brand),
           key="chart_brand_inv", fkey="f_brand_bucket")
with b2:
    st.segmented_control("Market Value by Brand", ["value", "markup"], key="seg_brand_mkt",
                         format_func=SEG_LABELS.get, on_change=_sticky,
                         args=("seg_brand_mkt",), label_visibility="collapsed")
    if ss["seg_brand_mkt"] == "markup":
        mkt_html = style.hbars_card_html(
            "Market value by brand —", "Markup (×)", tx.brand_markup(brand_frame),
            tx.fmt_mult, selected=sel_brand, pickable=pick_brand, neg_below=1.0,
            sub="Wholesale ÷ Oracle cost · priced SKUs only",
            empty="No priced SKUs match these filters.")
    else:
        mkt_html = style.hbars_card_html(
            "Market value by brand —", f"Wholesale (DN × {tx.WHOLESALE_FACTOR:.0%})",
            tx.brand_composition(brand_frame, "wholesale_value"), tx.fmt_abbr,
            selected=sel_brand, pickable=pick_brand)
    _chart(mkt_html, key="chart_brand_mkt", fkey="f_brand_bucket")

# ── product detail ───────────────────────────────────────────────────────────
# The hint shows counts only; the search text itself is never echoed into HTML.
label = "Product Detail"
if q:
    label += f" · {tx.fmtq(len(table_rows))} of {tx.fmtq(len(page))} SKUs"
style.render(style.section_label_html(label))       # escapes

# Sort in pandas. Nulls always sort LAST whichever direction the column is going
# — an unpriced SKU is not "the cheapest", which is what na_position would
# otherwise imply on an ascending price sort.
# Validate against the RENDERED columns, not df_all.columns: a deleted column
# (dealernet_name, dn_latest_date, ...) still exists in the frame but has no
# header, so the table would sort by an invisible key with no arrow shown.
sort_col = ss["tbl_sort_col"] if ss["tbl_sort_col"] in style.COLUMN_BY_KEY else "inventory_value"
sort_asc = bool(ss["tbl_sort_asc"]) if sort_col == ss["tbl_sort_col"] else False
view = table_rows.sort_values(sort_col, ascending=sort_asc,
                              na_position="last", kind="mergesort")

# Toolbar: the table search in the wide left column, Export in the narrow right
# one. Search narrows the table, its footer, the export and the drill-down
# options only; the tiles and charts above keep the dropdown frame. A search with
# no match renders the table's own empty row rather than stopping the page, so
# the box stays on screen. Export takes the sorted view, so the file matches the
# table on screen.
t1, t2 = st.columns([4, 1], vertical_alignment="center")
t1.text_input("Search", key="f_search", placeholder="Product or item number…",
              label_visibility="collapsed", icon=":material/search:")
payload, ext, mime = tx.to_excel(tx.export_frame(view))
t2.download_button(f"⬇ Export {ext.upper()}", payload, key="export",
                   file_name=f"vault_inventory_{pulled_at:%Y%m%d}.{ext}",
                   mime=mime, width="stretch",
                   help="The table's rows (filters and search applied) in table order, "
                        "with raw values rather than formatted text")

totals = tx.table_totals(table_rows)
selected = None if ss["selected_item"] == "—" else ss["selected_item"]

clicked, sort_click = interactive.table(
    style.product_table_html(view, totals, selected=selected,
                             sort_col=sort_col, sort_asc=sort_asc),
    key="product_tbl",
    nonce=f"{sort_col}:{sort_asc}:{len(view)}",
    max_rows=25,
)

# A header click re-sorts; clicking the ACTIVE column flips direction, matching
# the template's sortBy(). A fresh column starts ascending for text and
# descending for numbers, which is the useful default in each case. Only plain
# keys are written, so no widget-ownership error is possible. The column is
# written on a flip too: when a stale key fell back to Inventory Value above,
# that is what makes the first click on it reverse instead of snapping back.
# The rerun that redraws the table is deferred to the end of the script, like a
# chart pick's: rerunning here would drop the Drill into SKU selectbox below,
# which this run has not reached yet, and so close an open drill-down.
resort = bool(sort_click) and sort_click in style.COLUMN_BY_KEY
if resort:
    if sort_click == sort_col:
        ss["tbl_sort_asc"] = not sort_asc
    else:
        ss["tbl_sort_asc"] = style.COLUMN_BY_KEY[sort_click]["sort"] == "text"
    ss["tbl_sort_col"] = sort_click

# A row click opens the drill-down; re-clicking the open row closes it. Only an
# open bumps the scroll sequence. This rerun may fire here: the new value is
# written to the selectbox's key BEFORE the selectbox exists, which Streamlit
# keeps across the rerun, and nothing else below it holds state. Keep every
# write to ss["selected_item"] above the selectbox.
item_options = ["—"] + view["item_number"].astype(str).tolist()
if clicked is not None and clicked in set(item_options):
    closing = clicked == ss["selected_item"]
    ss["selected_item"] = "—" if closing else clicked
    if not closing:
        ss["_detail_seq"] += 1
    st.rerun()

# The selection is OWNED by this selectbox, with the table click as a second
# input to the same session key. That keeps the two interchangeable and gives the
# drill-down a keyboard-accessible path for free.
if selected is not None and selected not in item_options:
    item_options.append(selected)  # a search hiding the open row must not break it
st.selectbox("Drill into SKU", item_options, key="selected_item",
             on_change=_on_pick_sku, label_visibility="collapsed",
             help="Or click any row in the table above")

# Looked up in the PAGE frame, not the table's, so a search that hides the open
# row does not blank its panel. A dropdown that excludes it closed it above. The
# panel is a component so it can scroll itself into view: the token changes only
# when a SKU is opened, so any other rerun sends byte-identical data and the
# panel neither scrolls nor replays its slide-in.
if ss["selected_item"] != "—":
    match = page[page["item_number"].astype(str) == ss["selected_item"]]
    if not match.empty:
        interactive.detail(style.detail_panel_html(match.iloc[0]), key="detail_panel",
                           scroll_token=f'{ss["selected_item"]}#{ss["_detail_seq"]}')

# A chart pick or a header sort reruns HERE, after every widget has been drawn,
# not where it was clicked. st.rerun() counts as a finished run, so Streamlit
# then drops the state of every widget the run did not reach: a rerun from the
# charts would silently clear the table search, and one from either would close
# the drill-down below them.
if resort or "_pending_pick" in ss:
    st.rerun()
