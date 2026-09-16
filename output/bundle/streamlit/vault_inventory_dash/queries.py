"""The single SQL statement behind the dashboard.

Validated against the Sigma workbook (8d898107-2c74-41a7-94b7-15909b773301):
238 SKUs · 126 products · 31 brands · 15 box types · 11,292 cases ·
$4,374,988.15 inventory valuation · 184 Mapped / 54 No Price ·
aging 0-3(31) 3-6(50) 6-12(49) 12-24(85) 24+(23).

Reproduce those figures before trusting any change to this file — Sigma is the
source of truth for the headline numbers, not this app.

On 2026-09-15 this statement was re-run against the same Snowflake connection
Sigma reads and diffed column-for-column against the workbook's master vault
table (element ``NVWxD6IuSz``). Every figure above matched, plus
$4,100,626.5655157333 priced-only valuation, $65,486,623.8097 gross Dealernet
market value, $52,389,299.03 wholesale, all 238 aging buckets and all 31
brand→bucket mappings. So the SQL is not the place to look for a Sigma
mismatch. Note also that ``DESA_SILVER.PRICING.DEALERNET_*`` (what Sigma's own
raw elements point at) and the ``EDP_SILVER`` tables used below return identical
prices and listing counts.

Shape notes that the rest of the app depends on:

* One row per ``item_key`` — ``ITEM_NUMBER`` stripped of its ``-CSE`` / ``-DB``
  suffix — so the case and the display box of a product collapse into one SKU.
* ``ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V`` is an SCD2 view;
  ``END_DATE = '4712-12-31'`` pins the currently-open record. There is NO as-of
  dimension, so this is a live snapshot and the app has no period selector —
  the header shows a DATA PULLED freshness stamp instead of an AS OF month.
* ``-CSE`` / ``-DB`` rows are kept regardless of on-hand quantity, while plain
  item numbers need a positive quantity. That is deliberate (it matches Sigma),
  and it is why ~36 SKUs carry a zero or negative ``quantity_cases``. The charts
  clamp for it and the UI captions it; do not "fix" it by filtering here.
* Dealernet prices join on (category, subcategory, box type, year) with a
  three-tier year fallback — exact, then year-1, then year-2 — because split-year
  products (e.g. 23/24) are mapped as 2024 while the orders carry 2023.
  ``year_priority`` records which tier won and dedupes to one price per SKU.
* Two value measures, on purpose, because Sigma has two:
  ``market_value`` is the GROSS ``dn_price x qty`` and is what the Current
  Market Value and Unrealized Gross Margin KPIs read; ``wholesale_value``
  applies a 0.8 wholesale factor and is what the table's WHOLESALE VALUE column
  and its footer read, along with the profit/margin/markup columns derived from
  it. Sigma draws exactly that line, so keep the two bases separate.
  ``dealernet_price_per_case`` stays the raw average.
"""
from __future__ import annotations

