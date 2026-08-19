# Pricing engine reference (historical)

`pricing-engine-reference.py.txt` is the former `backend/tests/test_pricing.py`.

The pricing engine it tested (`PriceMaster`, `SalesTransaction`,
`PricingRecommendation`, `services/pricing/`) was **removed** when the
application pivoted to stock-availability cost-plus. The tests could no longer
import, so they were moved here rather than deleted: they are the only
surviving specification of that engine's intended behaviour, written as
hand-worked figures.

Kept because the trader-editable rule engine (Phase 1) rebuilds much of this
behaviour, and these cases are the requirements for it:

| Behaviour the tests pin down | Rebuild as rule type |
|---|---|
| Margin over base cost | `target_margin` |
| Blending recent comparable sales into the price | `invoice_anchor` |
| Volume pricing by tonnage band | `quantity_slab` |
| A/B/C commercial adjustment | `customer_tier` |
| Per-MT freight by delivery location, added **after** the percentage steps | `transportation` |
| Clamping up to a minimum margin **and flagging that it happened** | `margin_floor` |
| Rounding to a quotable figure, never back down through the floor | `rounding` |

Properties worth preserving verbatim in the new engine:

- **Every step records its own before/after figure and the sentence explaining
  it**, so the stored explanation is a by-product of the calculation rather
  than a model asked to justify a number afterwards.
- **Outlier invoices cannot drag the price** — a miskeyed comparable is rejected.
- **The comparable window widens before giving up**, and the anchor is skipped
  entirely when the evidence is thin.
- **An expired price is never used.**
- **Freight is added after the percentage steps**, because a tier discount
  should reduce the material rate, not the lorry.
- **Unknown quantity skips the slab rather than inventing one.**
- **An unknown customer cannot reach HIGH confidence.**

Do not re-add this file to the test suite; it tests classes that no longer
exist. Treat it as the specification to write new tests against.
