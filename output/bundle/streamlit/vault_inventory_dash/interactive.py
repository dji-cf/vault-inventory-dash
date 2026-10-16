"""The page's three components, via ``st.components.v2``: the sortable product
table, the click-to-filter charts and the row drill-down panel.

Custom Components v2 (Streamlit >= 1.51) render frameless with bidirectional
data flow. All three are defined with inline HTML/CSS/JS only, which is
the one form Streamlit-in-Snowflake supports: no asset directories, and the
content security policy forbids external scripts, ``eval`` and inline event
handlers — none is used here; every listener is bound with
``addEventListener``. Keep each inline CSS/JS string MULTI-LINE: CCv2 reads a
single-line string holding ``/``, ``*``, ``[`` or ``]`` as a file path or glob.

Each component renders in a shadow DOM (``isolate_styles`` is never passed, so
the isolating default applies). That is why their CSS ships via ``css=`` — page
styles cannot pierce a shadow root — and why the JS must write into the
``.mount`` child rather than ``parentElement``, which would wipe the injected
``<style>``. It is also why the charts' SVG survives: it is set through
``innerHTML`` in the shadow root, so ``st.html``'s DOMPurify never sees it.

The table sends two triggers back to Python:

``select``
    a ``tbody tr[data-key]`` click — the item number of the clicked row.
``sort``
    a ``thead th[data-sort]`` click — the column key to sort by. This is what
    keeps the template's sortable headers working without inline ``onclick``
    handlers, which the SiS content-security policy rejects.

The chart component is ONE definition mounted once per chart, under distinct
keys, and sends one trigger:

``pick``
    a click, or Enter / Space, on any ``[data-pick]`` element (a donut arc, a
    legend row, a bar row) — the category label, which the app applies as that
    chart's page filter.

The detail component sends nothing back. It is a component rather than
``st.html`` only so that its JS can scroll the panel into view when a SKU is
opened. There is no iframe: the shadow root sits in the app document, so
``scrollIntoView`` from inside it scrolls the Streamlit page.
"""
from __future__ import annotations

import streamlit as st

from style import CHART_CSS, DETAIL_CSS, TABLE_CSS

_SHELL_HTML = '<div class="fct"><div class="mount"></div></div>'

# Re-runs whenever the mounted data changes: re-render the table and rebind the
# row and header listeners.
_JS = """
export default function ({ data, setTriggerValue, parentElement }) {
  const mount = parentElement.querySelector('.mount');
  mount.innerHTML = data.html;
  const wrap = mount.querySelector('.table-wrap');
  // Row cap, MEASURED from the rendered DOM so it holds whatever row height the
  // CSS produces: show exactly maxRows rows above the sticky footer, then scroll.
  // At maxRows or fewer rows (or null) the table renders whole, unscrolled.
  const rows = wrap ? wrap.querySelectorAll('tbody tr[data-key]') : [];
  if (wrap && data.maxRows && rows.length > data.maxRows) {
    const cap = () => {
      wrap.style.maxHeight = '';
      const top = wrap.getBoundingClientRect().top;
      const last = rows[data.maxRows - 1].getBoundingClientRect().bottom;
      const foot = wrap.querySelector('tfoot');
      const fh = foot ? foot.getBoundingClientRect().height : 0;
      const sb = wrap.offsetHeight - wrap.clientHeight;   // horizontal scrollbar, if any
      wrap.style.maxHeight = Math.ceil(last - top + fh + sb) + 'px';
    };
    wrap.classList.add('scrollable');
    cap();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(cap);  // Inter swap
  }
  mount.querySelectorAll('tbody tr[data-key]').forEach((tr) => {
    tr.addEventListener('click', () => setTriggerValue('select', tr.getAttribute('data-key')));
  });
  // Header sort. The value is suffixed with a monotonic counter because a
  // trigger only fires on CHANGE: clicking the same header twice in a row must
  // still reach Python (that is how a direction toggle is expressed), and a bare
  // repeated column key would be swallowed as "no change".
  let n = 0;
  mount.querySelectorAll('thead th[data-sort]').forEach((th) => {
    th.addEventListener('click', () => {
      setTriggerValue('sort', th.getAttribute('data-sort') + '#' + (++n) + '.' + data.nonce);
    });
  });
}
"""

_renderer = st.components.v2.component("vault_table", html=_SHELL_HTML,
                                       css=TABLE_CSS, js=_JS)


