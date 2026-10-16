"""Pixel-faithful chrome: CSS + HTML/SVG builders ported from the HTML template.

``vault_inventory_dashboard.html`` was written as a port spec — it keeps the
sibling relic dashboard's class names so this module can adapt that stylesheet
rather than rewrite it. Two structural changes were unavoidable:

**Rescoping.** The template styles bare elements (``body``, ``header``, ``table``,
``td``, ``thead th``). Every selector here is scoped under a ``.fct`` wrapper so
it cannot collide with Streamlit's own DOM. The ``:root`` variables stay on
``:root`` and are repeated on ``.fct`` (the table's shadow root has no
``:root``). ``position: sticky`` on the header is dropped — Streamlit owns the
scroll container — so the header renders as a card.

**Splitting.** Page styles cannot pierce a Custom Component's shadow root, so the
product table's CSS ships separately as ``TABLE_CSS``, the four charts' as
``CHART_CSS`` and the row drill-down panel's as ``DETAIL_CSS`` (each injected
into its component), while the page chrome uses ``CSS``. Rules needed on more
than one side (chips, status pills, tokens) live in the shared blocks and are
concatenated into each.

The donut and horizontal-bar charts are built here as inline SVG/CSS rather than
handed to Altair: the template's donut pairs an arc ring with an itemised
value+percentage legend beside it, and its bars are a label/track/value grid.
Reproducing those in Altair would approximate the design instead of porting it.
They are mounted through ``interactive.chart``, which makes every ``data-pick``
element a click-to-filter target.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from html import escape

import pandas as pd

import streamlit as st
import transforms as tx

# Freshness tooltips read best in the reader's own wall-clock time. The zone is
# PINNED rather than taken from the host clock: the SiS container runs in UTC, so
# a host-derived zone would silently differ between local dev and deployed. Set
# DASHBOARD_TZ to any IANA name to override.
#
# zoneinfo is stdlib, but the tz DATABASE it reads is not guaranteed to exist in
# a minimal container image, so a missing/unknown zone degrades to a UTC-only
# tooltip rather than taking the header down. `tzdata` is pinned in
# pyproject.toml to make the named-zone branch reliable on the container runtime.
try:
    from zoneinfo import ZoneInfo

    _LOCAL_TZ = ZoneInfo(os.getenv("DASHBOARD_TZ") or "America/New_York")
except Exception:  # any lookup failure means "no local zone" -> UTC-only tooltip
    _LOCAL_TZ = None


# ══════════════════════════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════════════════════════

# Page-level only. @font-face rules are DOCUMENT-scoped, so importing the faces
# once here makes them available inside the table component's shadow root too —
# the component's own stylesheet does not need (and may ignore) an @import.
# ONE face: Inter, at every size and weight the chrome uses. The template paired
# it with DM Mono for micro-labels, but that read as a second, competing typeface
# beside the native Streamlit widgets — the filter bar and the aging legend in
# particular — so the dashboard is deliberately single-face now. The digit
# alignment DM Mono used to buy comes from font-variant-numeric: tabular-nums,
# which the numeric rules already carry.
# If the host cannot reach fonts.googleapis.com the stack falls back to system
# faces: label typography changes, layout does not.
_FONT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
"""

# Tokens + box model. Needed in the page stylesheet for the chrome AND inside the
# table component, because page styles can't pierce the shadow root.
# The custom properties sit on :root AS WELL AS .fct. The st-key-* rules in
# _WIDGET_CSS dress native widgets and containers that are not .fct descendants,
# so a .fct-only declaration left every var() there resolving to nothing (a
# transparent header card, theme-coloured button text). Inside the table's shadow
# root :root matches nothing and .fct still does. color / font stay on .fct only:
# on :root they would change Streamlit's own base font.
_TOKENS_CSS = """
.fct, .fct * { box-sizing: border-box; margin: 0; padding: 0; }
:root, .fct {
  --bg: #f0f2f5;
  --surface: #ffffff;
  --surface2: #f8f9fc;
  --border: #e2e8f0;
  --accent: #4d7ab8;
  --accent2: #16a34a;
  --text: #1a2b4a;
  --muted: #6b7fa3;
  --selected-bg: #eff6ff;
  --selected-border: #4d7ab8;

  --navy: #1a2b4a;
  --navy-deep: #0f1e38;
  --gold: #b5822a;
  --gold-wash: #fffbf0;
  --on-navy: #7a99c0;
  --on-navy-bright: #e0eaf7;

  --pos: #16a34a;
  --neg: #dc2626;

  /* AGING BUCKET RAMP — sequential, oldest = most saturated. Shared encoding:
     the donut arcs and the table's Aging Bucket chips use the same values. */
  --age-0-3:    #93b4dc;
  --age-3-6:    #4d7ab8;
  --age-6-12:   #2f5d96;
  --age-12-24:  #b5822a;
  --age-24plus: #a8332b;

  --band-identity:  #1f3d6a;
  --band-inventory: #166534;
  --band-pricing:   #155e63;
  --band-margin:    #8a6314;
  --band-dealernet: #5b3a8e;
}
.fct {
  color: var(--text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
}
"""

# Chips and status pills appear in the table AND in the drill-down panel, two
# separate shadow roots, so they are shared rather than duplicated.
_CHIP_CSS = """
.fct .chip {
  font-size: 10px; font-weight: 700;
  padding: 1px 6px; border-radius: 4px; vertical-align: middle;
  white-space: nowrap; display: inline-block;
}
.fct .chip-up   { background: #dcfce7; color: #166534; }
.fct .chip-down { background: #fee2e2; color: #7f1d1d; }
.fct .chip-new  { background: #e0e7ff; color: #3730a3; }
.fct .chip-age  { color: #fff; }

.fct .status-pill {
  font-family: 'Inter', sans-serif;
  font-size: 10px; font-weight: 700;
  padding: 2px 8px; border-radius: 10px;
  background: var(--accent); color: #fff;
  letter-spacing: 0; white-space: nowrap; display: inline-block;
}
.fct .pill-live  { background: #e8f5ec; color: #2a6e3f; }
.fct .pill-stale { background: #fdf3e1; color: #8a5a12; }
.fct .pill-none  { background: #fdecea; color: #9c2a22; }

.fct .no-data {
  text-align: center; padding: 40px;
  color: var(--muted); font-size: 13px;
  white-space: normal;
}
"""