# No bind parameters: the query takes no inputs. Anything user-supplied is
# applied downstream in pandas (transforms.apply_filters), never spliced in here.
INVENTORY_SQL = """
WITH brand_mapping AS (
    SELECT brand_oracle, brand_new
    FROM (VALUES
        ('ATHLETES UNLIMITED','Other'),('ATU','Other'),('AUSTRALIAN BASKETBALL','Other'),
        ('BOXING','Contact Sports'),('BUNDESLIGA','Soccer'),('Bundesliga','Soccer'),
        ('CHP','Other'),('CRICKET','Other'),('DFL','Soccer'),('DIS','Entertainment'),
        ('DISNEY','Entertainment'),('DUN','Entertainment'),('DUNE','Entertainment'),
        ('ENGLISH PREMIER LEAGUE','Soccer'),('ENT','Entertainment'),('EUR','Soccer'),
        ('English Premier League','Soccer'),('FOR','Formula One'),('FORMULA 1 RACING','Formula One'),
        ('GLB','Other'),('GPK','Other'),('LACROSSE','Other'),('MAJOR LEAGUE BASEBALL','Baseball'),
        ('MAJOR LEAGUE SOCCER','Soccer'),('MARVEL','Entertainment'),('MCD','NIL'),
        ('MCDONALDS ALL AMERICAN','NIL'),('MIN','Other'),('MLB','Baseball'),('MLS','Soccer'),
        ('MRV','Entertainment'),('MUSIC & ENTERTAINMENT','Entertainment'),
        ('Major League Soccer','Soccer'),('Marvel','Entertainment'),
        ('McDONALDS ALL AMERICAN','NIL'),('NATIONAL BASKETBALL ASSOCIATION','Basketball'),
        ('NATIONAL FOOTBALL LEAGUE','Football'),('NBA','Basketball'),('NBL','Other'),
        ('NCAA - BASKETBALL','NIL'),('NCAA - FOOTBALL','NIL'),('NFL','Football'),
        ('NHL','Other'),('NIL','NIL'),('NIL HOCKEY','Other'),
        ('National Basketball Association','Basketball'),('OLY','Other'),('OLYMPICS','Other'),
        ('OVERTIME ELITE','NIL'),('Olympics','Other'),('PIX','Entertainment'),
        ('PIXAR','Entertainment'),('PREMIER LEAGUE','Soccer'),('SBS','Other'),
        ('STAR WARS','Entertainment'),('STH','Entertainment'),('STRANGER THINGS','Entertainment'),
        ('STW','Entertainment'),('Soccer Club Exclusives','Soccer'),('Star Wars','Entertainment'),
        ('TEN','Tennis'),('TENNIS','Tennis'),('TOP RANK BOXING','Contact Sports'),
        ('TRB','Other'),('TWD','Entertainment'),('Tennis','Tennis'),
        ('UEFA CHAMPIONS LEAGUE','Soccer'),('UEFA Champions League','Soccer'),
        ('UEFA EUROS','Soccer'),('UFC','Contact Sports'),
        ('ULTIMATE FIGHTING CHAMPIONSHIP','Contact Sports'),('VFR','Other'),
        ('WNBA','Basketball'),('WORLD WRESTLING ENTERTAINMENT','Contact Sports'),
        ('WWE','Contact Sports'),('major league baseball','Baseball')
    ) AS t(brand_oracle, brand_new)
    QUALIFY ROW_NUMBER() OVER (PARTITION BY UPPER(TRIM(brand_oracle)) ORDER BY brand_oracle) = 1
),

dn_prices AS (
    -- Priority 1: exact year match
    SELECT
        m.SKU,
        m.ORACLE_SKU_NAME,
        AVG(o.TRANSACTION_PRICE)        AS case_price,
        COUNT(*)                        AS dn_listing_count,
        MAX(o.TRANSACTION_DATE)         AS dn_latest_date,
        'DN Live'                       AS price_source,
        1                               AS year_priority
    FROM EDP_SILVER.PRODUCT.DEALERNET_SKU_MAPPINGS m
    JOIN EDP_SILVER.ORDERS.DEALERNET_ORDERS o
        ON m.CATEGORY                    = o.CATEGORY
        AND TRIM(m.SUBCATEGORY)          = TRIM(o.SUBCATEGORY)
        AND TRIM(m.BOX_TYPE)             = TRIM(o.BOX_TYPE)
        AND TRIM(m.YEAR_CLEANED)::NUMBER = o.YEAR_CLEANED
    WHERE o.UOM = 'case'
    GROUP BY m.SKU, m.ORACLE_SKU_NAME

    UNION ALL

    -- Priority 2: year - 1 fallback (split year products e.g. 23/24 mapped as 2024, orders has 2023)
    SELECT
        m.SKU,
        m.ORACLE_SKU_NAME,
        AVG(o.TRANSACTION_PRICE)        AS case_price,
        COUNT(*)                        AS dn_listing_count,
        MAX(o.TRANSACTION_DATE)         AS dn_latest_date,
        'DN Live'                       AS price_source,
        2                               AS year_priority
    FROM EDP_SILVER.PRODUCT.DEALERNET_SKU_MAPPINGS m
    JOIN EDP_SILVER.ORDERS.DEALERNET_ORDERS o
        ON m.CATEGORY                    = o.CATEGORY
        AND TRIM(m.SUBCATEGORY)          = TRIM(o.SUBCATEGORY)
        AND TRIM(m.BOX_TYPE)             = TRIM(o.BOX_TYPE)
        AND TRIM(m.YEAR_CLEANED)::NUMBER - 1 = o.YEAR_CLEANED
    WHERE o.UOM = 'case'
    GROUP BY m.SKU, m.ORACLE_SKU_NAME

    UNION ALL

    -- Priority 3: year - 2 fallback (edge cases)
    SELECT
        m.SKU,
        m.ORACLE_SKU_NAME,
        AVG(o.TRANSACTION_PRICE)        AS case_price,
        COUNT(*)                        AS dn_listing_count,
        MAX(o.TRANSACTION_DATE)         AS dn_latest_date,
        'DN Live'                       AS price_source,
        3                               AS year_priority
    FROM EDP_SILVER.PRODUCT.DEALERNET_SKU_MAPPINGS m
    JOIN EDP_SILVER.ORDERS.DEALERNET_ORDERS o
        ON m.CATEGORY                    = o.CATEGORY
        AND TRIM(m.SUBCATEGORY)          = TRIM(o.SUBCATEGORY)
        AND TRIM(m.BOX_TYPE)             = TRIM(o.BOX_TYPE)
        AND TRIM(m.YEAR_CLEANED)::NUMBER - 2 = o.YEAR_CLEANED
    WHERE o.UOM = 'case'
    GROUP BY m.SKU, m.ORACLE_SKU_NAME
),

dn_prices_deduped AS (
    SELECT
        SKU,
        ORACLE_SKU_NAME,
        case_price,
        dn_listing_count,
        dn_latest_date,
        price_source,
        year_priority
    FROM dn_prices
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY SKU
        ORDER BY year_priority ASC, dn_listing_count DESC
    ) = 1
),

vault AS (
    SELECT
        REPLACE(REPLACE(ITEM_NUMBER, '-CSE', ''), '-DB', '')            AS item_key,
        MAX(ITEM_NUMBER)                                                AS item_number,
        MAX(PRODUCT_NAME)                                               AS product_name,
        MAX(BRAND)                                                      AS brand,
        MAX(STREET_DATE)                                                AS street_date,
        MAX(BOX_TYPE)                                                   AS box_type,
        MAX(BOX_P_CASE)                                                 AS boxes_per_case,
        MAX(PACKS_P_BOX)                                                AS packs_per_box,
        MAX(CARDS_P_PACK)                                               AS cards_per_pack,
        SUM(INVONHANDQUANTITYPEOTRANSACTIONQUANTITY) AS quantity_cases,
        MAX(UNIT_COST)                               AS unit_cost_per_case,
        SUM(INVENTORY_VALUE)                                            AS inventory_value
    FROM ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V
    WHERE ITEM_NUMBER IS NOT NULL
      AND END_DATE = '4712-12-31'
      AND (
          ITEM_NUMBER LIKE '%-CSE'
          OR ITEM_NUMBER LIKE '%-DB'
          OR (
              ITEM_NUMBER NOT LIKE '%-CSE'
              AND ITEM_NUMBER NOT LIKE '%-DB'
              AND (INVONHANDQUANTITYPEOTRANSACTIONQUANTITY) > 0
          )
      )
    GROUP BY REPLACE(REPLACE(ITEM_NUMBER, '-CSE', ''), '-DB', '')
)

SELECT
    v.item_number,
    v.item_key,
    v.product_name,
    v.brand,
    COALESCE(bm.brand_new, 'Other')                             AS brand_bucket,
    v.box_type,
    v.street_date,
    YEAR(v.street_date)                                         AS street_date_year,
    TO_CHAR(v.street_date, 'YYYY-MM')                           AS street_date_month_label,

    CASE
        WHEN v.street_date IS NULL                                      THEN 'Unknown'
        WHEN DATEDIFF('day', v.street_date, CURRENT_DATE()) <= 91      THEN '0-3 Months'
        WHEN DATEDIFF('day', v.street_date, CURRENT_DATE()) <= 182     THEN '3-6 Months'
        WHEN DATEDIFF('day', v.street_date, CURRENT_DATE()) <= 365     THEN '6-12 Months'
        WHEN DATEDIFF('day', v.street_date, CURRENT_DATE()) <= 730     THEN '12-24 Months'
        ELSE '24+ Months'
    END                                                         AS aging_bucket,

    v.boxes_per_case,
    v.packs_per_box,
    v.cards_per_pack,
    v.quantity_cases,
    v.unit_cost_per_case,
    v.inventory_value,

    dp.case_price                                               AS dealernet_price_per_case,
    dp.ORACLE_SKU_NAME                                          AS dealernet_name,
    dp.price_source,
    dp.dn_listing_count,
    dp.dn_latest_date,
    dp.year_priority,

    CASE dp.year_priority
        WHEN 1 THEN 'Exact Year'
        WHEN 2 THEN 'Split Year (-1)'
        WHEN 3 THEN 'Split Year (-2)'
        ELSE NULL
    END                                                         AS year_match_type,

    -- Gross Dealernet basis, un-rounded: this is Sigma's Current Market Value
    -- KPI verbatim, Sum([Dealernet Price per Case] * [Quantity Cases]). The 0.8
    -- wholesale discount below belongs to the WHOLESALE VALUE column only --
    -- Sigma applies it there and not in the KPI, so do not "unify" the two.
    v.quantity_cases * dp.case_price                            AS market_value,

    ROUND(v.quantity_cases * dp.case_price * 0.8, 2)            AS wholesale_value,

    ROUND((v.quantity_cases * dp.case_price * 0.8)
          - v.inventory_value, 2)                               AS total_potential_profit,

    ROUND(dp.case_price * 0.8 - v.unit_cost_per_case, 2)        AS margin_dollars_per_case,

    ROUND((v.quantity_cases * dp.case_price * 0.8)
          / NULLIF(v.inventory_value, 0), 2)                    AS markup_multiple,

    ROUND(
        ((v.quantity_cases * dp.case_price * 0.8) - v.inventory_value)
        / NULLIF(v.quantity_cases * dp.case_price * 0.8, 0)
    , 4)                                                        AS margin_pct,

    CASE
        WHEN dp.case_price IS NOT NULL THEN 'Mapped'
        ELSE                                'No Price'
    END                                                         AS mapping_status

FROM vault v
LEFT JOIN dn_prices_deduped dp
    ON v.item_key = dp.sku
LEFT JOIN brand_mapping bm
    ON UPPER(TRIM(v.brand)) = UPPER(TRIM(bm.brand_oracle))

ORDER BY v.brand, v.street_date
"""
