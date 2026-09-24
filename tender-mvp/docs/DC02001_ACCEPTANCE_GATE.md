# DC.02001 source-provenance and dynamic-calculation gate

Status: accepted

## Provenance summary

| Element | Value | Source | Classification |
|---|---:|---|---|
| material.A0001 | 29386.4 | Đơn giá chi tiết!H283 | SOURCE_VERIFIED |
| material.A0008 | 8500.0 | Đơn giá chi tiết!H284 | SOURCE_VERIFIED |
| material.A0044 | 1000.0 | Đơn giá chi tiết!H285 | SOURCE_VERIFIED |
| material.Z999 | 3888.6 | Đơn giá chi tiết!H286 | FORMULA_DERIVED |
| labour.N4 | 289379.9 | Đơn giá chi tiết!H289 | SOURCE_VERIFIED |
| machine.M202.0014 | 24114.5 | Đơn giá chi tiết!H291 | SOURCE_VERIFIED |
| machine.M202.0018 | 27.9 | Đơn giá chi tiết!H292 | SOURCE_VERIFIED |
| machine.M006 | 19.6 | Đơn giá chi tiết!H293 | SOURCE_VERIFIED |
| machine.M999 | 1208.1 | Đơn giá chi tiết!H294 | FORMULA_DERIVED |
| material_total | 42775.0 | Đơn giá chi tiết!H591 | SOURCE_VERIFIED |
| labour_total | 289379.9 | Đơn giá chi tiết!H593 | SOURCE_VERIFIED |
| machine_total | 25370.1 | Đơn giá chi tiết!H599 | SOURCE_VERIFIED |
| direct_total | 357525.0 | Chiết tính!H600 | SOURCE_VERIFIED |
| loaded_unit_price | 634808.0 | Chiết tính!H615 | SOURCE_VERIFIED |
| rounding.price_rounding | 1 | Đầu vào!D39 | SOURCE_VERIFIED |
| rounding.total_rounding | 0 | Đầu vào!D41 | SOURCE_VERIFIED |

## Cell-level parity

| Stage | Runtime | Workbook | Delta |
|---|---:|---:|---:|
| Direct material | 42775.0 | 42775.0 | 0.0 |
| Direct labour | 289379.9 | 289379.9 | 0.0 |
| Direct machine | 25370.1 | 25370.1 | 0.0 |
| Loaded unit price | 634808 | 634808 | 0 |

## Mutation gate

| Mutation | Loaded unit price | Notes |
|---|---:|---|
| Baseline | 634808 | Baseline runtime |
| Material +10% | 639920 | Material path changed |
| Labour +10% | 690144 | Labour path changed |
| Machine +10% | 637840 | Machine path changed |
| Quantity mutation | 634808 | Quantity set to 10 in gate |
| HSXL x1.10 | 698289 | HSXL coefficient scaling |

## Missing dependencies

- []