def table(html: str, *, key: str, nonce: str = "",
          max_rows: int | None = None) -> tuple[str | None, str | None]:
    """Mount the table; return ``(clicked_row_key, clicked_sort_column)``.

    Both values are transient triggers — non-``None`` only on the script run
    caused by the click. ``nonce`` should change whenever the rendered HTML does
    (pass the current sort state), so that the per-mount click counter cannot
    collide with a value Python has already seen.

    ``max_rows`` caps the scroll container at exactly that many body rows above
    the sticky footer, measured in the browser rather than estimated in px.
    With that many rows or fewer, or ``None``, every row renders unscrolled.
    """
    res = _renderer(
        key=key,
        data={"html": html, "maxRows": max_rows, "nonce": nonce},
        on_select_change=lambda: None,
        on_sort_change=lambda: None,
    )
    # ComponentResult is a dict subclass holding ONLY the keys that currently have
    # values, and trigger values are transient. A trigger that has never fired is
    # therefore absent, and attribute access (res.sort) raises AttributeError on
    # first render — so read both with .get().
    sort_raw = res.get("sort")
    # Strip the disambiguating "#counter.nonce" suffix added in JS.
    sort_col = sort_raw.split("#", 1)[0] if isinstance(sort_raw, str) else None
    selected = res.get("select")
    return (selected if isinstance(selected, str) else None), sort_col


# Re-runs whenever the mounted HTML changes: re-render the chart and rebind the
# listeners. Only [data-pick] elements are bound, so a label the app left
# unpickable is inert. Enter / Space on a focused row does what a click does.
_CHART_JS = """
export default function ({ data, setTriggerValue, parentElement }) {
  const mount = parentElement.querySelector('.mount');
  mount.innerHTML = data.html;
  // Date.now() plus a counter makes every click a NEW value, so re-picking the
  // same label (on, off, on) still reaches Python. The counter alone would not
  // do: it resets whenever this function re-runs, which is on every data change,
  // so "label#1" would recur after a pick and unpick round trip.
  let n = 0;
  const fire = (el) => setTriggerValue('pick',
      el.getAttribute('data-pick') + '#' + Date.now() + '.' + (++n));
  mount.querySelectorAll('[data-pick]').forEach((el) => {
    el.addEventListener('click', () => fire(el));
    el.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fire(el); }
    });
  });
}
"""

# One definition, mounted once per chart. The mount's default height="content"
# sizes the frameless host to the card, so no explicit height is needed.
_chart_renderer = st.components.v2.component("vault_chart", html=_SHELL_HTML,
                                              css=CHART_CSS, js=_CHART_JS)


def chart(html: str, *, key: str) -> str | None:
    """Mount one chart; return the clicked category label, or ``None``.

    A transient trigger, like the table's: non-``None`` only on the script run
    caused by the click. ``key`` must be unique per chart, and must not start
    with ``f_``, ``sort_`` or ``seg_``: the widget CSS matches those prefixes.
    """
    res = _chart_renderer(key=key, data={"html": html}, on_pick_change=lambda: None)
    raw = res.get("pick")          # .get(): see the comment in table()
    # Strip the "#time.counter" suffix added in JS. rsplit, so a "#" inside a
    # label could never truncate it.
    return raw.rsplit("#", 1)[0] if isinstance(raw, str) else None


# Runs only when the serialised data changes, and CCv2 memoises data on its JSON,
# so an unrelated rerun (a filter, a sort, a search) does not reach this at all.
# Identical HTML is not re-set either, which would replay the slide-in. The scroll
# fires once per TOKEN: Python sends "<item>#<seq>" on every run and bumps seq
# only when a SKU is opened. The handled token lives on window (the app
# document), so it survives a remount of the component and resets with a page
# reload, which resets the session too.
_DETAIL_JS = """
export default function ({ data, parentElement }) {
  const mount = parentElement.querySelector('.mount');
  if (mount._html !== data.html) { mount.innerHTML = data.html; mount._html = data.html; }
  const tok = data.scrollToken;
  if (tok && window.__fctDetailScrolled !== tok) {
    window.__fctDetailScrolled = tok;
    const el = mount.querySelector('.detail-panel');
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    // ~80ms lets the rerun's layout settle. 'nearest' is a no-op when the panel
    // is already fully in view and otherwise aligns its bottom edge, so the
    // clicked row usually stays on screen and Streamlit's fixed top bar cannot
    // cover the panel.
    if (el) setTimeout(() => el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth',
                                                 block: 'nearest' }), 80);
  }
}
"""

_detail_renderer = st.components.v2.component("vault_detail", html=_SHELL_HTML,
                                               css=DETAIL_CSS, js=_DETAIL_JS)


def detail(html: str, *, key: str, scroll_token: str = "") -> None:
    """Mount the drill-down panel; scroll it into view on a new ``scroll_token``.

    ``html`` is ``style.detail_panel_html`` output, unwrapped: the shell already
    supplies ``.fct``. Pass the same token on every run while the same SKU stays
    open, so that the mounted data stays byte-identical and nothing re-runs.
    """
    _detail_renderer(key=key, data={"html": html, "scrollToken": scroll_token})