_CHROME_CSS = """
/* ── HEADER ──────────────────────────────────────────────────────────────────
   The template's header element is sticky and full-bleed. Streamlit owns the
   scroll container, so it becomes a rounded card instead — same chrome, no
   sticking. The card itself is the keyed horizontal container
   .st-key-chrome_hdr (see _WIDGET_CSS), because the Refresh button beside Data
   Pulled is a native widget and cannot live inside an HTML string. The rules
   here style the two HTML fragments it holds: the title group and the facts.

   NOTE: not one LESS-THAN character may appear anywhere in this stylesheet, not
   even inside a comment. st.html sanitizes with DOMPurify, whose SAFE_FOR_XML
   guard FORCE-REMOVES any element whose own text looks like markup (a less-than
   followed by a letter, "!" or "/") and it runs BEFORE the allowed-tags check. A
   style element is exactly that shape — its innerHTML is its text — so a single
   "header" written in angle brackets here silently deletes all 11 KB of page CSS
   and the whole dashboard renders as naked HTML. _checked() below is what makes
   that failure loud instead of silent. */
/* The title and the "As of / Data pulled" line share a BASELINE - the only
   alignment that reads as correct between a 24px title and a 10px label. They
   are ONE fragment so .hdr-meta, which is a two-line stack, can stay
   box-centered in the header row on its own: the container's single
   vertical_alignment cannot serve both. */
.fct .hdr-title-group { display: flex; align-items: baseline; gap: 20px; flex-wrap: wrap; }
.fct .logo {
  font-size: 24px; font-weight: 500; letter-spacing: 0;
  color: #ffffff; line-height: 1.1;
}
/* Only SIZE separates the qualifier from the title: same face, same weight,
   same white. */
.fct .logo span { font-size: 15px; }

.fct .dataset-selector-wrap { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.fct .dataset-label {
  font-size: 10px; font-weight: 700;
  color: var(--on-navy); letter-spacing: 0; white-space: nowrap;
}
.fct .dataset-value {
  color: #fff; font-size: 13px; font-weight: 700;
}
.fct .dataset-value.dim { color: rgba(255,255,255,.85); font-size: 12px; font-weight: 400; }
.fct .dataset-sep { color: rgba(255,255,255,.4); margin: 0 6px; }

/* No margin-left:auto - the header's stretch spacer pushes the facts right. */
.fct .hdr-meta { display: flex; gap: 26px; row-gap: 10px; flex-wrap: wrap; }
.fct .hdr-meta > div {
  font-size: 10px; font-weight: 700; letter-spacing: 0;
  color: var(--on-navy);
}
.fct .hdr-meta b {
  display: block; margin-top: 2px; color: #fff; font-size: 14px;
  font-variant-numeric: tabular-nums; letter-spacing: 0;
}

/* ── SECTION LABELS ─────────────────────────────────────────────────────────
   The template declares .section-label but renders .trend-title instead;
   revived here — it is the same ::after hairline device. Values match the relic
   dashboard's .sec-title so the two read alike once merged. */
.fct .section-label {
  font-size: 12px; font-weight: 700; letter-spacing: 0;
  color: var(--muted);
  margin: 8px 0 12px;
  display: flex; align-items: center; gap: 10px;
}
.fct .section-label::after { content: ''; flex: 1; height: 1px; background: var(--border); }

/* ── LEGEND ─────────────────────────────────────────────────────────────────── */
.fct .legend { display: flex; gap: 20px; margin-bottom: 14px; flex-wrap: wrap; }
.fct .legend-item {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--muted);
}
.fct .legend-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }

/* .filter-badge - shown in the filter row whenever a filter is narrowing the view. */
.fct .filter-badge {
  font-size: 10px; letter-spacing: 0;
  color: var(--accent); border: 1px solid var(--accent);
  border-radius: 4px; padding: 3px 8px;
  display: inline-block; white-space: nowrap;
}

/* ── STAT CARDS ─────────────────────────────────────────────────────────────── */
.fct .stat-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 22px;
}
.fct .stat-card {
  background: var(--surface);
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
  border-top: 3px solid var(--accent);
}
.fct .stat-card-total  { border-top-color: var(--gold); background: var(--gold-wash); }
.fct .stat-card-market { border-top-color: var(--accent2); }
.fct .stat-card-margin { border-top-color: var(--band-dealernet); }
.fct .stat-card-label {
  font-size: 10px; font-weight: 700;
  letter-spacing: 0; color: var(--muted); margin-bottom: 6px;
}
.fct .stat-card-value {
  font-size: 26px; font-weight: 700; color: var(--text);
  line-height: 1.1; letter-spacing: -.5px;
  font-variant-numeric: tabular-nums;
}
.fct .stat-card-sub {
  font-size: 11px; color: var(--muted); margin-top: 3px;
  font-variant-numeric: tabular-nums;
}
/* The Wholesale Value card's "N SKUs not priced" note. */
.fct .stat-card-sub .sub-neg { color: var(--neg); }
"""

_TABLE_CSS = """
/* ── TABLE ──────────────────────────────────────────────────────────────────── */
.fct .table-wrap {
  background: var(--surface);
  border-radius: 8px;
  overflow-x: auto;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}
/* min-width:max-content is what lets the 15 columns size to their content and
   scroll sideways rather than compressing into illegibility. */
.fct table { width: 100%; min-width: max-content; border-collapse: collapse; table-layout: auto; }

.fct thead th {
  background: var(--navy);
  padding: 4px 5px;
  text-align: right;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0;
  color: #ffffff;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255,255,255,.08);
  cursor: pointer;
  user-select: none;
}
.fct thead th:first-child { text-align: left; background: #000000 !important; color: #fff !important; }
.fct thead th.sorted { color: var(--gold); }
.fct thead th .sort-arrow { margin-left: 4px; opacity: .6; }
/* Headers are the only sort control, so they need a hover state. An underline
   rather than a background: the band classes and th:first-child set their
   backgrounds with !important, which a hover background would lose to (or, if
   forced, would erase the band colour). */
.fct thead tr:not(.col-group-header) th[data-sort]:hover { box-shadow: inset 0 -2px 0 var(--gold); }

.fct .col-group-header th {
  background: var(--navy-deep);
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0;
  padding: 3px 5px;
  text-align: center;
  border-bottom: 1px solid rgba(255,255,255,.06);
  cursor: default;
}
.fct .col-group-header th:first-child { background: #000000 !important; }

/* Band tints repeat on both header rows so each group reads as one vertical
   stripe. */
.fct .th-identity  { background: var(--band-identity)  !important; color: #fff !important; border-bottom: none !important; }
.fct .th-inventory { background: var(--band-inventory) !important; color: #fff !important; border-bottom: none !important; }
.fct .th-pricing   { background: var(--band-pricing)   !important; color: #fff !important; border-bottom: none !important; }
.fct .th-margin    { background: var(--band-margin)    !important; color: #fff !important; border-bottom: none !important; }

/* Inventory Value is the authoritative measure — it gets the gold treatment the
   template reserves for its TOTAL VALUE column. */
.fct thead th.td-total { background: var(--gold) !important; color: #fff !important; }
.fct .td-total { font-weight: 700; color: #000000; font-size: 11px; }

.fct td {
  padding: 4px 5px;
  text-align: right;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  white-space: nowrap;
}
.fct td:first-child {
  text-align: left;
  font-size: 11px;
  font-weight: 500;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fct td.td-left  { text-align: left; }
.fct td.td-muted { color: var(--muted); }
.fct td.td-pos   { color: var(--pos); }
.fct td.td-neg   { color: var(--neg); }
.fct td.td-null  { color: #b8c2d4; }
.fct td.td-code  { font-size: 11px; }

.fct tbody tr[data-key] { cursor: pointer; }
.fct tbody tr:hover { background: var(--surface2); }
.fct tbody tr.selected { background: var(--selected-bg); border-left: 3px solid var(--selected-border); }
.fct tbody tr.selected td:first-child { padding-left: 13px; }

.fct .tfoot-row { background: var(--surface2); border-top: 2px solid var(--border); }
.fct .tfoot-row td { font-weight: 700; font-size: 10.5px; }

/* Stale Dealernet price (older than transforms.STALE_DAYS), before the Adj. DN
   Price digits so right-aligned numbers stay aligned. */
.fct .stale-dot {
  display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; background: var(--gold);
  margin-right: 4px; vertical-align: middle;
}

/* STICKY: the 15-column table can scroll sideways, so the product name column is
   pinned — it is what keeps rows identifiable. thead/tfoot stick as blocks,
   which handles the two-row grouped header with no per-row top offsets.
   A sticky cell is transparent by default, so the tbody backgrounds below are
   required or scrolling content shows through; .selected comes last to beat
   :hover at the same specificity. */
.fct .table-wrap.scrollable { overflow: auto; }
.fct .table-wrap.scrollable thead { position: sticky; top: 0; z-index: 3; }
.fct .table-wrap.scrollable tfoot { position: sticky; bottom: 0; z-index: 3; }
.fct thead th:first-child { position: sticky; left: 0; z-index: 4; }
.fct tbody td:first-child { position: sticky; left: 0; z-index: 1; background: var(--surface); }
.fct tbody tr:hover td:first-child { background: var(--surface2); }
.fct tbody tr.selected td:first-child { background: var(--selected-bg); }
.fct tfoot td:first-child { position: sticky; left: 0; z-index: 4; background: var(--surface2); }
.fct td.no-data:first-child { position: static; max-width: none; }
"""

