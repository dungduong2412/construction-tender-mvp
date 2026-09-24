# CC.21310 acceptance gate

Status: ACCEPTED

## Architecture checks

- Runtime is recomputed from work_item_norm and resource_price_book (no stored direct/loaded totals in compute path).
- Delta is computed as independent runtime result minus workbook_expected snapshot.
- Price source check validates price code, source cell, and unit alignment per resource line.

## Independent parity

| Metric | Runtime | Workbook expected | Delta (runtime - workbook) |
|---|---:|---:|---:|
| Direct total | 733074 | 733074 | 0 |
| Loaded unit price | 1414311 | 1414311 | 0 |

## Source verification

| Resource code | Unit | Price in price book | Price cell (price book) | Price cell (recipe) | Check |
|---|---|---:|---|---|---|
| A28.0254 | cái | 150000 | Giá tháng!F42 | Giá tháng!F42 | MATCH |
| A28.0097 | m | 60000 | Giá tháng!F15 | Giá tháng!F15 | MATCH |
| A28.0022 | bộ | 150000 | Giá tháng!F27 | Giá tháng!F27 | MATCH |
| A28.0172 | m | 20000 | Giá tháng!F47 | Giá tháng!F47 | MATCH |
| A28.0023 | cái | 40000 | Giá tháng!F28 | Giá tháng!F28 | MATCH |
| A28.0177 | m | 45000 | Giá tháng!F50 | Giá tháng!F50 | MATCH |
| A28.0178 | cái | 70000 | Giá tháng!F51 | Giá tháng!F51 | MATCH |
| A28.0216 | cái | 20000 | Giá tháng!F37 | Giá tháng!F37 | MATCH |
| A28.0192 | m3 | 4000000 | Giá tháng!F34 | Giá tháng!F34 | MATCH |
| N3 | công | 356526 | Giá tháng!F79 | Giá tháng!F79 | MATCH |
| M201.0002 | ca | 108194 | Giá tháng!F104 | Giá tháng!F104 | MATCH |

## Missing dependencies

- none

