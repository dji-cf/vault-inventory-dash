# Vault Inventory – Joe fixes (Part A only)

Requested by Maya Iwabuchi. Reviewer: Joe OBrien (Slack C0CAN1WAAR4, 2026-11-02 10:03). Maya approved only Part A (2026-11-02 16:30). **Policy sign-off still open:** Dan Chen should confirm at the 1:30 PM meeting before Start.

## Changes
| File:line | Change |
|---|---|
| `transforms.py:461-470` | New `drop_empty_skus(df)`. It drops rows where `quantity_cases == 0` AND `inventory_value == 0` (NULLs count as 0) and returns `(kept_df, hidden_count)`. |
| `streamlit_app.py:47` | `df_all, hidden_empty = tx.drop_empty_skus(df_all)` runs right after load. Every view downstream (filters, cards, charts, table, totals, export) uses the reduced set. |
| `streamlit_app.py:263-264` | One caption line under the product table: `"<n> SKUs with 0 quantity and $0 cost are hidden."`. It is shown only when n > 0. |

These are unchanged: `queries.py` (including :162 and :186, so there is no -CSE/-DB split), `DRAFT_LABEL`, the "Mapped" toggle, and the export button. The export now leaves out the hidden rows, because it uses the same filtered frame. `python3 -m py_compile transforms.py streamlit_app.py` passed.

## Counts (2026-11-02, connection `fleet`, read-only)
| | Rows |
|---|---|
| App query before | 255 |
| Hidden (qty 0 AND $0) | **37** (includes FGC007132-CSE) |
| **New row count** | **218** |

```sql
WITH vault AS (SELECT REPLACE(REPLACE(ITEM_NUMBER,'-CSE',''),'-DB','') item_key, MAX(ITEM_NUMBER) item_number,
  SUM(INVONHANDQUANTITYPEOTRANSACTIONQUANTITY) quantity_cases, SUM(INVENTORY_VALUE) inventory_value
 FROM ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V
 WHERE ITEM_NUMBER IS NOT NULL AND END_DATE='4712-12-31'
   AND (ITEM_NUMBER LIKE '%-CSE' OR ITEM_NUMBER LIKE '%-DB'
        OR (ITEM_NUMBER NOT LIKE '%-CSE' AND ITEM_NUMBER NOT LIKE '%-DB' AND INVONHANDQUANTITYPEOTRANSACTIONQUANTITY>0))
 GROUP BY 1)
SELECT COUNT(*) total,
  COUNT_IF(COALESCE(quantity_cases,0)=0 AND COALESCE(inventory_value,0)=0) hidden,
  total-hidden shown
FROM vault;
-- 255 | 37 | 218
```
This is the app's `vault` CTE (`queries.py:160-187`). Per the prep doc, the app's final SELECT only LEFT JOINs to lookups that are already deduplicated, so the row set is the same.

## Notes
- The existing "no positive on-hand quantity" caption (`streamlit_app.py:181`) now only counts negative rows, and those are 0 today, so it will not appear.
- Per the prep doc (not re-checked in this task; LIKELY), 9 of the hidden 37 are Mapped and 28 are No Price. Mapped/No Price would then go from 198 / 57 to 189 / 29.
- Self-check (2026-11-02): re-ran the SQL. Result: 255 total, 37 hidden, 0 negative, 0 NULL qty, 0 non-positive rows left after hiding. FGC007132-CSE is in the hidden set.
- The app was not run (no streamlit), so the rendered caption has not been viewed.