# The four charts render inside interactive.chart's shadow root (click-to-filter),
# so, like the table's, their CSS ships into the component and no page rule can
# reach them. The section labels and the aging ramp legend above them are page
# chrome and stay in _CHROME_CSS.
_CHART_CSS = """
/* ── CHARTS ───────────────────────────────────────────────────────────────────
   The relic dashboard renders its charts through Altair, so their text picks up
   the theme font (Inter), which is now the dashboard's only face, and they sit on
   the same surface treatment as its .table-wrap: radius 8px plus a soft shadow,
   no border. Both
   are mirrored here so the hand-built donuts read as the same family of chart.
   The aging ramp colours are deliberately NOT touched — that sequential encoding
   is shared with the table's Aging Bucket chips. */
.fct .chart-wrap {
  background: var(--surface);
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
  padding: 18px 22px 14px;
  overflow-x: auto;
  height: 100%;
}
.fct .chart-wrap svg { display: block; }
.fct .chart-title {
  font-size: 12px; font-weight: 700; letter-spacing: 0; color: var(--muted);
  margin-bottom: 14px;
}
.fct .chart-title b { color: var(--text); font-weight: 700; }
/* A basis line under the title (the Markup card's). */
.fct .chart-sub { font-size: 11px; color: var(--muted); margin: -10px 0 12px; }

/* Donut: SVG on the left, itemised legend on the right. */
.fct .donut-row { display: flex; align-items: center; gap: 22px; flex-wrap: wrap; }
.fct .donut-center-val {
  font-family: 'Inter', sans-serif; font-size: 20px; font-weight: 700;
  fill: #1a2b4a; font-variant-numeric: tabular-nums;
}
.fct .donut-center-lbl {
  font-family: 'Inter', sans-serif; font-size: 9px; font-weight: 700;
  fill: #6b7fa3; letter-spacing: .7px;
}
.fct .donut-legend { flex: 1; min-width: 190px; display: flex; flex-direction: column; gap: 6px; }
.fct .donut-legend-row {
  display: grid; grid-template-columns: 10px 1fr auto auto;
  align-items: center; gap: 8px;
  font-size: 12px; color: var(--muted);
}
.fct .donut-legend-row .dl-dot { width: 10px; height: 10px; border-radius: 2px; }
.fct .donut-legend-row .dl-val { color: var(--text); font-variant-numeric: tabular-nums; }
.fct .donut-legend-row .dl-pct { width: 42px; text-align: right; font-variant-numeric: tabular-nums; }

/* Horizontal bars: label / track / value. */
.fct .hbars { display: flex; flex-direction: column; gap: 7px; }
.fct .hbar-row {
  display: grid; grid-template-columns: 112px 1fr 76px;
  align-items: center; gap: 10px;
  font-size: 12px; color: var(--muted);
}
.fct .hbar-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fct .hbar-track { background: var(--surface2); border-radius: 3px; height: 14px; overflow: hidden; }
.fct .hbar-fill { display: block; height: 100%; border-radius: 3px; }
.fct .hbar-val { text-align: right; color: var(--text); font-variant-numeric: tabular-nums; }

/* ── CLICK TO FILTER ──────────────────────────────────────────────────────────
   Anything carrying data-pick sets (or clears) a page filter: the donut arcs,
   mouse only, and the legend and bar rows, which also take the keyboard
   (tabindex, role=button, Enter or Space). With a pick active, the picked item is
   .is-sel and every other item .is-dim. Arcs hit-test on their stroke through the
   SVG default pointer-events, so no override is set there; the two centre labels
   opt out so they can never swallow a click. The pickable rows pad out into
   their own negative margin, so the hover wash has room without moving a pixel
   of layout. */
.fct [data-pick] { cursor: pointer; }
.fct .is-dim { opacity: .35; }
.fct circle[data-pick]:hover { opacity: .8; }
.fct circle.is-dim[data-pick]:hover { opacity: .6; }
.fct .donut-legend-row[data-pick], .fct .hbar-row[data-pick] {
  border-radius: 4px; padding: 2px 4px; margin: -2px -4px;
}
.fct .donut-legend-row[data-pick]:hover, .fct .hbar-row[data-pick]:hover {
  background: var(--surface2);
}
.fct .donut-legend-row[data-pick]:focus-visible, .fct .hbar-row[data-pick]:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 1px;
}
.fct .is-sel .dl-label, .fct .is-sel .hbar-label { color: var(--text); font-weight: 700; }
.fct .donut-center-val, .fct .donut-center-lbl { pointer-events: none; }
"""

# The row drill-down renders inside interactive.detail's shadow root (so it can
# scroll itself into view), so its CSS ships into that component too. Nothing on
# the page renders the panel any more.
_DETAIL_CSS = """
/* ── DETAIL PANEL (row drill-down) ─────────────────────────────────────────── */
@keyframes fctSlideIn {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.fct .detail-panel {
  background: var(--surface);
  border: 1px solid var(--accent2);
  border-radius: 10px;
  overflow: hidden;
  margin-top: 14px;
  animation: fctSlideIn 0.25s ease;
}
.fct .detail-panel-header {
  background: var(--navy);
  padding: 12px 20px;
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.fct .detail-panel-title {
  font-size: 16px; font-weight: 700; color: #fff; letter-spacing: 0;
}
.fct .detail-count-badge {
  background: rgba(255,255,255,.12);
  border: 1px solid rgba(255,255,255,.2);
  color: #c5d4ea;
  font-size: 11px; padding: 2px 8px; border-radius: 20px;
}
/* A FIXED column count: 12 tiles fill 4 (or 2) columns evenly, and columns line
   up as cost over market over margin. auto-fit gave 8 tracks at about 1,400px,
   and the 4 empty ones showed the old grid background as a grey block. The
   hairlines are drawn on the cells instead, so an empty track stays white. */
.fct .detail-grid {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  background: var(--surface);
}
.fct .detail-cell {
  background: var(--surface); padding: 12px 16px;
  box-shadow: 1px 0 0 var(--border), 0 1px 0 var(--border);
}
.fct .detail-cell .dc-lbl {
  font-size: 9px; font-weight: 700;
  letter-spacing: 0; color: var(--muted); margin-bottom: 4px;
}
.fct .detail-cell .dc-val { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
/* Dealernet names run to about 55 characters, so that tile wraps. */
.fct .detail-cell .dc-text { font-size: 13px; font-weight: 500; overflow-wrap: anywhere; }
.fct .detail-cell .dc-sub {
  font-size: 11px; color: var(--muted); margin-top: 3px;
  font-variant-numeric: tabular-nums;
}
/* A stale price's sub-line, in the .pill-stale amber. */
.fct .detail-cell .dc-sub .sub-stale { color: #8a5a12; }
@media (max-width: 900px) {
  .fct .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
"""

# Streamlit's own widgets sit between the ported blocks; these few rules stop the
# default spacing from breaking the template's rhythm. Global, not .fct-scoped.
_STREAMLIT_CSS = """
/* The template packs its filter bar tightly; Streamlit's default block gap
   would spread the six controls over twice the height. */
div[data-testid="stHorizontalBlock"] { gap: 10px; }
/* The st.html wrapper adds vertical rhythm the template does not want: its
   line box would pad every chrome fragment. Zero it on the wrapper and restore
   it on the fragment inside. */
div[data-testid="stHtml"] { line-height: 0; }
div[data-testid="stHtml"] > * { line-height: normal; }
"""


