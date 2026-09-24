# DC.02001 acceptance gate

Status: ACCEPTED

## Architecture checks

- Runtime is recomputed from work_item_norm and resource_price_book (no stored direct/loaded totals in compute path).
- Delta is computed as independent runtime result minus workbook_expected snapshot.
- Price source check validates price code, source cell, and unit alignment per resource line.

## Independent parity

| Metric | Runtime | Workbook expected | Delta (runtime - workbook) |
|---|---:|---:|---:|
| Direct total | 357525 | 357525 | 0 |
| Loaded unit price | 634808 | 634808 | 0 |

## Source verification

| Resource code | Unit | Price in price book | Price cell (price book) | Price cell (recipe) | Check |
|---|---|---:|---|---|---|
| A0001 | kWh | 1685 | Giá tháng!F29 | Giá tháng!F29 | MATCH |
| A0008 | lít | 17000 | Giá tháng!F45 | Giá tháng!F45 | MATCH |
| A0044 | cái | 20000 | Giá tháng!F39 | Giá tháng!F39 | MATCH |
| N4 | công | 380763 | Giá tháng!F82 | Giá tháng!F82 | MATCH |
| M202.0014 | ca | 11348 | Giá tháng!F113 | Giá tháng!F113 | MATCH |
| M202.0018 | ca | 9287 | Giá tháng!F103 | Giá tháng!F103 | MATCH |
| M006 | ca | 6521 | Giá tháng!F88 | Giá tháng!F88 | MATCH |

## Missing dependencies

- none

