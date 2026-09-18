"""Pixel-faithful chrome: CSS + HTML/SVG builders ported from the HTML template.

``vault_inventory_dashboard.html`` was written as a port spec — it keeps the
sibling relic dashboard's class names so this module can adapt that stylesheet
rather than rewrite it. Two structural changes were unavoidable:

**Rescoping.** The template styles bare elements (``body``, ``header``, ``table``,
``td``, ``thead th``). Every selector here is scoped under a ``.fct`` wrapper so
it cannot collide with Streamlit's own DOM, and ``:root`` variables move onto
``.fct``. ``position: sticky`` on the header is dropped — Streamlit owns the
scroll container — so the header renders as a card.

**Splitting.** Page styles cannot pierce a Custom Component's shadow root, so the
product table's CSS ships separately as ``TABLE_CSS`` (injected into the
component) while the page chrome uses ``CSS``. Rules needed on both sides
(chips, status pills, tokens) live in the shared blocks and are concatenated into
each.

The donut and horizontal-bar charts are built here as inline SVG/CSS rather than
handed to Altair: the template's donut pairs an arc ring with an itemised
value+percentage legend beside it, and its bars are a label/track/value grid.
Reproducing those in Altair would approximate the design instead of porting it.
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
# Two faces: Inter for everything visible, DM Mono for micro-labels. The relic
# dashboard these merge into is Inter-only, so there is deliberately no display
# face here — the logo and section labels use weighted Inter instead.
# The template referenced 'DM Mono' 37 times without ever fetching it; this port
# actually loads it. If the host cannot reach fonts.googleapis.com the stack
# falls back to system faces: micro-label typography changes, layout does not.
_FONT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Inter:wght@400;500;600;700&display=swap');
"""

# Tokens + box model. Needed in the page stylesheet for the chrome AND inside the
# table component, because page styles can't pierce the shadow root.
_TOKENS_CSS = """
.fct, .fct * { box-sizing: border-box; margin: 0; padding: 0; }
.fct {
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
  --band-pack:      #57534e;
  --band-pricing:   #155e63;
  --band-margin:    #8a6314;
  --band-dealernet: #5b3a8e;

  color: var(--text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
  font-size: 14px;
}
"""