# The template's own widget chrome (.search-box, .filter-select, .sort-btn,
# .export-btn) has no markup in this port - native Streamlit controls stand in for
# it. These rules dress those controls to the template's spec, keyed off the
# st-key-* classes Streamlit emits for any widget or container with a key. Those
# elements are not .fct descendants, so their var() tokens resolve only because
# _TOKENS_CSS declares them on :root too.
_WIDGET_CSS = """
/* HEADER - the keyed horizontal container IS the navy card. Children: the
   title fragment, Refresh, a stretch spacer, the facts fragment. */
.st-key-chrome_hdr {
  background: var(--navy);
  border-radius: 10px;
  padding: 12px 22px;
  margin-bottom: 18px;
  box-shadow: 0 2px 8px rgba(0,0,0,.25);
}

/* Refresh is a port addition, not in the template; give it the on-navy ghost look. */
.st-key-refresh button {
  font-size: 11px; letter-spacing: 0;
  background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.28);
  color: var(--on-navy-bright); border-radius: 6px; padding: 4px 12px; min-height: 0;
}
.st-key-refresh button:hover {
  background: rgba(255,255,255,.16); color: #fff; border-color: rgba(255,255,255,.5);
}

/* FILTER BAR - four .filter-select, on white; the .search-box (f_search) sits
   in the Product Detail toolbar and shares the st-key-f_ rules. The face comes
   from the Inter theme font: these containers are NOT .fct descendants, so they
   inherit from Streamlit's root rather than from the chrome's own rules. */
.st-key-chrome_flt { margin-bottom: 20px; }
.st-key-chrome_flt div[data-testid="stHorizontalBlock"] { align-items: center; }
div[class*="st-key-f_"] div[data-testid="stSelectbox"] { min-width: 120px; }
div[class*="st-key-f_"] input { font-size: 12px; }
/* The open popover renders OUTSIDE the widget container, so it needs its own
   rule or the option list shows at the theme's 14px while the closed value
   reads 12px. */
div[data-testid="stSelectboxVirtualDropdown"] li { font-size: 12px; }
/* Must out-specify the rule above, which is (0,1,2) - hence the attribute
   selector rather than the bare .st-key-f_search class, which lost at (0,1,1)
   and silently left the search box at 12px. */
div[class*="st-key-f_search"] input { font-size: 13px; padding: 8px 14px; }

/* .sort-btn / .export-btn - ghost buttons on the page ground. */
.st-key-clear button, .st-key-export button {
  font-size: 11px; letter-spacing: 0;
  background: none; border: 1px solid var(--border); color: var(--muted);
  border-radius: 6px; padding: 5px 12px; min-height: 0;
}
.st-key-clear button:hover, .st-key-export button:hover {
  border-color: var(--accent); color: var(--accent);
}

/* BRAND CHART TOGGLES - the segmented control above each brand card
   (seg_brand_inv, seg_brand_mkt), white on the page ground. */
div[class*="st-key-seg_"] div[data-testid="stButtonGroup"] {
  border: 1px solid var(--border);
  border-radius: 6px; overflow: hidden; gap: 0; width: fit-content;
}
div[class*="st-key-seg_"] div[data-testid="stButtonGroup"] button {
  font-size: 11px;
  border: none; border-right: 1px solid var(--border); border-radius: 0;
  background: var(--surface); color: var(--muted); padding: 5px 12px; min-height: 0;
}
div[class*="st-key-seg_"] div[data-testid="stButtonGroup"] button:last-child { border-right: none; }
div[class*="st-key-seg_"] div[data-testid="stButtonGroup"] button[data-selected] {
  background: var(--surface2); color: var(--text); font-weight: 600;
}
"""

_CSS_BODY = (_FONT_CSS + _TOKENS_CSS + _CHIP_CSS + _CHROME_CSS + _STREAMLIT_CSS
             + _WIDGET_CSS)

# Raw CSS (no <style> tag) for the table mounted via interactive.table — injected
# into the component's shadow root.
_TABLE_CSS_BODY = _TOKENS_CSS + _CHIP_CSS + _TABLE_CSS

# Likewise for the charts mounted via interactive.chart. _CHIP_CSS brings
# .no-data; _TOKENS_CSS the --age-*, --neg and --surface* tokens.
_CHART_CSS_BODY = _TOKENS_CSS + _CHIP_CSS + _CHART_CSS

# And for the drill-down panel mounted via interactive.detail. _TOKENS_CSS brings
# --surface, --navy, --gold, --pos, --neg and the .fct reset; _CHIP_CSS the aging
# chip, .status-pill and the .pill-* classes.
_DETAIL_CSS_BODY = _TOKENS_CSS + _CHIP_CSS + _DETAIL_CSS


def _checked(css: str, what: str) -> str:
    """Reject a stylesheet DOMPurify would silently delete.

    A less-than character anywhere in the CSS text trips DOMPurify's SAFE_FOR_XML
    mXSS guard, which force-removes the entire style element. See _CHROME_CSS.
    """
    if "<" in css:
        i = css.index("<")
        raise AssertionError(
            f"{what} contains a less-than character at offset {i}: "
            f"...{css[max(0, i - 60):i + 20]!r}... DOMPurify's SAFE_FOR_XML guard "
            "deletes the entire style element, which silently unstyles the whole "
            "page. Rewrite it without that character."
        )
    return css


CSS = "<style>" + _checked(_CSS_BODY, "page CSS") + "</style>"

TABLE_CSS = _checked(_TABLE_CSS_BODY, "table CSS")

# Component CSS is never DOMPurified, so _checked is not strictly needed here; it
# is kept so the block stays safe to share with the page later. Keep it
# MULTI-LINE: CCv2 reads a single-line string holding "/", "*", "[" or "]" as a
# file path or glob, and then demands an asset_dir in pyproject.toml.
CHART_CSS = _checked(_CHART_CSS_BODY, "chart CSS")

# Same reasoning, and the same multi-line rule, as CHART_CSS.
DETAIL_CSS = _checked(_DETAIL_CSS_BODY, "detail CSS")


def inject_css() -> None:
    st.html(CSS)


def open_fct() -> str:
    return '<div class="fct">'


def close_fct() -> str:
    return "</div>"


def wrap(*parts: str) -> str:
    """Bracket HTML fragments in the scoped wrapper for a single emission."""
    return open_fct() + "".join(parts) + close_fct()


def render(*parts: str, container=None, width="stretch") -> None:
    """Emit scoped chrome into ``container`` (default: the page) via ``st.html``.

    ``st.html`` is the stricter channel, and it does not re-parse the payload as
    markdown, so a ``*`` or ``_`` in a product name stays literal. It sanitizes
    with DOMPurify(USE_PROFILES={'html': True}), whose tag profile carries no svg
    set, and ``svg`` is in DOMPurify's FORBID_CONTENTS, so SVG sent through here
    is dropped WITH its children. Nothing rendered here carries SVG: the donut
    rings are the page's only SVG, and they go out through ``interactive.chart``,
    which sets its HTML via innerHTML inside a component shadow root that
    DOMPurify never sees.

    ``width`` is forwarded to ``st.html``. ``"content"`` lets a fragment hug its
    text inside a horizontal container (the header). ``"stretch"``, the default,
    fills the page's vertical containers.
    """
    target = st if container is None else container
    target.html(wrap(*parts), width=width)


# ══════════════════════════════════════════════════════════════════════════════
# FRESHNESS
# ══════════════════════════════════════════════════════════════════════════════
def _rel_age(secs: float) -> str:
    """Coarse human age for a data-pull stamp ("12 min ago").

    Deliberately low-resolution: the point is answering "is this stale?" at a
    glance, not stopwatch precision. Never says "0 min ago" — anything under 45s
    reads as "just now".
    """
    if secs < 45:
        return "just now"
    mins = secs / 60
    if mins < 60:
        return f"{int(round(mins)) or 1} min ago"
    hrs, rem_min = divmod(int(round(mins)), 60)
    if hrs < 24:
        return f"{hrs} hr ago" if rem_min == 0 else f"{hrs} hr {rem_min} min ago"
    days = int(round(hrs / 24))
    return "1 day ago" if days == 1 else f"{days} days ago"


def freshness_label(pulled_at: datetime, now: datetime | None = None) -> tuple[str, str]:
    """``(relative, absolute)`` strings for a UTC data-pull instant.

    The absolute form always carries an explicit zone, and appends UTC whenever a
    local zone is available, so a screenshot of the tooltip is never ambiguous.
    ``now`` is injectable for tests.
    """
    now = now or datetime.now(timezone.utc)
    # A stamp slightly in the future (clock skew between the app host and
    # wherever `now` came from) must not render as a negative age.
    rel = _rel_age(max(0.0, (now - pulled_at).total_seconds()))
    utc_txt = pulled_at.strftime("%b %d, %Y %H:%M UTC")
    if _LOCAL_TZ is None:
        return rel, utc_txt
    local = pulled_at.astimezone(_LOCAL_TZ)
    # Build 12-hour time by hand: the %-I / %#I no-pad flags are platform-specific.
    hour12 = local.strftime("%I").lstrip("0") or "12"
    stamp = f"{local.strftime('%b %d, %Y')} {hour12}:{local.strftime('%M %p')}"
    return rel, f"{stamp} {local.tzname()} ({utc_txt})"


