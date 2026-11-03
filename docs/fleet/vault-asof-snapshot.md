# Vault Inventory — "As of" month-end snapshot

Requested by Joe OBrien (Slack C0CAN1WAAR4, 10:14: "live only, no as-of date")
and the 1:00 PM Collect Intel touchbase action item "align on a point-in-time
snapshot feature for the Vault dashboard". Built by CoCo for Maya Iwabuchi.

## What it does

A selector in the navy MAPPING strip offers **Live** (default, unchanged
behaviour) plus every month-end that has a closed SCD2 version, newest first.
Picking a month-end reloads the snapshot pinned to that day. The header's
As Of field reads `Live` or the date (e.g. `Sep 30, 2026`). CSE/DB rules, the
Dealernet price join, brand mapping and all other logic are untouched — only the
SCD2 filter line changes.

## SCD2 end-date rule (checked, differs from the brief)

`DESCRIBE VIEW ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V` → `START_DATE DATE`,
`END_DATE DATE`. `SELECT START_DATE, END_DATE, COUNT(*) ... GROUP BY 1,2` shows
18 versions: each closed one runs 1st-of-month .. **last day of that month
(inclusive)**, e.g. `2026-09-01 .. 2026-09-30`; the open one is
`2026-10-01 .. 4712-12-31`.

So the brief's `START_DATE <= pick AND END_DATE > pick` would return nothing for a
month-end pick:

| rule for pick 2026-09-30 | raw rows |
| --- | --- |
| `END_DATE >  pick` (brief) | 0 |
| `END_DATE >= pick` (used) | 258 |

Implemented: `START_DATE <= pick AND END_DATE >= pick`. Live stays
`END_DATE = '4712-12-31'`.

Picker options = `DISTINCT LAST_DAY(START_DATE)` over closed versions (17
month-ends, 2025-05-31 .. 2026-09-30). The open version's month-end (2026-10-31)
is in the future and identical to Live, so it is not listed separately.

## SQL proof

The app's final SELECT only LEFT JOINs one-row-per-key dedups onto the `vault`
CTE, so the `vault` CTE's row count / SUM(inventory_value) equal the app's
(before the in-app `drop_empty_skus` hide). Query (same WHERE as queries.py, one
pass per snapshot), query id `01c82bca-031a-2f84-69de-0701a0a8497b`:

| snapshot | SKUs (item_key rows) | total inventory_value | cases |
| --- | --- | --- | --- |
| Live | 255 | 4,736,264.3033 | 11,989 |
| 2026-10-01 | 255 | 4,736,264.3033 | 11,989 |
| 2026-09-30 | 246 | 4,573,685.1122 | 11,680 |
| 2026-08-31 | 233 | 4,405,338.7134 | 11,289 |

2026-10-01 == Live, as expected (the open version starts that day). 2026-09-30
picks up the September version and differs.

Note: Live is 255 SKUs / $4.74M today vs the 238 / $4.37M Sigma figures in the
`queries.py` docstring (validated 2026-09-15) — the open record has moved on
since; this change does not alter the Live SQL.

## Changes (file:line)

- `queries.py:26-28` — docstring: no longer "no as-of dimension".
- `queries.py:47-51` — `from datetime import date`; input note.
- `queries.py:179` — `END_DATE = '4712-12-31'` → `{snapshot_filter}` placeholder.
- `queries.py:271-275` — `_LIVE_FILTER` + documented inclusive end-date rule.
- `queries.py:279-285` — `SNAPSHOT_DATES_SQL` (read-only, picker options).
- `queries.py:288-302` — `inventory_sql(as_of)`; accepts only `datetime.date`
  (TypeError otherwise), rendered via isoformat → no injection path.
- `data.py:19` — import `date`.
- `data.py:160-165` — `load_snapshot_dates()` (`st.cache_data`, 2 h TTL).
- `data.py:168-181` — `load_inventory(as_of=None)`; cached per as_of value.
- `style.py:27` — import `date`.
- `style.py:731-744, 759` — `header_html(..., as_of=None)`: As Of shows `Live`
  or the month-end date.
- `streamlit_app.py:42-60` — resolve `as_of` from session state before loading.
- `streamlit_app.py:143-144` — pass `as_of` to the header.
- `streamlit_app.py:154, 163-167` — new `m5` column with the As-of selectbox.
- `streamlit_app.py:257-259` — export filename uses `asofYYYYMMDD` for snapshots.

## Verification

- `python3 -m py_compile queries.py data.py style.py streamlit_app.py` → OK.
- `inventory_sql()` renders `END_DATE = '4712-12-31'`; `inventory_sql(date(2026,9,30))`
  renders `START_DATE <= '2026-09-30' AND END_DATE >= '2026-09-30'`; a string arg
  raises TypeError.
- Not run: streamlit (per instructions). `output/bundle/...` copy not updated.

## Open points

- Aging buckets still use `CURRENT_DATE()`, so a past snapshot's aging is measured
  to today, not to the as-of date. Left as-is ("keep every other rule"); switching
  to the pick date is a one-line follow-up if wanted.
- Dealernet prices are current, not historical, for any snapshot.