# Chips and status pills appear in the table (shadow root) AND in the drill-down
# panel (page), so they are shared rather than duplicated.
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
  letter-spacing: .5px; white-space: nowrap; display: inline-block;
}
.fct .pill-live { background: #e8f5ec; color: #2a6e3f; }
.fct .pill-none { background: #fdecea; color: #9c2a22; }

.fct .no-data {
  text-align: center; padding: 40px;
  color: var(--muted); font-family: 'DM Mono', monospace; font-size: 13px;
  white-space: normal;
}
"""

_CHROME_CSS = """
/* ── HEADER ──────────────────────────────────────────────────────────────────
   The template's header element is sticky and full-bleed. Streamlit owns the
   scroll container, so it becomes a rounded card instead — same chrome, no
   sticking.

   NOTE: not one LESS-THAN character may appear anywhere in this stylesheet, not
   even inside a comment. st.html sanitizes with DOMPurify, whose SAFE_FOR_XML
   guard FORCE-REMOVES any element whose own text looks like markup (a less-than
   followed by a letter, "!" or "/") and it runs BEFORE the allowed-tags check. A
   style element is exactly that shape — its innerHTML is its text — so a single
   "header" written in angle brackets here silently deletes all 11 KB of page CSS
   and the whole dashboard renders as naked HTML. _checked() below is what makes
   that failure loud instead of silent. */
.fct .hdr {
  background: var(--navy);
  /* Only the TOP row lives in this card now. The MAPPING row below it is a native
     segmented control, which cannot sit inside an HTML string, so it becomes a
     separate navy strip: the card takes the top radius and zero bottom margin, the
     strip takes the bottom radius, and the two read as one header. */
  border-radius: 10px 10px 0 0;
  padding: 0 22px;
  margin-bottom: 0;
  box-shadow: 0 2px 8px rgba(0,0,0,.25);
  display: flex; flex-direction: column;
}
.fct .header-row { display: flex; align-items: center; gap: 20px; width: 100%; flex-wrap: wrap; }
.fct .header-row-top { padding: 12px 0; }
.fct .mapping-counts { display: flex; align-items: center; gap: 8px; }
.fct .hdr-vdiv {
  width: 2px; height: 20px; background: rgba(255,255,255,.5);
  margin: 0 6px; align-self: center; border-radius: 2px;
}
.fct .header-row-label {
  font-family: 'DM Mono', monospace;
  font-size: 10px; letter-spacing: 1px;
  color: var(--on-navy); white-space: nowrap;
}
.fct .logo {
  font-size: 24px; font-weight: 700; letter-spacing: 1px;
  color: #ffffff; line-height: 1;
}
.fct .logo span { color: var(--on-navy); font-size: 15px; font-weight: 600; }

.fct .dataset-selector-wrap { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fct .dataset-label {
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  color: var(--on-navy); letter-spacing: .5px; white-space: nowrap;
}
.fct .dataset-value {
  color: #fff; font-size: 13px; font-weight: 700;
  font-family: 'DM Mono', monospace;
}
.fct .dataset-value.dim { color: rgba(255,255,255,.85); font-size: 12px; font-weight: 400; }
.fct .dataset-sep { color: rgba(255,255,255,.4); margin: 0 6px; }

.fct .hdr-meta { margin-left: auto; display: flex; gap: 26px; row-gap: 10px; flex-wrap: wrap; }
.fct .hdr-meta > div {
  font-size: 10px; font-weight: 700; letter-spacing: .5px;
  color: var(--on-navy); text-transform: uppercase;
}
.fct .hdr-meta b {
  display: block; margin-top: 2px; color: #fff; font-size: 14px;
  font-variant-numeric: tabular-nums; letter-spacing: 0;
}
/* DATA PULLED carries a tooltip with the absolute timestamp; the dotted
   underline advertises that there is something to hover. width:fit-content is
   what makes the rule hug the text instead of spanning the whole column. */
.fct .hdr-meta .fresh { cursor: help; }
.fct .hdr-meta .fresh b { width: fit-content; border-bottom: 1px dotted #4d6a91; }

/* ── SECTION LABELS ─────────────────────────────────────────────────────────
   The template declares .section-label but renders .trend-title instead;
   revived here — it is the same ::after hairline device. Values match the relic
   dashboard's .sec-title so the two read alike once merged. */
.fct .section-label {
  font-size: 12px; font-weight: 700; letter-spacing: 1px;
  text-transform: uppercase;
  color: var(--muted);
  margin: 8px 0 12px;
  display: flex; align-items: center; gap: 10px;
}
.fct .section-label::after { content: ''; flex: 1; height: 1px; background: var(--border); }

/* ── LEGEND ─────────────────────────────────────────────────────────────────── */
.fct .legend { display: flex; gap: 20px; margin-bottom: 14px; flex-wrap: wrap; }
.fct .legend-item {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--muted); font-family: 'DM Mono', monospace;
}
.fct .legend-dot { width: 10px; height: 10px; border-radius: 2px; flex-shrink: 0; }

/* ── CONTEXT BAR ────────────────────────────────────────────────────────────── */
.fct .context-bar { display: flex; align-items: center; gap: 10px; margin: 0 0 14px; flex-wrap: wrap; }
.fct .context-status, .fct .context-view {
  font-family: 'DM Mono', monospace;
  font-size: 12px; font-weight: 700; letter-spacing: .8px;
  padding: 4px 11px; border-radius: 5px; color: #fff;
}
.fct .context-status { background: var(--gold); }
.fct .context-status.status-S { background: var(--accent2); }
.fct .context-status.status-O { background: var(--neg); }
.fct .context-sep { color: var(--muted); }
.fct .context-view { background: #5a7fbf; }
.fct .context-view.view-filtered { background: #7b52ab; }

/* .filter-badge - shown in the filter row whenever a filter is narrowing the view. */
.fct .filter-badge {
  font-family: 'DM Mono', monospace;
  font-size: 10px; letter-spacing: 1px;
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
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .7px; color: var(--muted); margin-bottom: 6px;
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

/* ── CHARTS ───────────────────────────────────────────────────────────────────
   The relic dashboard renders its charts through Altair, so their text picks up
   the theme font (Inter) rather than DM Mono, and they sit on the same surface
   treatment as its .table-wrap: radius 8px plus a soft shadow, no border. Both
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
  font-size: 12px; font-weight: 700; letter-spacing: 1px; color: var(--muted);
  text-transform: uppercase; margin-bottom: 14px;
}
.fct .chart-title b { color: var(--text); font-weight: 700; }

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
  font-size: 16px; font-weight: 700; color: #fff; letter-spacing: .5px;
}
.fct .detail-count-badge {
  background: rgba(255,255,255,.12);
  border: 1px solid rgba(255,255,255,.2);
  color: #c5d4ea;
  font-family: 'DM Mono', monospace;
  font-size: 11px; padding: 2px 8px; border-radius: 20px;
}
.fct .detail-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 1px; background: var(--border);
}
.fct .detail-cell { background: var(--surface); padding: 12px 16px; }
.fct .detail-cell .dc-lbl {
  font-size: 9px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .6px; color: var(--muted); margin-bottom: 4px;
}
.fct .detail-cell .dc-val { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
"""

_TABLE_CSS = """
/* ── TABLE ──────────────────────────────────────────────────────────────────── */
.fct .table-wrap {
  background: var(--surface);
  border-radius: 8px;
  overflow-x: auto;
  box-shadow: 0 1px 4px rgba(0,0,0,.08);
}
/* min-width:max-content is what lets the 22 columns size to their content and
   scroll sideways rather than compressing into illegibility. */
.fct table { width: 100%; min-width: max-content; border-collapse: collapse; table-layout: auto; }

.fct thead th {
  background: var(--navy);
  padding: 4px 5px;
  text-align: right;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .3px;
  text-transform: uppercase;
  color: #ffffff;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255,255,255,.08);
  cursor: pointer;
  user-select: none;
}
.fct thead th:first-child { text-align: left; background: #000000 !important; color: #fff !important; }
.fct thead th.sorted { color: var(--gold); }
.fct thead th .sort-arrow { margin-left: 4px; opacity: .6; }

.fct .col-group-header th {
  background: var(--navy-deep);
  color: #ffffff;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .3px;
  text-transform: uppercase;
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
.fct .th-pack      { background: var(--band-pack)      !important; color: #fff !important; border-bottom: none !important; }
.fct .th-pricing   { background: var(--band-pricing)   !important; color: #fff !important; border-bottom: none !important; }
.fct .th-margin    { background: var(--band-margin)    !important; color: #fff !important; border-bottom: none !important; }
.fct .th-dealernet { background: var(--band-dealernet) !important; color: #fff !important; border-bottom: none !important; }

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
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fct td.td-left  { text-align: left; }
.fct td.td-muted { color: var(--muted); }
.fct td.td-pos   { color: var(--pos); }
.fct td.td-neg   { color: var(--neg); }
.fct td.td-null  { color: #b8c2d4; }
.fct td.td-code  { font-family: 'DM Mono', monospace; font-size: 10px; }

.fct tbody tr[data-key] { cursor: pointer; }
.fct tbody tr:hover { background: var(--surface2); }
.fct tbody tr.selected { background: var(--selected-bg); border-left: 3px solid var(--selected-border); }
.fct tbody tr.selected td:first-child { padding-left: 13px; }

.fct .tfoot-row { background: var(--surface2); border-top: 2px solid var(--border); }
.fct .tfoot-row td { font-weight: 700; font-size: 10.5px; }

/* Bar-in-cell under the product name: cost / margin split per case. */
.fct .mix-bar-wrap {
  display: flex; gap: 2px; height: 4px;
  border-radius: 3px; overflow: hidden;
  width: 80px; margin-top: 3px;
}
.fct .mix-bar-seg { height: 100%; }
.fct .sub-label { color: var(--muted); font-size: 10px; font-weight: 400; }

/* STICKY: the 22-column table scrolls sideways, so the product name column is
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

# Streamlit's own widgets sit between the ported blocks; these few rules stop the
# default spacing from breaking the template's rhythm. Global, not .fct-scoped.
_STREAMLIT_CSS = """
/* The template packs its filter bar tightly; Streamlit's default block gap
   would spread the six controls over twice the height. */
div[data-testid="stHorizontalBlock"] { gap: 10px; }
/* Both emission wrappers add vertical rhythm the template does not want. The
   donuts go out through st.markdown rather than st.html (see render() below), and
   Streamlit gives every markdown container margin-bottom:-1rem to cancel the
   trailing paragraph margin of its OWN output - .fct content has no trailing
   paragraph, so that would pull the next block 16px upward. */
div[data-testid="stHtml"],
div[data-testid="stMarkdownContainer"]:has(> .fct) { line-height: 0; }
div[data-testid="stHtml"] > *,
div[data-testid="stMarkdownContainer"] > .fct { line-height: normal; }
div[data-testid="stMarkdownContainer"]:has(> .fct) { margin-bottom: 0; }
"""


# The template's own widget chrome (.status-toggle, .search-box, .filter-select,
# .sort-btn, .export-btn) has no markup in this port - native Streamlit controls
# stand in for it. These rules dress those controls to the template's spec, keyed
# off the st-key-* classes Streamlit emits for any widget or container with a key.
_WIDGET_CSS = """
/* MAPPING STRIP - the template's .header-row-bottom, closing the navy header. */
.st-key-chrome_map {
  background: var(--navy);
  border-radius: 0 0 10px 10px;
  padding: 7px 22px 9px;
  margin-bottom: 18px;
  box-shadow: 0 2px 8px rgba(0,0,0,.25);
}
.st-key-chrome_map div[data-testid="stHorizontalBlock"] { align-items: center; }

/* .status-toggle - one bordered group, hairline-separated segments, pastel actives.
   The per-segment active colors are positional: ALL / MAPPED / NO PRICE. */
.st-key-mapping div[data-testid="stButtonGroup"] {
  border: 1px solid rgba(255,255,255,.28);
  border-radius: 7px; overflow: hidden; gap: 0; width: fit-content;
}
.st-key-mapping div[data-testid="stButtonGroup"] button {
  font-family: 'DM Mono', monospace;
  font-size: 11px; font-weight: 600; letter-spacing: .5px;
  border: none; border-right: 1px solid rgba(255,255,255,.28); border-radius: 0;
  background: transparent; color: var(--on-navy-bright);
  padding: 4px 14px; min-height: 0;
}
.st-key-mapping div[data-testid="stButtonGroup"] button:last-child { border-right: none; }
.st-key-mapping div[data-testid="stButtonGroup"] button:hover {
  background: rgba(255,255,255,.10); color: #fff;
}
.st-key-mapping div[data-testid="stButtonGroup"] button[data-selected] {
  background: var(--surface2); color: var(--text);
}
.st-key-mapping div[data-testid="stButtonGroup"] button:nth-child(2)[data-selected] {
  background: #e8f5ec; color: #2a6e3f;
}
.st-key-mapping div[data-testid="stButtonGroup"] button:nth-child(3)[data-selected] {
  background: #fdecea; color: #9c2a22;
}

/* Refresh is a port addition, not in the template; give it the on-navy ghost look. */
.st-key-refresh button {
  font-family: 'DM Mono', monospace; font-size: 11px; letter-spacing: .5px;
  background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.28);
  color: var(--on-navy-bright); border-radius: 6px; padding: 4px 12px; min-height: 0;
}
.st-key-refresh button:hover {
  background: rgba(255,255,255,.16); color: #fff; border-color: rgba(255,255,255,.5);
}

/* FILTER BAR - .search-box and five .filter-select, all DM Mono on white. */
.st-key-chrome_flt { margin-bottom: 20px; }
.st-key-chrome_flt div[data-testid="stHorizontalBlock"] { align-items: center; }
div[class*="st-key-f_"] div[data-testid="stSelectbox"] { min-width: 120px; }
div[class*="st-key-f_"] input,
div[class*="st-key-f_"] div[data-testid="stSelectbox"] div[value] {
  font-family: 'DM Mono', monospace; font-size: 12px;
}
.st-key-f_search input { font-size: 13px; padding: 8px 14px; }

/* .sort-btn / .export-btn - ghost buttons on the page ground. */
.st-key-clear button, .st-key-export button {
  font-family: 'DM Mono', monospace; font-size: 11px; letter-spacing: .5px;
  background: none; border: 1px solid var(--border); color: var(--muted);
  border-radius: 6px; padding: 5px 12px; min-height: 0;
}
.st-key-clear button:hover, .st-key-export button:hover {
  border-color: var(--accent); color: var(--accent);
}

/* PRODUCT DETAIL controls - the same segmented idiom, on white rather than navy. */
div[class*="st-key-sort_"] div[data-testid="stButtonGroup"] {
  border: 1px solid var(--border);
  border-radius: 6px; overflow: hidden; gap: 0; width: fit-content;
}
div[class*="st-key-sort_"] div[data-testid="stButtonGroup"] button {
  font-family: 'DM Mono', monospace; font-size: 11px;
  border: none; border-right: 1px solid var(--border); border-radius: 0;
  background: var(--surface); color: var(--muted); padding: 5px 12px; min-height: 0;
}
div[class*="st-key-sort_"] div[data-testid="stButtonGroup"] button:last-child { border-right: none; }
div[class*="st-key-sort_"] div[data-testid="stButtonGroup"] button[data-selected] {
  background: var(--surface2); color: var(--text); font-weight: 600;
}
div[class*="st-key-sort_"] input, .st-key-rows input {
  font-family: 'DM Mono', monospace; font-size: 12px;
}
"""

_CSS_BODY = (_FONT_CSS + _TOKENS_CSS + _CHIP_CSS + _CHROME_CSS + _STREAMLIT_CSS
             + _WIDGET_CSS)

# Raw CSS (no <style> tag) for the table mounted via interactive.table — injected
# into the component's shadow root.
_TABLE_CSS_BODY = _TOKENS_CSS + _CHIP_CSS + _TABLE_CSS


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


def inject_css() -> None:
    st.html(CSS)


def open_fct() -> str:
    return '<div class="fct">'


def close_fct() -> str:
    return "</div>"


def wrap(*parts: str) -> str:
    """Bracket HTML fragments in the scoped wrapper for a single emission."""
    return open_fct() + "".join(parts) + close_fct()


def render(*parts: str, container=None, raw: bool = False) -> None:
    """Emit scoped chrome into ``container`` (default: the page).

    ``raw=True`` routes through ``st.markdown`` instead of ``st.html``, and is
    REQUIRED for anything containing SVG. ``st.html`` sanitizes with
    DOMPurify(USE_PROFILES={'html': True}), whose tag profile carries no svg set,
    and ``svg`` is in DOMPurify's FORBID_CONTENTS - so the element is dropped WITH
    its children and the donut rings vanish silently. The markdown renderer runs
    rehype-raw with no sanitizer and no element allow-list, so the SVG survives.

    ``st.html`` stays the default everywhere else: it is the stricter channel and it
    does not re-parse the payload as markdown. Inside a raw-HTML block remark does
    no inline processing, so a ``*`` or ``_`` in a product name is safe either way -
    but a NEWLINE in the data would close the block and hand the remainder to the
    markdown parser, so the raw path flattens them first.
    """
    body = wrap(*parts)
    target = st if container is None else container
    if raw:
        target.markdown(body.replace("\n", " "), unsafe_allow_html=True)
    else:
        target.html(body)


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
def header_html(meta: dict, pulled_at: datetime | None = None) -> str:
    """Header card: identity, freshness, and the three headline facts.

    The template shows "AS OF <month>", but ``VAULT_INVENTORY_V`` is an SCD2 view
    with no as-of dimension and the query pins the open record — there is no
    period to name. So the field reads LIVE SNAPSHOT and is paired with a real
    DATA PULLED stamp, which is the question a reader actually has.
    """
    fresh = ""
    if pulled_at is not None:
        rel, abs_txt = freshness_label(pulled_at)
        fresh = ('<span class="dataset-sep">&middot;</span>'
                 '<label class="dataset-label">DATA PULLED</label>'
                 f'<span class="dataset-value dim" title="Last query against Snowflake: '
                 f'{escape(abs_txt)}">{escape(rel)}</span>')
    return (
        '<div class="hdr">'
        '<div class="header-row header-row-top">'
        '<div class="logo">Vault Inventory <span>/ Dealernet</span></div>'
        '<div class="dataset-selector-wrap">'
        '<label class="dataset-label">AS OF</label>'
        '<span class="dataset-value" title="VAULT_INVENTORY_V is an SCD2 view with no '
        'as-of dimension; the query pins the currently-open record.">LIVE SNAPSHOT</span>'
        f'{fresh}'
        "</div>"
        '<div class="hdr-meta">'
        f'<div>SKUs<b>{tx.fmtq(meta["skus"])}</b></div>'
        f'<div>Brands<b>{tx.fmtq(meta["brands"])}</b></div>'
        f'<div>Total Value<b>{tx.fmt_abbr(meta["total_val"])}</b></div>'
        "</div></div></div>"
    )


def mapping_label_html() -> str:
    """The MAPPING micro-label, left of the native toggle in the navy strip."""
    return '<span class="header-row-label">MAPPING</span>'


def mapping_counts_html(meta: dict) -> str:
    """The live mapped / no-price counts, right of the native toggle.

    These and mapping_label_html() are the text of the template's
    .header-row-bottom; the toggle between them is a native segmented control, so
    the row is assembled in Streamlit rather than in one HTML string.
    """
    return (
        '<div class="mapping-counts">'
        '<div class="hdr-vdiv"></div>'
        f'<span class="header-row-label">{tx.fmtq(meta["mapped"])} MAPPED '
        f'&middot; {tx.fmtq(meta["no_price"])} NO PRICE</span>'
        "</div>"
    )


def filter_badge_html() -> str:
    """The template's FILTERED pill, shown only while a filter is narrowing."""
    return '<span class="filter-badge">FILTERED</span>' 


def context_bar_html(mapping: str, view_label: str, filtered: bool) -> str:
    scls = "" if mapping == "A" else f" status-{mapping}"
    vcls = " view-filtered" if filtered else ""
    return (
        '<div class="context-bar">'
        f'<span class="context-status{scls}">{tx.MAPPING_LABELS.get(mapping, "ALL MAPPING")}</span>'
        '<span class="context-sep">&middot;</span>'
        f'<span class="context-view{vcls}">{escape(view_label)}</span>'
        "</div>"
    )


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


def stat_cards_html(c: dict) -> str:
    """The six KPI cards, in the workbook's order.

    The margin card's markup chip is the like-for-like multiple over priced SKUs;
    the margin figure itself nets priced market value against ALL valuation, so
    the two deliberately do not reconcile. See ``transforms.stat_cards``.
    """
    def card(cls: str, label: str, value: str, sub: str, color: str | None = None) -> str:
        style = f' style="color:{color}"' if color else ""
        return (
            f'<div class="stat-card {cls}">'
            f'<div class="stat-card-label">{label}</div>'
            f'<div class="stat-card-value"{style}>{value}</div>'
            f'<div class="stat-card-sub">{sub}</div>'
            "</div>"
        )

    markup_chip = (
        "" if c["markup"] is None
        else f'<span class="chip chip-up">{tx.fmt_mult(c["markup"])} markup</span>'
    )
    return (
        '<div class="stat-cards">'
        + card("", "&#9670; # of Products", tx.fmtq(c["products"]),
               f'{c["brand_buckets"]} brand buckets')
        + card("", "&#9670; # of SKUs", tx.fmtq(c["skus"]),
               f'{c["box_types"]} box types')
        + card("", "&#9670; # of Cases", tx.fmtq_abbr(c["cases"]),
               f'{tx.fmtq(c["cases"])} cases on hand')
        + card("stat-card-total", "Inventory Valuation", tx.fmt_abbr(c["inv_val"]),
               "Oracle basis", "var(--gold)")
        + card("stat-card-market", "&#9670; Current Market Value", tx.fmt_abbr(c["mkt_val"]),
               f'Dealernet basis &middot; {c["priced_skus"]} priced SKUs', "var(--accent2)")
        + card("stat-card-margin", "&#9670; Unrealized Gross Margin", tx.fmt_abbr(c["margin"]),
               f"Pre-royalty &middot; vs. Oracle basis {markup_chip}",
               "var(--band-dealernet)" if c["margin"] >= 0 else "var(--neg)")
        + "</div>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CHARTS (inline SVG / CSS — ports of donutSvg / donutLegend / hbars)
# ══════════════════════════════════════════════════════════════════════════════
_DONUT = {"W": 150, "H": 150, "R": 56, "SW": 20}


def _donut_svg(rows: list[dict], fmt_fn, center_label: str) -> str:
    """Arc ring with the net total in the middle.

    Negative values cannot be drawn: a negative ``stroke-dasharray`` renders
    nothing and would corrupt the cumulative offset for every arc after it. So
    the RING is scaled by the sum of positive values only, while the CENTRE shows
    the true net total (positives less negatives). The legend beside it still
    lists every bucket at its real value, so nothing is hidden — the ring is a
    composition of what is actually on hand.
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
        length = row["value"] / arc_total * circumference
        pct = row["value"] / arc_total * 100
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none"'
            f' stroke="{row["color"]}" stroke-width="{sw}"'
            f' stroke-dasharray="{length:.2f} {circumference - length:.2f}"'
            f' stroke-dashoffset="{-cum:.2f}">'
            f'<title>{escape(str(row["label"]))}: {fmt_fn(row["value"])} ({pct:.1f}%)</title>'
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


def _donut_legend(rows: list[dict], fmt_fn) -> str:
    """Itemised legend: dot, label, value, share of the positive total."""
    arc_total = sum(row["value"] for row in rows if row["value"] > 0)
    out = []
    for row in rows:
        pct = (row["value"] / arc_total * 100) if arc_total > 0 else 0.0
        out.append(
            '<div class="donut-legend-row">'
            f'<span class="dl-dot" style="background:{row["color"]}"></span>'
            f'<span>{escape(str(row["label"]))}</span>'
            f'<span class="dl-val">{fmt_fn(row["value"])}</span>'
            f'<span class="dl-pct">{pct:.1f}%</span>'
            "</div>"
        )
    return '<div class="donut-legend">' + "".join(out) + "</div>"


def donut_card_html(title_prefix: str, title_bold: str, rows: list[dict],
                    fmt_fn, center_label: str) -> str:
    """A full donut panel: titled card, ring, and legend."""
    return (
        '<div class="chart-wrap">'
        f'<div class="chart-title">{escape(title_prefix)} <b>{escape(title_bold)}</b></div>'
        '<div class="donut-row">'
        + _donut_svg(rows, fmt_fn, center_label)
        + _donut_legend(rows, fmt_fn)
        + "</div></div>"
    )


def hbars_card_html(title_prefix: str, title_bold: str, rows: list[dict], fmt_fn) -> str:
    """Sorted horizontal bars — used for brand buckets, which have 10 categories.

    Bar width is scaled by the largest ABSOLUTE value so a negative bucket (real,
    caused by the retained non-positive-quantity SKUs) still renders a visible
    bar; negatives are tinted red rather than given a negative width, which
    would silently draw nothing.
    """
    head = ('<div class="chart-wrap">'
            f'<div class="chart-title">{escape(title_prefix)} <b>{escape(title_bold)}</b></div>')
    if not rows:
        return head + '<div class="no-data">No inventory matches these filters.</div></div>'

    scale = max(abs(row["value"]) for row in rows) or 1.0
    bars = []
    for row in rows:
        pct = abs(row["value"]) / scale * 100
        color = "var(--neg)" if row["value"] < 0 else row["color"]
        bars.append(
            f'<div class="hbar-row" title="{escape(str(row["label"]))}: {fmt_fn(row["value"])}">'
            f'<span class="hbar-label">{escape(str(row["label"]))}</span>'
            '<span class="hbar-track">'
            f'<span class="hbar-fill" style="background:{color};width:{pct:.1f}%"></span>'
            "</span>"
            f'<span class="hbar-val">{fmt_fn(row["value"])}</span>'
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


def _price_source_pill(row) -> str:
    src = row["price_source"]
    if src is None or pd.isna(src):
        return '<span class="status-pill pill-none">NO PRICE</span>'
    return f'<span class="status-pill pill-live">{escape(str(src))}</span>'


def _signed(v, fmt_fn) -> str:
    """Green when >= 0, red when negative — the template's convention."""
    if v is None or pd.isna(v):
        return _null_cell()
    color = "var(--pos)" if float(v) >= 0 else "var(--neg)"
    return f'<span style="color:{color}">{fmt_fn(v)}</span>'


def _mix_bar(row) -> str:
    """Cost / margin split for ONE case, as a bar under the product name.

    A flat gray bar means unpriced. When the Oracle cost exceeds the wholesale
    price the cost segment fills the whole bar, so an underwater SKU reads as
    all-cost rather than wrapping around.
    """
    price = row["dealernet_price_per_case"]
    if price is None or pd.isna(price) or float(price) <= 0:
        return ('<div class="mix-bar-wrap"><span class="mix-bar-seg" '
                'style="background:#d7dee9;width:100%"></span></div>')
    wholesale = float(price) * 0.8
    cost = float(row["unit_cost_per_case"] or 0.0)
    cost_pct = 100.0 if wholesale <= 0 else max(0.0, min(100.0, cost / wholesale * 100.0))
    return (
        '<div class="mix-bar-wrap">'
        f'<span class="mix-bar-seg" style="background:var(--accent);width:{cost_pct:.1f}%"></span>'
        f'<span class="mix-bar-seg" style="background:var(--accent2);width:{100 - cost_pct:.1f}%"></span>'
        "</div>"
    )


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
# (key, header, td_css, sort_type, cell_fn, total_fn). One definition drives the
# two-row header, the body rows and the footer totals, so nothing can drift out
# of alignment. Column ORDER is the workbook's, verbatim.
# ══════════════════════════════════════════════════════════════════════════════
def _col(key, header, td, sort_type, cell, total=None):
    return {"key": key, "header": header, "td": td, "sort": sort_type,
            "cell": cell, "total": total}


GROUPS = [
    # The anchor column sits outside every band — black header, pinned, and it
    # carries the cost/margin mini-bar under the product name.
    ("", "", [
        _col("product_name", "PRODUCT NAME (ORACLE)", "", "text",
             lambda r: escape(str(r["product_name"] or "")) + _mix_bar(r)),
    ]),
    ("&#9670; IDENTITY", "th-identity", [
        _col("dealernet_name", "DEALERNET NAME", "td-left", "text", _text_cell("dealernet_name")),
        _col("box_type", "BOX TYPE", "td-left", "text", _text_cell("box_type")),
        _col("item_number", "ITEM NUMBER", "td-left td-code", "text", _text_cell("item_number")),
        _col("brand_bucket", "BRAND BUCKET", "td-left td-muted", "text", _text_cell("brand_bucket")),
    ]),
    ("&#9670; INVENTORY", "th-inventory", [
        _col("quantity_cases", "QTY (CASES)", "", "num",
             _num_cell("quantity_cases", tx.fmtq), _sum_total("quantity_cases", tx.fmtq)),
        _col("street_date", "STREET DATE", "td-muted", "num", _date_cell("street_date")),
        _col("aging_bucket", "AGING BUCKET", "td-left", "text",
             lambda r: _aging_chip(r["aging_bucket"])),
        _col("brand", "BRAND", "td-left td-muted", "text", _text_cell("brand")),
        _col("inventory_value", "INVENTORY VALUE", "td-total", "num",
             _num_cell("inventory_value", tx.fmt), _sum_total("inventory_value", tx.fmt)),
    ]),
    ("&#9670; PACK CONFIG", "th-pack", [
        _col("boxes_per_case", "BOXES / CASE", "td-muted", "num", _num_cell("boxes_per_case", tx.fmt_int)),
        _col("packs_per_box", "PACKS / BOX", "td-muted", "num", _num_cell("packs_per_box", tx.fmt_int)),
        _col("cards_per_pack", "CARDS / PACK", "td-muted", "num", _num_cell("cards_per_pack", tx.fmt_int)),
    ]),
    ("&#9670; PRICING", "th-pricing", [
        _col("unit_cost_per_case", "UNIT COST / CASE", "", "num",
             _num_cell("unit_cost_per_case", tx.fmt)),
        _col("dealernet_price_per_case", "DN PRICE / CASE", "", "num",
             _num_cell("dealernet_price_per_case", tx.fmt)),
        _col("wholesale_value", "WHOLESALE VALUE", "", "num",
             _num_cell("wholesale_value", tx.fmt), _sum_total("wholesale_value", tx.fmt)),
    ]),
    ("&#9670; MARGIN", "th-margin", [
        # The footer % is Σprofit / Σwholesale from transforms.table_totals, not an
        # average of the per-row percentages.
        _col("margin_pct", "MARGIN %", "", "num",
             lambda r: _signed(r["margin_pct"], tx.fmt_pct), _sum_total("margin_pct", tx.fmt_pct)),
        _col("total_potential_profit", "POTENTIAL PROFIT", "", "num",
             lambda r: _signed(r["total_potential_profit"], tx.fmt),
             _sum_total("total_potential_profit", tx.fmt)),
        _col("margin_dollars_per_case", "MARGIN $ / CASE", "", "num",
             lambda r: _signed(r["margin_dollars_per_case"], tx.fmt)),
    ]),
    ("&#9670; DEALERNET MATCH", "th-dealernet", [
        _col("price_source", "PRICE SOURCE", "td-left", "text", _price_source_pill),
        _col("dn_listing_count", "DN LISTINGS", "td-muted", "num",
             lambda r: tx.fmtq(r["dn_listing_count"]) if r["dn_listing_count"] else _null_cell(),
             _sum_total("dn_listing_count", tx.fmtq)),
        _col("dn_latest_date", "DN LATEST", "td-muted", "num", _date_cell("dn_latest_date")),
    ]),
]

COLUMNS = [c for _label, _css, cols in GROUPS for c in cols]
COLUMN_BY_KEY = {c["key"]: c for c in COLUMNS}
# Sort-menu options: the on-screen header paired with its column key.
SORT_OPTIONS = [(c["key"], c["header"]) for c in COLUMNS]


def _td_attr(col: dict) -> str:
    """``class="..."`` attribute for a body/footer cell, or empty when unstyled."""
    return f' class="{col["td"]}"' if col["td"] else ""


def product_table_html(df: pd.DataFrame, totals: dict, *, selected: str | None,
                       sort_col: str, sort_asc: bool) -> str:
    """The 22-column banded product table.

    Rows carry ``data-key`` (the item number) and header cells carry
    ``data-sort`` (the column key); ``interactive.table`` binds click listeners to
    both. No inline ``onclick`` — the SiS content-security policy forbids it, and
    the component's JS is the supported path.
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
            dim = "" if c["key"] == sort_col else ' style="opacity:.3"'
            chead.append(
                f'<th{cls} data-sort="{escape(c["key"])}">{c["header"]}'
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
    if not body:
        body = [f'<tr><td class="no-data" colspan="{ncols}">'
                "No products match these filters.</td></tr>"]

    # Footer totals cover the WHOLE filtered set, which is the same set the table
    # renders (there is no pagination), so the numbers tie to what is on screen.
    fcells = [f'<td>TOTAL ({tx.fmtq(totals.get("_rows", len(df)))} SKUs)</td>']
    for c in COLUMNS[1:]:
        fcells.append(f"<td{_td_attr(c)}>{c['total'](totals) if c['total'] else ''}</td>")
    foot = '<tr class="tfoot-row">' + "".join(fcells) + "</tr>"

    return ('<div class="table-wrap"><table><thead>'
            + "".join(ghead) + "".join(chead)
            + "</thead><tbody>" + "".join(body)
            + "</tbody><tfoot>" + foot + "</tfoot></table></div>")


def detail_panel_html(row) -> str:
    """Inline drill-down panel for one SKU — 12 cells, the template's set.

    An expanding panel rather than an overlay modal, matching the template (which
    has no true modals either).
    """
    def cell(label: str, value: str, color: str | None = None) -> str:
        style = f' style="color:{color}"' if color else ""
        return (f'<div class="detail-cell"><div class="dc-lbl">{label}</div>'
                f'<div class="dc-val"{style}>{value}</div></div>')

    dn_name = row["dealernet_name"]
    dn_cell = escape(str(dn_name)) if dn_name and not pd.isna(dn_name) else _null_cell()
    pack = " × ".join(tx.fmt_int(row[k]) for k in
                      ("boxes_per_case", "packs_per_box", "cards_per_pack"))
    listings = (
        f'{tx.fmtq(row["dn_listing_count"])} &middot; {tx.fmt_date(row["dn_latest_date"])}'
        if row["dn_listing_count"] else _null_cell()
    )
    return (
        '<div class="detail-panel">'
        '<div class="detail-panel-header">'
        f'<div class="detail-panel-title">{escape(str(row["product_name"] or ""))}</div>'
        f'<span class="detail-count-badge">{escape(str(row["item_number"]))}</span>'
        f'<span class="detail-count-badge">{escape(str(row["brand_bucket"]))}</span>'
        "</div>"
        '<div class="detail-grid">'
        + cell("Dealernet Name", dn_cell)
        + cell("Mapping Status", _price_source_pill(row))
        + cell("Aging Bucket", _aging_chip(row["aging_bucket"]))
        + cell("Street Date", tx.fmt_date(row["street_date"]))
        + cell("Qty (Cases)", tx.fmtq(row["quantity_cases"]))
        + cell("Pack Config", pack)
        + cell("Inventory Value", tx.fmt(row["inventory_value"]), "var(--gold)")
        + cell("Wholesale Value", tx.fmt(row["wholesale_value"]), "var(--accent2)")
        + cell("Margin %", _signed(row["margin_pct"], tx.fmt_pct))
        + cell("Potential Profit", _signed(row["total_potential_profit"], tx.fmt))
        + cell("Markup Multiple", tx.fmt_mult(row["markup_multiple"]))
        + cell("DN Listings", listings)
        + "</div></div>"
    )