# ══════════════════════════════════════════════════════════════════════════════
# CHROME BUILDERS
# ══════════════════════════════════════════════════════════════════════════════
def header_title_html(pulled_at: datetime | None = None) -> str:
    """The header's left fragment: identity and freshness.

    ONE fragment, because the title and the As Of / Data Pulled line share a
    baseline (``.hdr-title-group``). The navy card around it is the
    ``chrome_hdr`` container, and Refresh follows this fragment in that row.

    The template shows "AS OF <month>", but ``VAULT_INVENTORY_V`` is an SCD2 view
    with no as-of dimension and the query pins the open record — there is no
    period to name. So the field reads Live Snapshot and is paired with a real
    Data Pulled stamp, which is the question a reader actually has.
    """
    fresh = ""
    if pulled_at is not None:
        rel, abs_txt = freshness_label(pulled_at)
        fresh = ('<span class="dataset-sep">&middot;</span>'
                 '<label class="dataset-label">Data Pulled</label>'
                 f'<span class="dataset-value dim" title="Last query against Snowflake: '
                 f'{escape(abs_txt)}">{escape(rel)}</span>')
    return (
        '<div class="hdr-title-group">'
        '<div class="logo">Vault Inventory / Dealernet</div>'
        '<div class="dataset-selector-wrap">'
        '<label class="dataset-label">As Of</label>'
        '<span class="dataset-value" title="VAULT_INVENTORY_V is an SCD2 view with no '
        'as-of dimension; the query pins the currently-open record.">Live Snapshot</span>'
        f'{fresh}'
        "</div></div>"
    )


def header_meta_html(meta: dict) -> str:
    """The header's right fragment: the three headline facts."""
    return (
        '<div class="hdr-meta">'
        f'<div>SKUs<b>{tx.fmtq(meta["skus"])}</b></div>'
        f'<div>Licensors<b>{tx.fmtq(meta["brands"])}</b></div>'
        f'<div>Total Value<b>{tx.fmt_abbr(meta["total_val"])}</b></div>'
        "</div>"
    )


def filter_badge_html() -> str:
    """The template's FILTERED pill, shown only while a filter is narrowing."""
    return '<span class="filter-badge">Filtered</span>' 


def legend_html() -> str:
    """The aging ramp — the encoding shared by both donuts and the table chips."""
    items = "".join(
        f'<div class="legend-item"><div class="legend-dot" style="background:'
        f'{tx.AGING_COLOR[b]}"></div>{escape(b)}</div>'
        for b in tx.AGING_ORDER
    )
    return f'<div class="legend">{items}</div>'


def section_label_html(text: str) -> str:
    return f'<div class="section-label">{escape(text)}</div>'


def _count(n: int, noun: str) -> str:
    """``1 brand`` / ``10 brands``: a count with its noun agreeing."""
    return f"{tx.fmtq(n)} {noun}" if n == 1 else f"{tx.fmtq(n)} {noun}s"


def stat_cards_html(c: dict) -> str:
    """The six KPI cards, in the workbook's order.

    Wholesale Value, Potential Profit and the markup chip are on the table's
    basis (priced SKUs, 80% of the DN price), so each ties to its footer total.
    See ``transforms.stat_cards``. The unpriced count appears once, on the
    Wholesale card; the Profit card carries the unpriced cost in its tooltip
    only. The Wholesale tooltip names the gross Market Value (unadjusted DN), the
    one place that figure appears on the cards.
    """
    def card(cls: str, label: str, value: str, sub: str, color: str | None = None,
             title: str | None = None) -> str:
        style = f' style="color:{color}"' if color else ""
        tip = f' title="{escape(title)}"' if title else ""
        return (
            f'<div class="stat-card {cls}"{tip}>'
            f'<div class="stat-card-label">{label}</div>'
            f'<div class="stat-card-value"{style}>{value}</div>'
            f'<div class="stat-card-sub">{sub}</div>'
            "</div>"
        )

    factor = f"{tx.WHOLESALE_FACTOR:.0%}"
    wholesale, profit, mkt = c["wholesale"], c["profit"], c["market"]
    priced_n, unpriced_n = c["priced_skus"], c["unpriced_skus"]

    # The cards render before the page's empty-result guard, so a view with no
    # SKUs at all gets neither note.
    unpriced_note = (
        f' &middot; <span class="sub-neg">{_count(unpriced_n, "SKU")} not priced</span>'
        if unpriced_n else " &middot; all SKUs priced" if priced_n else ""
    )
    wholesale_tip = (
        f"{tx.fmt(wholesale)} Wholesale Value ({factor} of Dealernet). "
        f"Market Value (unadjusted DN): {tx.fmt(mkt)}. {_count(priced_n, 'priced SKU')}."
        if wholesale is not None else "No priced SKUs in this view."
    )

    profit_tip = (
        f"{tx.fmt(profit)} = Wholesale Value − Inventory Value over "
        f"{_count(priced_n, 'priced SKU')}."
        if profit is not None else "No priced SKUs in this view."
    )
    if unpriced_n and profit is not None:
        profit_tip += (f" Excludes {tx.fmt(c['unpriced_cost'])} of cost on "
                       f"{_count(unpriced_n, 'unpriced SKU')}.")
    markup_chip = (
        "" if c["markup"] is None
        else f' &middot; <span class="chip chip-up">{tx.fmt_mult(c["markup"])} markup</span>'
    )
    profit_color = (None if profit is None
                    else "var(--band-dealernet)" if profit >= 0 else "var(--neg)")

    return (
        '<div class="stat-cards">'
        + card("", "&#9670; # of Products", tx.fmtq(c["products"]),
               _count(c["brand_buckets"], "brand"))
        + card("", "&#9670; # of SKUs", tx.fmtq(c["skus"]),
               _count(c["box_types"], "box type"))
        + card("", "&#9670; # of Cases", tx.fmtq_abbr(c["cases"]),
               f'{tx.fmtq(c["cases"])} cases on hand')
        + card("stat-card-total", "Inventory Value", tx.fmt_abbr(c["inv_val"]),
               "Oracle standard cost", "var(--gold)")
        + card("stat-card-market", "&#9670; Wholesale Value", tx.fmt_abbr(wholesale),
               f"Dealernet &times; {factor}{unpriced_note}",
               None if wholesale is None else "var(--accent2)", wholesale_tip)
        + card("stat-card-margin", "&#9670; Potential Profit", tx.fmt_abbr(profit),
               f"Pre-royalty &middot; vs. Oracle basis{markup_chip}", profit_color, profit_tip)
        + "</div>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CHARTS (inline SVG / CSS — ports of donutSvg / donutLegend / hbars)
#
# Mounted through interactive.chart, which turns a click on any [data-pick]
# element into a page filter. ``selected`` is the chart's active filter value
# (or None) and ``pickable`` the labels a click may pick: the app passes the
# labels that have rows in the chart's own cross-filtered frame, so a pick can
# never empty the page. The selected label is always pickable, so it can be
# clicked off again.
# ══════════════════════════════════════════════════════════════════════════════
_DONUT = {"W": 150, "H": 150, "R": 56, "SW": 20}


def _pick_state(label: str, selected: str | None,
                pickable: frozenset[str]) -> tuple[bool, str]:
    """``(clickable, highlight class)`` for one chart item.

    The class is ``is-sel`` for the selected item, ``is-dim`` for every other
    item while a selection is active, and empty when there is none.
    """
    can = label in pickable or (selected is not None and label == selected)
    state = "" if selected is None else "is-sel" if label == selected else "is-dim"
    return can, state


def _pick_attrs(label: str, can: bool, state: str, *, keyboard: bool) -> str:
    """The click target's attributes: ``data-pick``, plus the keyboard set."""
    if not can:
        return ""
    attrs = f' data-pick="{escape(label, quote=True)}"'
    if keyboard:
        pressed = "true" if state == "is-sel" else "false"
        attrs += f' tabindex="0" role="button" aria-pressed="{pressed}"'
    return attrs


def _pick_hint(can: bool, state: str) -> str:
    """The tooltip suffix naming what a click will do."""
    if not can:
        return ""
    return " · click to clear" if state == "is-sel" else " · click to filter"


def _cls(base: str, state: str) -> str:
    return f"{base} {state}" if state else base


def _donut_svg(rows: list[dict], fmt_fn, center_label: str, *,
               selected: str | None = None,
               pickable: frozenset[str] = frozenset()) -> str:
    """Arc ring with the net total in the middle.

    Negative values cannot be drawn: a negative ``stroke-dasharray`` renders
    nothing and would corrupt the cumulative offset for every arc after it. So
    the RING is scaled by the sum of positive values only, while the CENTRE shows
    the true net total (positives less negatives). The legend beside it still
    lists every bucket at its real value, so nothing is hidden — the ring is a
    composition of what is actually on hand.

    Arcs are mouse-only click targets; the legend rows carry the keyboard path.
    """
    w, h, r, sw = _DONUT["W"], _DONUT["H"], _DONUT["R"], _DONUT["SW"]
    cx, cy = w / 2, h / 2
    circumference = 2 * 3.141592653589793 * r

    net_total = sum(row["value"] for row in rows)
    positives = [row for row in rows if row["value"] > 0]
    arc_total = sum(row["value"] for row in positives)

    if arc_total <= 0:
        return (
            f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#eef1f6" stroke-width="{sw}"/>'
            f'<text x="{cx}" y="{cy + 4}" text-anchor="middle" class="donut-center-lbl">'
            "NO DATA</text></svg>"
        )

    arcs, cum = [], 0.0
    for row in positives:
        label = str(row["label"])
        can, state = _pick_state(label, selected, pickable)
        cls = f' class="{state}"' if state else ""
        length = row["value"] / arc_total * circumference
        pct = row["value"] / arc_total * 100
        arcs.append(
            f'<circle{cls} cx="{cx}" cy="{cy}" r="{r}" fill="none"'
            f' stroke="{row["color"]}" stroke-width="{sw}"'
            f' stroke-dasharray="{length:.2f} {circumference - length:.2f}"'
            f' stroke-dashoffset="{-cum:.2f}"'
            f'{_pick_attrs(label, can, state, keyboard=False)}>'
            f'<title>{escape(label)}: {fmt_fn(row["value"])} ({pct:.1f}%)'
            f'{_pick_hint(can, state)}</title>'
            "</circle>"
        )
        cum += length

    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#eef1f6" stroke-width="{sw}"/>'
        f'<g transform="rotate(-90 {cx} {cy})">{"".join(arcs)}</g>'
        f'<text x="{cx}" y="{cy - 1}" text-anchor="middle" class="donut-center-val">'
        f"{fmt_fn(net_total)}</text>"
        f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" class="donut-center-lbl">'
        f"{escape(center_label)}</text>"
        "</svg>"
    )


