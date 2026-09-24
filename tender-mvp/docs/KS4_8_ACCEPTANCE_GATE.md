# KS.4/8 source-provenance and dynamic-calculation gate

Status: blocked

## Provenance summary

| Element | Value | Source | Classification |
|---|---:|---|---|
| labour.UNRESOLVED.KS4_8.LABOUR | 298700.0 | Đơn giá chi tiết!H683 | EXTERNAL_UNRESOLVED |
| material_total | 0 | Đơn giá chi tiết!H1452 | SOURCE_VERIFIED |
| labour_total | 298700.0 | Đơn giá chi tiết!H1451 | SOURCE_VERIFIED |
| machine_total | 0 | Đơn giá chi tiết!H1452 | SOURCE_VERIFIED |
| direct_total | 298700.0 | Chiết tính!H1452 | SOURCE_VERIFIED |
| loaded_unit_price | 584015.0 | Chiết tính!H1467 | SOURCE_VERIFIED |
| rounding.price_rounding | 1 | Đầu vào!D39 | SOURCE_VERIFIED |
| rounding.total_rounding | 0 | Đầu vào!D41 | SOURCE_VERIFIED |

## Cell-level parity

| Stage | Runtime | Workbook | Delta |
|---|---:|---:|---:|
| Direct material | 0 | 0 | 0 |
| Direct labour | 298700.0 | 298700.0 | 0.0 |
| Direct machine | 0 | 0 | 0 |
| Loaded unit price | 584015 | 584015 | 0 |

## Mutation gate

| Mutation | Loaded unit price | Notes |
|---|---:|---|
| Baseline | 584015 | Baseline runtime |
| Material +10% | 584015 | Material path changed |
| Labour +10% | 642417 | Labour path changed |
| Machine +10% | 584015 | Machine path changed |
| Quantity mutation | 584015 | Quantity set to 10 in gate |
| HSXL x1.10 | 642417 | HSXL coefficient scaling |

## Missing dependencies

- ['labour.UNRESOLVED.KS4_8.LABOUR']