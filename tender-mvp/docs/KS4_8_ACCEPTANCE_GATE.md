# KS.4/8 acceptance gate

Status: BLOCKED/INCOMPLETE

## Architecture checks

- Runtime is recomputed from work_item_norm and resource_price_book (no stored direct/loaded totals in compute path).
- Delta is computed as independent runtime result minus workbook_expected snapshot.
- Price source check validates price code, source cell, and unit alignment per resource line.

## Independent parity

| Metric | Runtime | Workbook expected | Delta (runtime - workbook) |
|---|---:|---:|---:|
| Direct total | N/A | 298700 | N/A |
| Loaded unit price | N/A | 584015 | N/A |

## Source verification

| Resource code | Unit | Price in price book | Price cell (price book) | Price cell (recipe) | Check |
|---|---|---:|---|---|---|
| UNRESOLVED.KS4_8.LABOUR |  | N/A | N/A | N/A | BLOCKED |

## Missing dependencies

- labour.UNRESOLVED.KS4_8.LABOUR
- resource_price:UNRESOLVED.KS4_8.LABOUR

## Block reason

- Labour source remains unresolved; calculation is intentionally fail-closed.
- Workbook expected values are retained for comparison only and are not used in runtime computation.