def _donut_legend(rows: list[dict], fmt_fn, *, selected: str | None = None,
                  pickable: frozenset[str] = frozenset()) -> str:
    """Itemised legend: dot, label, value, share of the positive total.

    The legend is zero-filled, so the selected bucket always has a row to click
    off, even when its value leaves it no arc.
    """
    arc_total = sum(row["value"] for row in rows if row["value"] > 0)
    out = []
    for row in rows:
        label = str(row["label"])
        can, state = _pick_state(label, selected, pickable)
        pct = (row["value"] / arc_total * 100) if arc_total > 0 else 0.0
        out.append(
            f'<div class="{_cls("donut-legend-row", state)}"'
            f'{_pick_attrs(label, can, state, keyboard=True)}>'
            f'<span class="dl-dot" style="background:{row["color"]}"></span>'
            f'<span class="dl-label">{escape(label)}</span>'
            f'<span class="dl-val">{fmt_fn(row["value"])}</span>'
            f'<span class="dl-pct">{pct:.1f}%</span>'
            "</div>"
        )
    return '<div class="donut-legend">' + "".join(out) + "</div>"


def donut_card_html(title_prefix: str, title_bold: str, rows: list[dict],
                    fmt_fn, center_label: str, *, selected: str | None = None,
                    pickable: frozenset[str] = frozenset()) -> str:
    """A full donut panel: titled card, ring, and legend.

    The centre shows the net total of every bucket in ``rows``; the selection is
    carried by the highlight, not by the total.
    """
    return (
        '<div class="chart-wrap">'
        f'<div class="chart-title">{escape(title_prefix)} <b>{escape(title_bold)}</b></div>'
        '<div class="donut-row">'
        + _donut_svg(rows, fmt_fn, center_label, selected=selected, pickable=pickable)
        + _donut_legend(rows, fmt_fn, selected=selected, pickable=pickable)
        + "</div></div>"
    )


def hbars_card_html(title_prefix: str, title_bold: str, rows: list[dict], fmt_fn, *,
                    selected: str | None = None,
                    pickable: frozenset[str] = frozenset(),
                    neg_below: float = 0.0, sub: str | None = None,
                    empty: str = "No inventory matches these filters.") -> str:
    """Sorted horizontal bars — used for brand buckets, which have 10 categories.

    Bar width is scaled by the largest ABSOLUTE value so a negative bucket still
    renders a visible bar; bars below ``neg_below`` are tinted red rather than given a negative
    width, which would silently draw nothing. ``neg_below`` is 0 for amounts and
    1.0 for markup multiples (wholesale below cost).

    A row's optional ``tip`` joins its tooltip. ``sub`` is a basis line under the
    title. A ``selected`` label with no row (its bucket summed to zero or was
    dropped) gets a placeholder row at the bottom, an empty track and an em dash,
    so it can still be clicked off.
    """
    head = ('<div class="chart-wrap">'
            f'<div class="chart-title">{escape(title_prefix)} <b>{escape(title_bold)}</b></div>'
            + (f'<div class="chart-sub">{escape(sub)}</div>' if sub else ""))
    if selected is not None and selected not in {str(row["label"]) for row in rows}:
        rows = rows + [{"label": selected, "value": None, "color": ""}]
    if not rows:
        return head + f'<div class="no-data">{escape(empty)}</div></div>'

    scale = max((abs(row["value"]) for row in rows if row["value"] is not None),
                default=0.0) or 1.0
    bars = []
    for row in rows:
        label, v = str(row["label"]), row["value"]
        can, state = _pick_state(label, selected, pickable)
        fill = ""
        if v is not None:
            color = "var(--neg)" if v < neg_below else row["color"]
            fill = (f'<span class="hbar-fill" style="background:{color};'
                    f'width:{abs(v) / scale * 100:.1f}%"></span>')
        tip = f"{label}: {fmt_fn(v)}"
        if row.get("tip"):
            tip += f" · {row['tip']}"
        bars.append(
            f'<div class="{_cls("hbar-row", state)}"'
            f' title="{escape(tip + _pick_hint(can, state))}"'
            f'{_pick_attrs(label, can, state, keyboard=True)}>'
            f'<span class="hbar-label">{escape(label)}</span>'
            f'<span class="hbar-track">{fill}</span>'
            f'<span class="hbar-val">{fmt_fn(v)}</span>'
            "</div>"
        )
    return head + '<div class="hbars">' + "".join(bars) + "</div></div>"


# ══════════════════════════════════════════════════════════════════════════════
# CELL BUILDERS
# ══════════════════════════════════════════════════════════════════════════════
def _null_cell() -> str:
    return f'<span style="color:#b8c2d4">{tx.NULL_CELL}</span>'


def _aging_chip(bucket) -> str:
    label = str(bucket)
    color = tx.AGING_COLOR.get(label, "#b8c2d4")
    return f'<span class="chip chip-age" style="background:{color}">{escape(label)}</span>'


def _blank(v) -> bool:
    """None, NaN, NaT or pd.NA: a field the row does not carry."""
    return v is None or (not isinstance(v, str) and pd.isna(v))


# price_status -> (pill class, chip word). The words are README decision 16.
_PRICE_PILLS = {
    tx.PRICE_LIVE: ("pill-live", "LIVE"),
    tx.PRICE_STALE: ("pill-stale", "STALE PRICE"),
    tx.PRICE_NONE: ("pill-none", "NO PRICE"),
}


