# CF.21120 source-provenance and dynamic-calculation gate

Status: accepted

## Provenance summary

| Element | Value | Source | Classification |
|---|---:|---|---|
| material.A28.0341 | 22269.0 | Đơn giá chi tiết!H702 | SOURCE_VERIFIED |
| material.A28.0008 | 18000.0 | Đơn giá chi tiết!H703 | SOURCE_VERIFIED |
| material.A28.0089 | 7800.0 | Đơn giá chi tiết!H704 | SOURCE_VERIFIED |
| material.A28.0026 | 2000.0 | Đơn giá chi tiết!H705 | SOURCE_VERIFIED |
| material.A28.0296 | 2.3 | Đơn giá chi tiết!H706 | SOURCE_VERIFIED |
| material.A28.0298 | 4545.5 | Đơn giá chi tiết!H707 | SOURCE_VERIFIED |
| material.Z999 | 5461.7 | Đơn giá chi tiết!H708 | FORMULA_DERIVED |
| labour.NKS | 275646.0 | Đơn giá chi tiết!H711 | SOURCE_VERIFIED |
| labour.N3 | 702356.2 | Đơn giá chi tiết!H712 | SOURCE_VERIFIED |
| machine.M201.0021 | 25000.0 | Đơn giá chi tiết!H715 | SOURCE_VERIFIED |
| machine.M999 | 2500.0 | Đơn giá chi tiết!H716 | FORMULA_DERIVED |
| material_total | 60078.5 | Đơn giá chi tiết!H1557 | SOURCE_VERIFIED |
| labour_total | 978002.2 | Đơn giá chi tiết!H1561 | SOURCE_VERIFIED |
| machine_total | 27500.0 | Đơn giá chi tiết!H1565 | SOURCE_VERIFIED |
| direct_total | 1065580.7 | Chiết tính!H1566 | SOURCE_VERIFIED |
| loaded_unit_price | 2045481.0 | Chiết tính!H1581 | SOURCE_VERIFIED |
| rounding.price_rounding | 1 | Đầu vào!D39 | SOURCE_VERIFIED |
| rounding.total_rounding | 0 | Đầu vào!D41 | SOURCE_VERIFIED |

## Cell-level parity

| Stage | Runtime | Workbook | Delta |
|---|---:|---:|---:|
| Direct material | 60078.5 | 60078.5 | 0.0 |
| Direct labour | 978002.2 | 978002.2 | 0.0 |
| Direct machine | 27500.0 | 27500.0 | 0.0 |
| Loaded unit price | 2045481 | 2045481 | 0 |

## Mutation gate

| Mutation | Loaded unit price | Notes |
|---|---:|---|
| Baseline | 2045481 | Baseline runtime |
| Material +10% | 2052995 | Material path changed |
| Labour +10% | 2239074 | Labour path changed |
| Machine +10% | 2048920 | Machine path changed |
| Quantity mutation | 2045481 | Quantity set to 10 in gate |
| HSXL x1.10 | 2250029 | HSXL coefficient scaling |

## Missing dependencies

- []