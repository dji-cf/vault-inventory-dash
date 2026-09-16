"""The clickable, sortable product table, via ``st.components.v2``.

Custom Components v2 (Streamlit >= 1.51) render frameless with bidirectional
data flow. The component is defined with inline HTML/CSS/JS only, which is the
one form Streamlit-in-Snowflake supports: no asset directories, and the content
security policy forbids external scripts and ``eval`` — neither is used here.

The component renders in a shadow DOM (``isolate_styles`` is never passed, so the
isolating default applies). That is why the table CSS ships via ``css=`` — page
styles cannot pierce a shadow root — and why the JS must write into the
``.mount`` child rather than ``parentElement``, which would wipe the injected
``<style>``.

Two triggers travel back to Python:

``select``
    a ``tbody tr[data-key]`` click — the item number of the clicked row.
``sort``
    a ``thead th[data-sort]`` click — the column key to sort by. This is what
    keeps the template's sortable headers working without inline ``onclick``
    handlers, which the SiS content-security policy rejects.
"""
from __future__ import annotations

import streamlit as st

from style import TABLE_CSS

_SHELL_HTML = '<div class="fct"><div class="mount"></div></div>'

# Re-runs whenever the mounted data changes: re-render the table, rebind the row
# and header listeners, and (one-shot, Python-controlled) scroll into view.
_JS = """
export default function ({ data, setTriggerValue, parentElement }) {
  const mount = parentElement.querySelector('.mount');
  mount.innerHTML = data.html;
  const wrap = mount.querySelector('.table-wrap');
  // rows-per-view cap: bound the table height and scroll the overflow (null = uncapped)
  if (wrap && data.maxHeight) {
    wrap.classList.add('scrollable');
    wrap.style.maxHeight = data.maxHeight + 'px';
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
  if (data.scroll) {
    const el = wrap || mount.firstElementChild;
    // ~80ms lets layout settle before scrolling
    if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);
  }
}
"""

_renderer = st.components.v2.component("vault_table", html=_SHELL_HTML,
                                       css=TABLE_CSS, js=_JS)


def table(html: str, *, key: str, nonce: str = "", scroll: bool = False,
          max_height: int | None = None) -> tuple[str | None, str | None]:
    """Mount the table; return ``(clicked_row_key, clicked_sort_column)``.

    Both values are transient triggers — non-``None`` only on the script run
    caused by the click. ``nonce`` should change whenever the rendered HTML does
    (pass the current sort state), so that the per-mount click counter cannot
    collide with a value Python has already seen.

    ``max_height`` (px) caps the scroll container for the rows-per-view control;
    ``None`` leaves it uncapped and renders every row.
    """
    res = _renderer(
        key=key,
        data={"html": html, "scroll": scroll, "maxHeight": max_height, "nonce": nonce},
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