def _price_status_pill(row) -> str:
    """The detail panel's Price Status chip: LIVE / STALE PRICE / NO PRICE.

    Reads ``price_status`` (data.load_inventory: No Price when there is no
    Dealernet price, else Stale past ``tx.STALE_DAYS`` or with no sale date,
    else Live). Stale is a confidence warning, not a missing price: its value
    still counts everywhere. The tooltip repeats the age from ``dn_age_days``;
    the panel's sub-line spells it out, since a tooltip alone is not
    discoverable.
    """
    cls, word = _PRICE_PILLS.get(row.get("price_status"), _PRICE_PILLS[tx.PRICE_NONE])
    age = row.get("dn_age_days")
    tip = ""
    if cls != "pill-none" and not _blank(age):
        tip = (f' title="Last Dealernet case sale {_count(age, "day")} before the data '
               f'pull (stale above {tx.STALE_DAYS})"')
    return f'<span class="status-pill {cls}"{tip}>{word}</span>'


def _signed(v, fmt_fn) -> str:
    """Green when >= 0, red when negative — the template's convention."""
    if v is None or pd.isna(v):
        return _null_cell()
    color = "var(--pos)" if float(v) >= 0 else "var(--neg)"
    return f'<span style="color:{color}">{fmt_fn(v)}</span>'


def _text_cell(key: str):
    def fn(row):
        v = row[key]
        if v is None or (not isinstance(v, str) and pd.isna(v)):
            return _null_cell()
        return escape(str(v))
    return fn


def _num_cell(key: str, fmt_fn):
    def fn(row):
        return fmt_fn(row[key])
    return fn


def _date_cell(key: str):
    def fn(row):
        return tx.fmt_date(row[key])
    return fn


def _sum_total(key: str, fmt_fn):
    def fn(totals):
        return fmt_fn(totals.get(key))
    return fn


# ══════════════════════════════════════════════════════════════════════════════
# COLUMN SPEC — mirrors the template's GROUPS array.
#
# A group is (label, header_css, [columns]); a column is
# (key, header, td_css, sort_type, cell_fn, total_fn, title). One definition
# drives the two-row header, the body rows and the footer totals, so nothing can
# drift out of alignment. The set is the workbook's, trimmed to 15 columns (plan
# 05): Dealernet Name, the canonical licensor, Pack Config and Dealernet Match
# moved to the detail panel and the export, and the Inventory and Margin groups
# were reordered.
# ══════════════════════════════════════════════════════════════════════════════
def _col(key, header, td, sort_type, cell, total=None, title=None):
    return {"key": key, "header": header, "td": td, "sort": sort_type,
            "cell": cell, "total": total, "title": title}


def _mult(v) -> str:
    """Markup multiple: neutral text, red only below 1.0x (worth less than it cost).

    README decision 15. Every SKU is above 1.0x today, so green would turn the
    whole column green and hide nothing. Red still flags the rows where, for a
    positive-cost row, profit is negative.
    """
    if v is None or pd.isna(v):
        return _null_cell()
    if float(v) < 1.0:
        return f'<span style="color:var(--neg)">{tx.fmt_mult(v)}</span>'
    return tx.fmt_mult(v)


def _name_cell(r) -> str:
    # The cell ellipsizes at max-width; the title carries the full name.
    name = escape(str(r["product_name"] or ""))
    return f'<span title="{name}">{name}</span>'


def _adj_dn_cell(r) -> str:
    # The dot goes BEFORE the number so right-aligned digits stay aligned.
    dot = ""
    if r.get("price_status") == tx.PRICE_STALE:
        dot = ('<span class="stale-dot" title="Stale price: last Dealernet sale '
               f'{tx.fmt_date(r["dn_latest_date"])}"></span>')
    return dot + tx.fmt(r["adj_dn_price_per_case"])


GROUPS = [
    # The anchor column sits outside every band: black header, pinned.
    ("", "", [
        _col("product_name", "Product Name (Oracle)", "", "text", _name_cell),
    ]),
    ("&#9670; Identity", "th-identity", [
        _col("box_type", "Box Type", "td-left", "text", _text_cell("box_type")),
        _col("item_number", "Item Number", "td-left td-code", "text", _text_cell("item_number")),
        _col("brand_bucket", "Brand", "td-left td-muted", "text", _text_cell("brand_bucket")),
    ]),
    ("&#9670; Inventory", "th-inventory", [
        _col("street_date", "Street Date", "td-muted", "num", _date_cell("street_date")),
        _col("aging_bucket", "Aging Bucket", "td-left", "text",
             lambda r: _aging_chip(r["aging_bucket"])),
        # Fractional when a key holds -DB boxes or -PCK packs (0.50, 53.25).
        _col("quantity_cases", "Qty (Cases)", "", "num",
             _num_cell("quantity_cases", tx.fmt_cases),
             _sum_total("quantity_cases", tx.fmt_cases)),
        _col("inventory_value", "Inventory Value", "td-total", "num",
             _num_cell("inventory_value", tx.fmt), _sum_total("inventory_value", tx.fmt)),
    ]),
    ("&#9670; Pricing", "th-pricing", [
        _col("unit_cost_per_case", "Unit Cost / Case", "", "num",
             _num_cell("unit_cost_per_case", tx.fmt)),
        _col("adj_dn_price_per_case", "Adj. DN Price / Case", "", "num", _adj_dn_cell,
             title="Dealernet average case sale × 80% — the price behind Wholesale Value"),
        _col("wholesale_value", "Wholesale Value", "", "num",
             _num_cell("wholesale_value", tx.fmt), _sum_total("wholesale_value", tx.fmt)),
    ]),
    ("&#9670; Margin", "th-margin", [
        _col("total_potential_profit", "Potential Profit", "", "num",
             lambda r: _signed(r["total_potential_profit"], tx.fmt),
             _sum_total("total_potential_profit", tx.fmt)),
        _col("margin_dollars_per_case", "Margin $ / Case", "", "num",
             lambda r: _signed(r["margin_dollars_per_case"], tx.fmt)),
        # Footer ratios are recomputed from sums in transforms.table_totals,
        # never averaged across rows.
        _col("margin_pct", "Margin %", "", "num",
             lambda r: _signed(r["margin_pct"], tx.fmt_pct), _sum_total("margin_pct", tx.fmt_pct)),
        _col("markup_multiple", "Markup Multiple", "", "num",
             lambda r: _mult(r["markup_multiple"]), _sum_total("markup_multiple", tx.fmt_mult),
             title="Wholesale Value ÷ Inventory Value"),
    ]),
]

COLUMNS = [c for _label, _css, cols in GROUPS for c in cols]
COLUMN_BY_KEY = {c["key"]: c for c in COLUMNS}


def _td_attr(col: dict) -> str:
    """``class="..."`` attribute for a body/footer cell, or empty when unstyled."""
    return f' class="{col["td"]}"' if col["td"] else ""


def product_table_html(df: pd.DataFrame, totals: dict, *, selected: str | None,
                       sort_col: str, sort_asc: bool) -> str:
    """15-column banded product table (anchor + four groups).

    Rows carry ``data-key`` (the item number) and header cells carry
    ``data-sort`` (the column key); ``interactive.table`` binds click listeners to
    both. No inline ``onclick`` — the SiS content-security policy forbids it, and
    the component's JS is the supported path. The headers are the only sort
    control, so each carries a tooltip: the column's own ``title`` where one is
    set, otherwise the click hint.
    """
    ghead = ['<tr class="col-group-header">']
    chead = ["<tr>"]
    for glabel, gcss, cols in GROUPS:
        if glabel == "":
            ghead.append("<th></th>")
        else:
            ghead.append(f'<th colspan="{len(cols)}" class="{gcss}">{glabel}</th>')
        for c in cols:
            classes = [gcss] if gcss else []
            if c["td"] == "td-total":
                classes.append("td-total")
            if c["key"] == sort_col:
                classes.append("sorted")
            cls = f' class="{" ".join(classes)}"' if classes else ""
            arrow = ("↑" if sort_asc else "↓") if c["key"] == sort_col else "↕"
            dim = "" if c["key"] == sort_col else ' style="opacity:.45"'
            # Headers are otherwise raw HTML, so the title must be escaped.
            tip = escape(c["title"] or "Click to sort; click again to reverse")
            chead.append(
                f'<th{cls} data-sort="{escape(c["key"])}" title="{tip}">{c["header"]}'
                f'<span class="sort-arrow"{dim}>{arrow}</span></th>'
            )
    ghead.append("</tr>")
    chead.append("</tr>")

    ncols = len(COLUMNS)
    body = []
    for _i, row in df.iterrows():
        key = str(row["item_number"])
        sel = ' class="selected"' if selected is not None and key == selected else ""
        cells = "".join(f"<td{_td_attr(c)}>{c['cell'](row)}</td>" for c in COLUMNS)
        body.append(f'<tr data-key="{escape(key)}"{sel}>{cells}</tr>')
    # The page stops on an empty dropdown slice before the table is built, so
    # the only way to reach an empty table is a search with no match.
    if not body:
        body = [f'<tr><td class="no-data" colspan="{ncols}">'
                "No products match this search.</td></tr>"]

    # Footer totals cover the WHOLE filtered set, which is the same set the table
    # renders (there is no pagination; rows past the 25-row cap scroll), so the
    # numbers tie to the table and, with the search empty, to the Cases and
    # Inventory Value tiles. The market tiles are gross; see transforms.stat_cards.
    fcells = [f'<td>TOTAL ({tx.fmtq(totals.get("_rows", len(df)))} SKUs)</td>']
    for c in COLUMNS[1:]:
        fcells.append(f"<td{_td_attr(c)}>{c['total'](totals) if c['total'] else ''}</td>")
    foot = '<tr class="tfoot-row">' + "".join(fcells) + "</tr>"

    return ('<div class="table-wrap"><table><thead>'
            + "".join(ghead) + "".join(chead)
            + "</thead><tbody>" + "".join(body)
            + "</tbody><tfoot>" + foot + "</tfoot></table></div>")


