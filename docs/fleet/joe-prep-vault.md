# Joe prep – Vault points (Touchbase on Autos/Vault, 2026-11-02)

Source: `ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V`, Snowflake connection `fleet`, run 2026-11-02. All SQL was read-only.

## V1. 37 SKUs at 0 qty / $0 cost: **Confirmed, 37.**
The app returns **255 rows today. 37 of them have qty = 0 and $0 inventory value. None are negative.** All 37 are `-CSE` items. The earlier count of 6 only looked at raw view rows. The app's query does two things that raise it to 37:
- it keeps every `-CSE`/`-DB` row whatever its quantity (`queries.py:177-185`)
- it then groups by base SKU (`queries.py:186`)

The app's final SELECT only LEFT JOINs to lookups that are already deduplicated to one row per key (`queries.py:154-157`, `queries.py:81`). So its row set is exactly the `vault` CTE (`queries.py:160-187`), which was run verbatim:
```sql
WITH vault AS (SELECT REPLACE(REPLACE(ITEM_NUMBER,'-CSE',''),'-DB','') item_key, MAX(ITEM_NUMBER) item_number,
  SUM(INVONHANDQUANTITYPEOTRANSACTIONQUANTITY) quantity_cases, SUM(INVENTORY_VALUE) inventory_value
 FROM ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V
 WHERE ITEM_NUMBER IS NOT NULL AND END_DATE='4712-12-31'
   AND (ITEM_NUMBER LIKE '%-CSE' OR ITEM_NUMBER LIKE '%-DB'
        OR (ITEM_NUMBER NOT LIKE '%-CSE' AND ITEM_NUMBER NOT LIKE '%-DB' AND INVONHANDQUANTITYPEOTRANSACTIONQUANTITY>0))
 GROUP BY 1)
SELECT COUNT(*), COUNT_IF(quantity_cases=0 AND COALESCE(inventory_value,0)=0) FROM vault;
-- 255 total | 37 qty0 & $0 | 0 negative
```
The 37: FGC005459, 005985, 006019, 006107, 006109, 006119, 006120, 006153, 006156, 006231, 006247, 006249, 006398, 006433, 006434, 006549, 006586, 006608, 006634, 006650, 006681, 006688, 006692, 006702, 006767, 006770, 006772, 006789, 006834, 007026, 007052, 007132, 007159, 007232, 007239, 007243, 007655 (all `-CSE`).

Self-check (2026-11-02): today the view has 267 open rows (`END_DATE='4712-12-31'`). **46 of them have qty = 0.** So the earlier "6" does not match today's data. I do not know which query produced 6. Of the 37 zero SKUs, 9 are Mapped and 28 are No Price.

The app already knows about these rows. The comment at `queries.py:29-32` calls them deliberate ("matches Sigma"), and `transforms.py:451-458` (`nonpositive_qty_count`) counts them for a caption (`streamlit_app.py:180`).

`ORACLE_DATA_PROD.SANDBOX.VAULT_ANALYST_V`: the `fleet` login can reach it, but my one query (`SELECT * ... WHERE ITEM_NUMBER LIKE 'FGC007132%' LIMIT 20`) failed inside the view's own definition: `Function TRY_CAST cannot be used with arguments of types NUMBER(38,10) and FLOAT`. **The view is broken, not just locked down. No data could be read from it.**

**Fix option (not built):** add `AND quantity <> 0` (or `HAVING SUM(qty) <> 0`) for `-CSE`/`-DB` rows in `queries.py:177-186`. That moves the app away from Sigma's 238-row baseline, so Sigma would need the same change.

