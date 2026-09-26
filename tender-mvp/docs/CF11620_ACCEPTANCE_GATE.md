# CF.11620 acceptance gate

Status: ACCEPTED

## Architecture checks

- Runtime is recomputed from work_item_norm and resource_price_book (no stored direct/loaded totals in compute path).
- Delta is computed as independent runtime result minus workbook_expected snapshot.
- Price source check validates price code, source cell, and unit alignment per resource line.

## Independent parity

| Metric | Runtime | Workbook expected | Delta (runtime - workbook) |
|---|---:|---:|---:|
| Direct total | 1967829.3 | 1967829.3 | 0 |
| Loaded unit price | 3808696 | 3808696 | 0 |

## Source verification

| Resource code | Unit | Price in price book | Price cell (price book) | Price cell (recipe) | Check |
|---|---|---:|---|---|---|
| A28.0341 | kg | 1713 | Giá tháng!F69 | Giá tháng!F69 | MATCH |
| A28.0008 | m3 | 450000 | Giá tháng!F26 | Giá tháng!F26 | MATCH |
| A28.0089 | m3 | 300000 | Giá tháng!F12 | Giá tháng!F12 | MATCH |
| A28.0026 | kg | 20000 | Giá tháng!F32 | Giá tháng!F32 | MATCH |
| A28.0296 | kg | 44814 | Giá tháng!F64 | Giá tháng!F64 | MATCH |
| A28.0298 | quyển | 9091 | Giá tháng!F58 | Giá tháng!F58 | MATCH |
| NKS | công | 348919 | Giá tháng!F72 | Giá tháng!F72 | MATCH |
| N3 | công | 356526 | Giá tháng!F79 | Giá tháng!F79 | MATCH |
| M201.0022 | ca | 540291 | Giá tháng!F87 | Giá tháng!F87 | MATCH |

## Missing dependencies

- none

