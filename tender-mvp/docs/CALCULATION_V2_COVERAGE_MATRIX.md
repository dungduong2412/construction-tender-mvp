# Calculation V2 coverage matrix

## Coverage dimensions

- Source coverage: 43/43 lines match code/unit/source cell/price.
- Direct-cost parity coverage: 5/6 items have direct_total delta = 0.
- Loaded-price parity coverage: 5/6 items have loaded_unit_price delta = 0.
- Full project coverage: false (resolved items 5/6; KS.4/8 remains blocked/incomplete).

## Item status

| Work item | Category | Gate status | Missing dependencies | Direct delta | Loaded delta |
|---|---|---|---|---:|---:|
| CF.11620 | topography | ACCEPTED | - | 0 | 0 |
| CC.21310 | geotechnical_drilling | ACCEPTED | - | 0 | 0 |
| DC.02001 | laboratory | ACCEPTED | - | 0 | 0 |
| KS.4/8 | traffic_survey | BLOCKED/INCOMPLETE | labour.UNRESOLVED.KS4_8.LABOUR, resource_price:UNRESOLVED.KS4_8.LABOUR | N/A | N/A |
| CF.21120 | gmpb_stake | ACCEPTED | - | 0 | 0 |
| AG.11112 | gmpb_marker | ACCEPTED | - | 0 | 0 |

Snapshot note: workbook_expected values are reference snapshots only; runtime totals are recomputed from current norms + price book.
