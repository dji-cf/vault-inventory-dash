"""The single SQL statement behind the dashboard.

**2026-09-15 Sigma baseline** (historical; the statement then counted every
``-DB`` display box as a case). Validated against the Sigma workbook
(8d898107-2c74-41a7-94b7-15909b773301):
238 SKUs · 126 products · 31 brands · 15 box types · 11,292 cases ·
$4,374,988.15 inventory valuation · 184 Mapped / 54 No Price ·
aging 0-3(31) 3-6(50) 6-12(49) 12-24(85) 24+(23).

On 2026-09-15 this statement was re-run against the same Snowflake connection
Sigma reads and diffed column-for-column against the workbook's master vault
table (element ``NVWxD6IuSz``). Every figure above matched, plus
$4,100,626.5655157333 priced-only valuation, $65,486,623.8097 gross Dealernet
market value, $52,389,299.03 wholesale, all 238 aging buckets and all 31
brand→bucket mappings. Note also that ``DESA_SILVER.PRICING.DEALERNET_*`` (what
Sigma's own raw elements point at) and the ``EDP_SILVER`` tables used below
return identical prices and listing counts.

**Since plan 01 (2026-10-01): each row is valued in its own unit.** Keys that
hold only cases are unchanged and still match Sigma measure for measure. Keys
holding ``-DB`` boxes or ``-PCK`` packs now diverge from Sigma in cases, market,
wholesale, item number and listing count, until the workbook takes the same
change. Measured on 2026-10-01, same session, old SQL vs new: 246 SKUs and
188 Mapped / 58 No Price both ways; cases 11,675 → 11,653.2; inventory value
$4,570,529.56 unchanged; gross market $67,537,060.65 → $67,409,168.72;
wholesale $54,029,648.47 → $53,927,334.93. Only ``FGC006466``, ``FGC006035`` and
``FGC006078`` move.

Shape notes that the rest of the app depends on:

* One row per ``item_key``: ``ITEM_NUMBER`` stripped of its ``-CSE`` / ``-DB`` /
  ``-PCK`` suffix, so a product's case, display box and pack collapse into one
  SKU. A ``-CSE`` or plain row counts cases, a ``-DB`` row counts display boxes
  and a ``-PCK`` row counts packs. Boxes and packs convert to case-equivalents
  (``quantity_cases`` is fractional: 5 boxes at 10/case = 0.5) and travel
  alongside as ``display_boxes`` / ``loose_packs``. A row that cannot convert
  (no usable boxes per case, or for a pack no packs per box) counts zero cases
  and makes the key No Price; ``unconverted_rows`` counts them.
* ``item_number`` prefers the case row, then ``-DB``, then ``-PCK``.
  ``unit_cost_per_case`` is the case row's cost, else the box (or pack) cost
  scaled up to a case.
* ``BOX_P_CASE`` / ``PACKS_P_BOX`` are TEXT in the view, so arithmetic goes
  through ``TRY_TO_NUMBER`` (0 counts as unknown) and the pass-through
  ``boxes_per_case`` / ``packs_per_box`` columns are a string ``MAX``.
* ``ORACLE_DATA_PROD.VAULT_INV.VAULT_INVENTORY_V`` is an SCD2 view;
  ``END_DATE = '4712-12-31'`` pins the currently-open record. There is NO as-of
  dimension, so this is a live snapshot and the app has no period selector —
  the header shows a DATA PULLED freshness stamp instead of an AS OF month.
* ``-CSE`` / ``-DB`` rows are kept regardless of on-hand quantity, while plain
  item numbers (and ``-PCK`` rows, which fall under the same rule) need a
  positive quantity. That is deliberate (it matches Sigma),
  and it is why ~36 SKUs carry a zero or negative ``quantity_cases``. The app
  drops those SKUs in ``data.load_inventory``; do not "fix" it by filtering
  here, which would break this statement's reconciliation to Sigma.
* Dealernet prices join on (category, subcategory, box type, year) with a
  three-tier year fallback — exact, then year-1, then year-2 — because split-year
  products (e.g. 23/24) are mapped as 2024 while the orders carry 2023.
  Dealernet is read for ``UOM IN ('case', 'box')``; there is no pack market.
  The dedupe keeps one case price and one box price per SKU, each with its own
  tier; ``year_priority`` reports the case tier when there is one. Box listings
  join only to keys holding ``-DB`` or ``-PCK`` rows. A display box is valued at
  the DN box price (case price / boxes per case when the SKU has no box market),
  a pack at that box rate / packs per box.
* Two value measures, on purpose, because Sigma has two:
  ``market_value`` is the GROSS ``dn_price x qty`` and is what Sigma's Current
  Market Value and Unrealized Gross Margin KPIs read (the app shows it only in
  the Wholesale Value tile's tooltip); ``wholesale_value``
  applies a 0.8 wholesale factor and is what the app's KPI tiles, the table's
  WHOLESALE VALUE column and its footer read, along with the profit/margin/markup
  columns derived from it. Keep the two bases separate in the SQL.
  ``dealernet_price_per_case`` stays the raw case average on keys holding only
  cases. On keys holding boxes or packs it is the blended per-case figure,
  ``market_value / quantity_cases``, so Qty x DN = market value on every row;
  ``dealernet_price_per_box`` carries the raw box average for those keys.
  ``dn_listing_count`` / ``dn_latest_date`` cover whichever markets valued the
  key (``dn_box_listing_count`` is the box share).
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
    -- Case AND box listings, one row per unit: a display box is valued at the
    -- box price and a pack at a box's worth / packs per box (there is no pack
    -- market). DEALERNET_ORDERS carries exactly these two UOMs.
    -- Priority 1: exact year match
    SELECT
        m.SKU,
        m.ORACLE_SKU_NAME,
        o.UOM                           AS uom,
        AVG(o.TRANSACTION_PRICE)        AS price,  -- per case or per box, by uom
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
    WHERE o.UOM IN ('case', 'box')
    GROUP BY m.SKU, m.ORACLE_SKU_NAME, o.UOM

    UNION ALL

    -- Priority 2: year - 1 fallback (split year products e.g. 23/24 mapped as 2024, orders has 2023)
    SELECT
        m.SKU,
        m.ORACLE_SKU_NAME,
        o.UOM                           AS uom,
        AVG(o.TRANSACTION_PRICE)        AS price,
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
    WHERE o.UOM IN ('case', 'box')
    GROUP BY m.SKU, m.ORACLE_SKU_NAME, o.UOM

    UNION ALL

    -- Priority 3: year - 2 fallback (edge cases)
    SELECT
        m.SKU,
        m.ORACLE_SKU_NAME,
        o.UOM                           AS uom,
        AVG(o.TRANSACTION_PRICE)        AS price,
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
    WHERE o.UOM IN ('case', 'box')
    GROUP BY m.SKU, m.ORACLE_SKU_NAME, o.UOM
),

-- At most one case price and one box price per SKU, each with its own
-- year-fallback tier.
dn_prices_deduped AS (
    SELECT
        SKU,
        ORACLE_SKU_NAME,
        uom,
        price,
        dn_listing_count,
        dn_latest_date,
        price_source,
        year_priority
    FROM dn_prices
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY SKU, uom
        ORDER BY year_priority ASC, dn_listing_count DESC
    ) = 1
),

-- One row per vault row, tagged with the unit it counts.
vault_rows AS (
    SELECT
        REGEXP_REPLACE(ITEM_NUMBER, '-(CSE|DB|PCK)$', '')               AS item_key,
        ITEM_NUMBER,
        PRODUCT_NAME,
        BRAND,
        STREET_DATE,
        BOX_TYPE,
        BOX_P_CASE,
        PACKS_P_BOX,
        CARDS_P_PACK,
        UNIT_COST,
        INVENTORY_VALUE,
        INVONHANDQUANTITYPEOTRANSACTIONQUANTITY                         AS qty,
        -- -DB = Display Box (counts boxes); -PCK = one pack; -CSE and plain count cases.
        CASE WHEN ITEM_NUMBER LIKE '%-DB'  THEN 'box'
             WHEN ITEM_NUMBER LIKE '%-PCK' THEN 'pack'
             ELSE 'case' END                                            AS unit_kind,
        -- BOX_P_CASE / PACKS_P_BOX are TEXT. 0 is treated as unknown, and an
        -- unknown falls back to a sibling row's value for the same key.
        COALESCE(NULLIF(TRY_TO_NUMBER(BOX_P_CASE), 0),
                 MAX(NULLIF(TRY_TO_NUMBER(BOX_P_CASE), 0)) OVER (
                     PARTITION BY REGEXP_REPLACE(ITEM_NUMBER, '-(CSE|DB|PCK)$', '')))
                                                                        AS boxes_per_case_n,
        COALESCE(NULLIF(TRY_TO_NUMBER(PACKS_P_BOX), 0),
                 MAX(NULLIF(TRY_TO_NUMBER(PACKS_P_BOX), 0)) OVER (
                     PARTITION BY REGEXP_REPLACE(ITEM_NUMBER, '-(CSE|DB|PCK)$', '')))
                                                                        AS packs_per_box_n
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
),

vault AS (
    SELECT
        item_key,
        -- Prefer the case/plain item number, then -DB, then -PCK.
        COALESCE(MAX(IFF(unit_kind = 'case', ITEM_NUMBER, NULL)),
                 MAX(IFF(unit_kind = 'box',  ITEM_NUMBER, NULL)),
                 MAX(ITEM_NUMBER))                                      AS item_number,
        MAX(PRODUCT_NAME)                                               AS product_name,
        MAX(BRAND)                                                      AS brand,
        MAX(STREET_DATE)                                                AS street_date,
        MAX(BOX_TYPE)                                                   AS box_type,
        MAX(BOX_P_CASE)                                                 AS boxes_per_case,
        MAX(PACKS_P_BOX)                                                AS packs_per_box,
        MAX(CARDS_P_PACK)                                               AS cards_per_pack,
        MAX(boxes_per_case_n)                                           AS boxes_per_case_n,
        MAX(packs_per_box_n)                                            AS packs_per_box_n,
        COUNT_IF(unit_kind = 'case') > 0                                AS has_case_row,
        COUNT_IF(unit_kind = 'box')  > 0                                AS has_db_row,
        COUNT_IF(unit_kind = 'pack') > 0                                AS has_pck_row,
        -- Keep the three units apart for valuation ...
        SUM(IFF(unit_kind = 'case', qty, 0))                            AS case_qty,
        SUM(IFF(unit_kind = 'box',  qty, 0))                            AS display_boxes,
        SUM(IFF(unit_kind = 'pack', qty, 0))                            AS loose_packs,
        -- ... and report quantity in case-equivalents (5 boxes at 10/case = 0.5).
        -- An unconvertible row is NULL here, so SUM skips it: it counts as zero
        -- cases, and unconverted_rows makes the key No Price.
        SUM(CASE unit_kind
                WHEN 'box'  THEN qty / boxes_per_case_n
                WHEN 'pack' THEN qty / (boxes_per_case_n * packs_per_box_n)
                ELSE qty END)                                           AS quantity_cases,
        COUNT_IF((unit_kind = 'box'  AND boxes_per_case_n IS NULL)
              OR (unit_kind = 'pack' AND boxes_per_case_n * packs_per_box_n IS NULL))
                                                                        AS unconverted_rows,
        -- -DB cost is per box and -PCK cost (assumed) per pack. Use the case row's
        -- cost; for a key without one, scale the box or pack cost up to a case.
        COALESCE(MAX(IFF(unit_kind = 'case', UNIT_COST, NULL)),
                 MAX(IFF(unit_kind = 'box',  UNIT_COST * boxes_per_case_n, NULL)),
                 MAX(IFF(unit_kind = 'pack', UNIT_COST * boxes_per_case_n * packs_per_box_n, NULL)))
                                                                        AS unit_cost_per_case,
        SUM(INVENTORY_VALUE)                                            AS inventory_value
    FROM vault_rows
    GROUP BY item_key
),

valued AS (
    SELECT
        v.*,
        dc.price                                                        AS dn_case_price,
        db.price                                                        AS dn_box_price,
        -- A display box is worth the DN box price; case / boxes only when the SKU
        -- has no box market. A pack is a box's worth / packs per box.
        COALESCE(db.price, dc.price / v.boxes_per_case_n)               AS box_rate,
        COALESCE(db.price, dc.price / v.boxes_per_case_n) / v.packs_per_box_n
                                                                        AS pack_rate,
        -- Priced only when every unit the key holds converts and has a rate.
        v.unconverted_rows = 0
            AND (NOT v.has_case_row OR dc.price IS NOT NULL)
            AND (NOT v.has_db_row   OR COALESCE(db.price, dc.price / v.boxes_per_case_n) IS NOT NULL)
            AND (NOT v.has_pck_row  OR COALESCE(db.price, dc.price / v.boxes_per_case_n)
                                       / v.packs_per_box_n IS NOT NULL)
                                                                        AS is_priced,
        -- Which markets feed recency and listing count: the case market unless the
        -- key holds no cases and has a box market; the box market whenever joined.
        (v.has_case_row OR db.price IS NULL)                            AS uses_case_market,
        (db.price IS NOT NULL)                                          AS uses_box_market,
        dc.dn_latest_date                                               AS dn_case_latest,
        db.dn_latest_date                                               AS dn_box_latest,
        dc.dn_listing_count                                             AS dn_case_count,
        db.dn_listing_count                                             AS dn_box_count,
        COALESCE(dc.ORACLE_SKU_NAME, db.ORACLE_SKU_NAME)                AS dealernet_name,
        COALESCE(dc.price_source,    db.price_source)                   AS price_source,
        COALESCE(dc.year_priority,   db.year_priority)                  AS year_priority
    FROM vault v
    LEFT JOIN dn_prices_deduped dc
        ON v.item_key = dc.sku AND dc.uom = 'case'
    -- Box listings only value boxes and packs: join them for those keys only, or
    -- zero-quantity case SKUs that happen to have box listings turn Mapped at $0.
    LEFT JOIN dn_prices_deduped db
        ON v.item_key = db.sku AND db.uom = 'box'
        AND (v.has_db_row OR v.has_pck_row)
),

measured AS (
    SELECT
        x.*,
        -- A key holding only cases keeps the old expression verbatim (a NULL
        -- quantity stays NULL rather than becoming $0).
        IFF(x.is_priced,
            IFF(x.has_db_row OR x.has_pck_row,
                COALESCE(x.case_qty * x.dn_case_price, 0)
                  + x.display_boxes * COALESCE(x.box_rate, 0)
                  + x.loose_packs   * COALESCE(x.pack_rate, 0),
                x.case_qty * x.dn_case_price),
            NULL)                                                       AS market_value
    FROM valued x
),

per_case AS (
    SELECT
        m.*,
        -- DN Price / Case. A key holding only cases keeps the raw case average.
        -- One holding boxes or packs gets the blended per-case figure, so
        -- Qty x DN = market_value; at zero quantity it falls back to the case
        -- price, else a box's worth x boxes per case, so a priced zero-stock key
        -- still has a price (data.py's price_status reads its notna()).
        IFF(m.is_priced,
            IFF(m.has_db_row OR m.has_pck_row,
                COALESCE(m.market_value / NULLIF(m.quantity_cases, 0),
                         m.dn_case_price,
                         m.box_rate * m.boxes_per_case_n),
                m.dn_case_price),
            NULL)                                                       AS dn_price_per_case
    FROM measured m
)

SELECT
    p.item_number,
    p.item_key,
    p.product_name,
    p.brand,
    COALESCE(bm.brand_new, 'Other')                             AS brand_bucket,
    p.box_type,
    p.street_date,
    YEAR(p.street_date)                                         AS street_date_year,
    TO_CHAR(p.street_date, 'YYYY-MM')                           AS street_date_month_label,

    CASE
        WHEN p.street_date IS NULL                                      THEN 'Unknown'
        WHEN DATEDIFF('day', p.street_date, CURRENT_DATE()) <= 91      THEN '0-3 Months'
        WHEN DATEDIFF('day', p.street_date, CURRENT_DATE()) <= 182     THEN '3-6 Months'
        WHEN DATEDIFF('day', p.street_date, CURRENT_DATE()) <= 365     THEN '6-12 Months'
        WHEN DATEDIFF('day', p.street_date, CURRENT_DATE()) <= 730     THEN '12-24 Months'
        ELSE '24+ Months'
    END                                                         AS aging_bucket,

    p.boxes_per_case,
    p.packs_per_box,
    p.cards_per_pack,
    p.quantity_cases,
    p.display_boxes,
    p.loose_packs,
    p.unconverted_rows,
    p.unit_cost_per_case,
    p.inventory_value,

    p.dn_price_per_case                                         AS dealernet_price_per_case,
    p.dn_box_price                                              AS dealernet_price_per_box,
    p.dealernet_name,
    p.price_source,
    NULLIF(IFF(p.uses_case_market, COALESCE(p.dn_case_count, 0), 0)
           + IFF(p.uses_box_market, p.dn_box_count, 0), 0)     AS dn_listing_count,
    p.dn_box_count                                              AS dn_box_listing_count,
    GREATEST_IGNORE_NULLS(IFF(p.uses_case_market, p.dn_case_latest, NULL),
                          IFF(p.uses_box_market,  p.dn_box_latest,  NULL))
                                                                AS dn_latest_date,
    p.year_priority,

    CASE p.year_priority
        WHEN 1 THEN 'Exact Year'
        WHEN 2 THEN 'Split Year (-1)'
        WHEN 3 THEN 'Split Year (-2)'
        ELSE NULL
    END                                                         AS year_match_type,

    -- Gross Dealernet basis, un-rounded: this is Sigma's Current Market Value
    -- KPI verbatim, Sum([Dealernet Price per Case] * [Quantity Cases]), for every
    -- key without boxes or packs. The 0.8 wholesale discount below belongs to the
    -- WHOLESALE VALUE column only -- Sigma applies it there and not in the KPI, so
    -- do not "unify" the two.
    p.market_value,

    ROUND(p.market_value * 0.8, 2)                              AS wholesale_value,

    ROUND(p.market_value * 0.8 - p.inventory_value, 2)          AS total_potential_profit,

    ROUND(p.dn_price_per_case * 0.8 - p.unit_cost_per_case, 2)  AS margin_dollars_per_case,

    ROUND(p.market_value * 0.8 / NULLIF(p.inventory_value, 0), 2) AS markup_multiple,

    ROUND((p.market_value * 0.8 - p.inventory_value)
          / NULLIF(p.market_value * 0.8, 0), 4)                 AS margin_pct,

    IFF(p.is_priced, 'Mapped', 'No Price')                      AS mapping_status

FROM per_case p
LEFT JOIN brand_mapping bm
    ON UPPER(TRIM(p.brand)) = UPPER(TRIM(bm.brand_oracle))

ORDER BY p.brand, p.street_date
"""