## V1a. FGC007132-CSE transfers 5/4, 5/22, 5/28: **Can't confirm the dates from this view. It only has month-level records, and every month shows 0.**
```sql
SELECT ITEM_NUMBER, START_DATE, END_DATE, INVONHANDQUANTITYPEOTRANSACTIONQUANTITY, INVENTORY_VALUE
FROM ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V WHERE ITEM_NUMBER LIKE 'FGC007132%' ORDER BY START_DATE;
-- 2026-05-01..05-31  0 | 0
-- 2026-06-01..06-30  0 | 0   ... (Jul, Aug, Sep the same)
-- 2026-10-01..4712-12-31  0 | 0
```
The data fits Joe's account. The SKU first appears in May, which matches the 10 units arriving 5/4. It is 0 at May month-end, which matches the 9 units moved back 5/22 and the 1 unit 5/28. It has stayed 0 since. All 6 rows have subinventory `Vault FG` and organization `FCT_SUNNY`. UNIT_COST is 285.2649 from May to Sep and 0 from 2026-10-01. This SKU has no `WH FG` rows in the view (I did not check the whole view's subinventory list). Neither object in `VAULT_INV` holds the dated subinventory transfers themselves; that would need the Oracle material-transactions source. **Not verified.**

## V2. FGC006078 shows as one SKU with qty 25: **The app merges `-CSE` and `-DB` into one base-SKU key.**
- `queries.py:162`: `REPLACE(REPLACE(ITEM_NUMBER, '-CSE', ''), '-DB', '') AS item_key`
- `queries.py:186`: `GROUP BY` the same expression
- `queries.py:163`: `MAX(ITEM_NUMBER)`, so the merged row is labelled `-DB` because 'FGC006078-DB' sorts after 'FGC006078-CSE'
- `queries.py:171`: `SUM(qty)` gives 16 + 9 = 25
- Documented in `queries.py:23-24`. `transforms.py` does not merge anything.
```sql
SELECT ITEM_NUMBER, SUM(INVONHANDQUANTITYPEOTRANSACTIONQUANTITY), SUM(INVENTORY_VALUE)
FROM ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V WHERE ITEM_NUMBER LIKE 'FGC006078%' AND END_DATE='4712-12-31' GROUP BY 1;
-- FGC006078-CSE 16 | 2,973.12
-- FGC006078-DB   9 |    83.62
```
Side effect: `MAX(UNIT_COST)` (`queries.py:172`) puts one unit cost on both rows. The Dealernet case price is applied to all 25 units, including the 9 display boxes (`queries.py:234-236`).

**Fix option (not built):** group by `ITEM_NUMBER` so `-CSE` and `-DB` stay separate rows. Keep `item_key` only as the join key to Dealernet, and price only the CSE row (or price DB at case price / boxes per case).

## V3. "Live only, no as-of date": **Confirmed for the app. But the source view does keep monthly history.**
- The code always filters on `END_DATE = '4712-12-31'` (`queries.py:176`). The only "snapshot" references are comments and the header label `style.py:737,755` ("Live Snapshot"). A grep for `as_of|asof|hist` in the `.py` files finds no as-of filter or date picker.
- `INFORMATION_SCHEMA.TABLES` for `VAULT_INV` lists only two objects. Neither has SNAP/HIST in its name:
  - `VAULT_INVENTORY_V` (view)
  - `VAULT_TOTAL_VALUE` (table, 6,694 rows, last altered 2026-05-29; one row per Dealernet listing per item, no date column)
- `VAULT_INVENTORY_V` is an SCD2 view with **18 monthly versions, START_DATE 2025-05-01 through 2026-10-01** (68 → 267 rows).
```sql
SELECT START_DATE, COUNT(*) FROM ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V GROUP BY 1 ORDER BY 1;
```
**Fix option (not built):** replace `END_DATE='4712-12-31'` with `:as_of BETWEEN START_DATE AND END_DATE` and add a month selector. This gives month-end as-of only, not daily.

## V4. "Mapped" means a Dealernet case price was found: **Confirmed.**
- `queries.py:251-254`: `WHEN dp.case_price IS NOT NULL THEN 'Mapped' ELSE 'No Price'`
- `streamlit_app.py:147`: help text "Mapped = a Dealernet case price was found for the SKU"

Current counts, using the app's join logic (case UOM, year fallback 0/-1/-2, joined on `item_key`):

| Status | All app rows | qty > 0 |
|---|---|---|
| Mapped | 198 | 189 |
| No Price | 57 | 29 |
| Total | 255 | 218 |

The query docstring baseline from 2026-09-15 is 184 / 54 (238 rows).

**Fix option (not built):** removing the 0-qty rows (V1) would bring No Price down to 29. Splitting CSE vs DB (V2) would change the counts again.
