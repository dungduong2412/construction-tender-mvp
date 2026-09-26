# AG.11112 acceptance gate

Status: ACCEPTED

## Architecture checks

- Runtime is recomputed from work_item_norm and resource_price_book (no stored direct/loaded totals in compute path).
- Delta is computed as independent runtime result minus workbook_expected snapshot.
- Price source check validates price code, source cell, and unit alignment per resource line.

## Independent parity

| Metric | Runtime | Workbook expected | Delta (runtime - workbook) |
|---|---:|---:|---:|
| Direct total | 1460669.6 | 1460669.6 | 0 |
| Loaded unit price | 2919165 | 2919165 | 0 |

## Source verification

| Resource code | Unit | Price in price book | Price cell (price book) | Price cell (recipe) | Check |
|---|---|---:|---|---|---|
| A24.0796A | kg | 1111 | Giá tháng!F70 | Giá tháng!F70 | MATCH |
| A24.0180 | m3 | 400000 | Giá tháng!F13 | Giá tháng!F13 | MATCH |
| A24.0008 | m3 | 530000 | Giá tháng!F25 | Giá tháng!F25 | MATCH |
| A24.0524 | lít | 10 | Giá tháng!F44 | Giá tháng!F44 | MATCH |
| N2.30 | công | 265915 | Giá tháng!F75 | Giá tháng!F75 | MATCH |
| M104.0102 | ca | 446610 | Giá tháng!F110 | Giá tháng!F110 | MATCH |
| M112.1301 | ca | 401159 | Giá tháng!F100 | Giá tháng!F100 | MATCH |

## Missing dependencies

- none