def detail_panel_html(row) -> str:
    """Inline drill-down panel for one SKU: 12 tiles in a fixed 4-column grid.

    Three rows, so the columns line up as cost over market over margin:

    * Inventory: Street Date (with its aging chip), Qty (Cases), Pack Config,
      Inventory Value (with the unit cost per case).
    * Dealernet: Price Status (LIVE / STALE PRICE / NO PRICE, with the last sale,
      its age and the sale count), Dealernet Name (with the year match), DN Price
      / Case (the full average case sale, with the 80% price), Wholesale Value.
    * Margin: Potential Profit, Margin $ / Case, Margin %, Markup Multiple.

    The header badges are the item key, the brand bucket and the licensor.

    Per-case figures come from the per-case columns, never value ÷ qty: a key can
    merge a ``-CSE`` and a ``-DB`` row.
    An unpriced SKU shows an em dash on every Dealernet and margin tile. Without
    an Oracle cost, Margin $ / Case is an em dash too, since it would otherwise
    report the whole adjusted price as margin.

    The output goes straight to ``interactive.detail``, whose shell supplies the
    ``.fct`` wrapper, so it is NOT passed through ``render``. The component sets
    it with ``innerHTML``, which does no sanitising, so every data string is
    escaped here. An expanding panel rather than an overlay modal, matching the
    template (which has no true modals either).
    """
    def cell(label: str, value: str, color: str | None = None, sub: str | None = None,
             cls: str = "") -> str:
        style = f' style="color:{color}"' if color else ""
        val_cls = f"dc-val {cls}" if cls else "dc-val"
        sub_html = f'<div class="dc-sub">{sub}</div>' if sub else ""
        return (f'<div class="detail-cell"><div class="dc-lbl">{label}</div>'
                f'<div class="{val_cls}"{style}>{value}</div>{sub_html}</div>')

    factor = f"{tx.WHOLESALE_FACTOR:.0%}"
    priced = not _blank(row["dealernet_price_per_case"])
    qty = row["quantity_cases"]
    unit_cost = row["unit_cost_per_case"]
    has_cost = not _blank(unit_cost) and float(unit_cost) > 0
    adj = row["adj_dn_price_per_case"]

    # ── Inventory row ──
    street = f'{tx.fmt_date(row["street_date"])} {_aging_chip(row["aging_bucket"])}'
    qty_sub = "None on hand" if float(qty) <= 0 else None
    # A fractional Qty comes from -DB boxes / -PCK packs: name the physical holding
    # ("52 cases + 10 display boxes"). The case count is what is left of the
    # case-equivalents once the boxes and packs are taken out.
    boxes, packs = row.get("display_boxes"), row.get("loose_packs")
    boxes = 0.0 if _blank(boxes) else float(boxes)
    packs = 0.0 if _blank(packs) else float(packs)
    if boxes or packs:
        bpc = pd.to_numeric(row.get("boxes_per_case"), errors="coerce")
        ppb = pd.to_numeric(row.get("packs_per_box"), errors="coerce")
        cases = float(qty)
        if boxes and pd.notna(bpc) and bpc:
            cases -= boxes / bpc
        if packs and pd.notna(bpc) and bpc and pd.notna(ppb) and ppb:
            cases -= packs / (bpc * ppb)
        held = [f"{tx.fmt_cases(cases)} case{'' if round(cases, 2) == 1 else 's'}"
                ] if round(cases, 2) else []
        if boxes:
            held.append(f"{tx.fmt_cases(boxes)} display box{'' if boxes == 1 else 'es'}")
        if packs:
            held.append(f"{tx.fmt_cases(packs)} pack{'' if packs == 1 else 's'}")
        qty_sub = " + ".join(held)
    pack = " × ".join(tx.fmt_int(row[k]) for k in
                      ("boxes_per_case", "packs_per_box", "cards_per_pack"))
    cost_sub = f"{tx.fmt(unit_cost)} / case unit cost" if has_cost else "No Oracle cost"

    # ── Dealernet row ──
    if priced:
        latest, age = row["dn_latest_date"], row["dn_age_days"]
        parts = [f"Last DN sale {tx.fmt_date(latest)}" if not _blank(latest)
                 else "Last DN sale date unknown"]
        if not _blank(age):
            parts.append("today" if age == 0 else f"{_count(age, 'day')} ago")
        if not _blank(row["dn_listing_count"]):
            parts.append(_count(row["dn_listing_count"], "sale"))
        status_sub = " &middot; ".join(parts)
        if row["price_status"] == tx.PRICE_STALE:
            status_sub = f'<span class="sub-stale">{status_sub}</span>'
    else:
        status_sub = "No Dealernet case sales matched"
    dn_name = "" if _blank(row["dealernet_name"]) else str(row["dealernet_name"]).strip()
    match = row["year_match_type"]
    name_sub = escape(str(match)) if priced and not _blank(match) else None

    return (
        '<div class="detail-panel">'
        '<div class="detail-panel-header">'
        f'<div class="detail-panel-title">{escape(str(row["product_name"] or ""))}</div>'
        # item_key: the product, whichever of its case / -DB / -PCK rows the
        # table's item_number names.
        + "".join(f'<span class="detail-count-badge">{escape(str(row[k]))}</span>'
                  for k in ("item_key", "brand_bucket", "brand") if not _blank(row[k]))
        + "</div>"
        '<div class="detail-grid">'
        + cell("Street Date", street)
        + cell("Qty (Cases)", tx.fmt_cases(qty), sub=qty_sub)
        + cell("Pack Config", pack, sub="Boxes &middot; packs &middot; cards")
        + cell("Inventory Value", tx.fmt(row["inventory_value"]), "var(--gold)", cost_sub)
        + cell("Price Status", _price_status_pill(row), sub=status_sub)
        + cell("Dealernet Name", escape(dn_name) if dn_name else _null_cell(),
               sub=name_sub, cls="dc-text")
        + cell("DN Price / Case",
               tx.fmt(row["dealernet_price_per_case"]) if priced else _null_cell(),
               sub=f"{tx.fmt(adj)} at {factor}" if priced else None)
        + cell("Wholesale Value",
               tx.fmt(row["wholesale_value"]) if priced else _null_cell(),
               "var(--accent2)" if priced else None,
               f"{tx.fmt(adj)} / case (DN × {factor})" if priced else "Not priced")
        + cell("Potential Profit", _signed(row["total_potential_profit"], tx.fmt),
               sub="Pre-royalty" if priced else None)
        + cell("Margin $ / Case",
               _signed(row["margin_dollars_per_case"], tx.fmt) if has_cost else _null_cell())
        + cell("Margin %", _signed(row["margin_pct"], tx.fmt_pct))
        + cell("Markup Multiple", _mult(row["markup_multiple"]))
        + "</div></div>"
    )
