# Disclaimers

How the dashboard's figures are built. This text used to appear in the dashboard's
collapsed "About these numbers" note under the KPI cards.

- **Cost** = Oracle standard manufacturing cost per case.
- **Market Value** = unadjusted Dealernet (DN) average case sale × quantity.
- **Wholesale Value** = 80% of the DN price × quantity; it is the headline figure
  and the table's basis.
- **Potential Profit** = Wholesale Value − Inventory Value over priced SKUs;
  unpriced SKUs are excluded, not counted as zero.
- The **markup chip** is Wholesale Value ÷ Inventory Value over the same priced
  SKUs. Both are pre-royalty.
- Display boxes (`-DB`) and packs (`-PCK`) are converted to case-equivalents and
  valued at the Dealernet box price (÷ packs per box for packs).
- A Dealernet price is **stale** when its last case sale is more than 90 days
  before the data pull.

The 80% and the 90 days are `transforms.WHOLESALE_FACTOR` and `transforms.STALE_DAYS`;
update this file if either changes. The evidence behind each point is in the README's
"Known data caveats".
