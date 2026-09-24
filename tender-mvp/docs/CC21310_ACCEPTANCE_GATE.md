# CC.21310 source-provenance and dynamic-calculation gate

Status: accepted

## Provenance summary

| Element | Value | Source | Classification |
|---|---:|---|---|
| material.A28.0254 | 8400.0 | Đơn giá chi tiết!H196 | SOURCE_VERIFIED |
| material.A28.0097 | 1020.0 | Đơn giá chi tiết!H197 | SOURCE_VERIFIED |
| material.A28.0022 | 825.0 | Đơn giá chi tiết!H198 | SOURCE_VERIFIED |
| material.A28.0172 | 600.0 | Đơn giá chi tiết!H199 | SOURCE_VERIFIED |
| material.A28.0023 | 400.0 | Đơn giá chi tiết!H200 | SOURCE_VERIFIED |
| material.A28.0177 | 1800.0 | Đơn giá chi tiết!H201 | SOURCE_VERIFIED |
| material.A28.0178 | 140.0 | Đơn giá chi tiết!H202 | SOURCE_VERIFIED |
| material.A28.0216 | 8000.0 | Đơn giá chi tiết!H203 | SOURCE_VERIFIED |
| material.A28.0192 | 14000.0 | Đơn giá chi tiết!H204 | SOURCE_VERIFIED |
| material.Z999 | 3518.5 | Đơn giá chi tiết!H205 | FORMULA_DERIVED |
| labour.N3 | 683941.7 | Đơn giá chi tiết!H208 | SOURCE_VERIFIED |
| machine.M201.0002 | 10224.3 | Đơn giá chi tiết!H210 | SOURCE_VERIFIED |
| machine.M999 | 204.5 | Đơn giá chi tiết!H211 | FORMULA_DERIVED |
| material_total | 38703.5 | Đơn giá chi tiết!H398 | SOURCE_VERIFIED |
| labour_total | 683941.7 | Đơn giá chi tiết!H400 | SOURCE_VERIFIED |
| machine_total | 10428.8 | Đơn giá chi tiết!H404 | SOURCE_VERIFIED |
| direct_total | 733074.0 | Chiết tính!H405 | SOURCE_VERIFIED |
| loaded_unit_price | 1414311.0 | Chiết tính!H420 | SOURCE_VERIFIED |
| rounding.price_rounding | 1 | Đầu vào!D39 | SOURCE_VERIFIED |
| rounding.total_rounding | 0 | Đầu vào!D41 | SOURCE_VERIFIED |

## Cell-level parity

| Stage | Runtime | Workbook | Delta |
|---|---:|---:|---:|
| Direct material | 38703.5 | 38703.5 | 0.0 |
| Direct labour | 683941.7 | 683941.7 | 0.0 |
| Direct machine | 10428.8 | 10428.8 | 0.0 |
| Loaded unit price | 1414311 | 1414311 | 0 |

## Mutation gate

| Mutation | Loaded unit price | Notes |
|---|---:|---|
| Baseline | 1414311 | Baseline runtime |
| Material +10% | 1419099 | Material path changed |
| Labour +10% | 1549666 | Labour path changed |
| Machine +10% | 1415602 | Machine path changed |
| Quantity mutation | 1414311 | Quantity set to 10 in gate |
| HSXL x1.10 | 1555742 | HSXL coefficient scaling |

## Missing dependencies

- []