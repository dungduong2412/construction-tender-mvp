# AG.11112 source-provenance and dynamic-calculation gate

Status: accepted

## Provenance summary

| Element | Value | Source | Classification |
|---|---:|---|---|
| material.A24.0796A | 292065.2 | Đơn giá chi tiết!H745 | SOURCE_VERIFIED |
| material.A24.0180 | 214368.0 | Đơn giá chi tiết!H746 | SOURCE_VERIFIED |
| material.A24.0008 | 468554.5 | Đơn giá chi tiết!H747 | SOURCE_VERIFIED |
| material.A24.0524 | 1857.5 | Đơn giá chi tiết!H748 | SOURCE_VERIFIED |
| material.Z999 | 4884.2 | Đơn giá chi tiết!H749 | FORMULA_DERIVED |
| labour.N2.30 | 364303.6 | Đơn giá chi tiết!H752 | SOURCE_VERIFIED |
| machine.M104.0102 | 42428.0 | Đơn giá chi tiết!H754 | SOURCE_VERIFIED |
| machine.M112.1301 | 72208.6 | Đơn giá chi tiết!H755 | SOURCE_VERIFIED |
| material_total | 981729.4 | Đơn giá chi tiết!H1646 | SOURCE_VERIFIED |
| labour_total | 364303.6 | Đơn giá chi tiết!H1648 | SOURCE_VERIFIED |
| machine_total | 114636.6 | Đơn giá chi tiết!H1652 | SOURCE_VERIFIED |
| direct_total | 1460669.6 | Chiết tính!H1653 | SOURCE_VERIFIED |
| loaded_unit_price | 2919165.0 | Chiết tính!H1668 | SOURCE_VERIFIED |
| rounding.price_rounding | 1 | Đầu vào!D39 | SOURCE_VERIFIED |
| rounding.total_rounding | 0 | Đầu vào!D41 | SOURCE_VERIFIED |

## Cell-level parity

| Stage | Runtime | Workbook | Delta |
|---|---:|---:|---:|
| Direct material | 981729.4 | 981729.4 | 0.0 |
| Direct labour | 364303.6 | 364303.6 | 0.0 |
| Direct machine | 114636.6 | 114636.6 | 0.0 |
| Loaded unit price | 2919165 | 2919165 | 0 |

## Mutation gate

| Mutation | Loaded unit price | Notes |
|---|---:|---|
| Baseline | 2919165 | Baseline runtime |
| Material +10% | 3115365 | Material path changed |
| Labour +10% | 2991972 | Labour path changed |
| Machine +10% | 2942076 | Machine path changed |
| Quantity mutation | 2919165 | Quantity set to 10 in gate |
| HSXL x1.10 | 3211082 | HSXL coefficient scaling |

## Missing dependencies

- []