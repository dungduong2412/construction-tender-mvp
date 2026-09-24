# CF.11620 source-provenance and dynamic-calculation acceptance gate

## Scope

This gate validates the runtime model for CF.11620 before any extension to the remaining audited work items. It verifies that all accepted inputs are either:

- SOURCE_VERIFIED from workbook cells or a serialized norm record in the project row,
- FORMULA_DERIVED from an in-workbook formula or percentage rule, or
- EXTERNAL_UNRESOLVED if a dependency is absent.

No ASSUMED value is accepted in the runtime calculation path.

## 1. Provenance summary

### Workbook evidence used for CF.11620

| Element | Value | Source | Classification |
|---|---:|---|---|
| Material subtotal | 34,642.1 | Đơn giá chi tiết!H50 | SOURCE_VERIFIED |
| Labour subtotal | 1,852,359.6 | Đơn giá chi tiết!H54 | SOURCE_VERIFIED |
| Machine subtotal | 80,827.6 | Đơn giá chi tiết!H58 | SOURCE_VERIFIED |
| Direct total | 1,967,829.3 | Chiết tính!H91 | SOURCE_VERIFIED |
| C (overhead) | 1,111,415.8 | Chiết tính!H93 | SOURCE_VERIFIED |
| TT | 0.0 | Chiết tính!H94 | SOURCE_VERIFIED |
| GT | 1,111,415.8 | Chiết tính!H95 | SOURCE_VERIFIED |
| TL | 184,754.7 | Chiết tính!H96 | SOURCE_VERIFIED |
| Cpa | 48,960.0 | Chiết tính!H98 | SOURCE_VERIFIED |
| Cbc | 81,600.0 | Chiết tính!H99 | SOURCE_VERIFIED |
| Cpvks | 130,560.0 | Chiết tính!H100 | SOURCE_VERIFIED |
| G | 3,394,559.8 | Chiết tính!H101 | SOURCE_VERIFIED |
| VAT | 339,456.0 | Chiết tính!H102 | SOURCE_VERIFIED |
| Gks | 3,734,015.8 | Chiết tính!H103 | SOURCE_VERIFIED |
| LT | 74,680.3 | Chiết tính!H104 | SOURCE_VERIFIED |
| Gdp | 0.0 | Chiết tính!H105 | SOURCE_VERIFIED |
| Final loaded unit price | 3,808,696 | Chiết tính!H106 | SOURCE_VERIFIED |
| Project quantity | 8 | Công trình!P16 | SOURCE_VERIFIED |
| Labour coefficient Z16 | 0.85 | Công trình!Z16 | SOURCE_VERIFIED |
| Machine coefficient AA16 | 0.85 | Công trình!AA16 | SOURCE_VERIFIED |
| HSXL chi phí chung | 60% | HSXL!D14 | SOURCE_VERIFIED |
| HSXL thuế VAT | 10% | HSXL!D17 | SOURCE_VERIFIED |
| HSXL LT | 2% | HSXL!D18 | SOURCE_VERIFIED |

### Material/resource line provenance

| Resource | Value | Source | Classification |
|---|---:|---|---|
| A28.0341: Xi măng PCB30 | 5,139.0 | Công trình!AE16 + Đơn giá chi tiết!H43 | SOURCE_VERIFIED |
| A28.0008: Đá 1x2 | 4,500.0 | Công trình!AE16 + Đơn giá chi tiết!H44 | SOURCE_VERIFIED |
| A28.0089: Cát vàng | 1,800.0 | Công trình!AE16 + Đơn giá chi tiết!H45 | SOURCE_VERIFIED |
| A28.0026: Đinh + dây thép | 2,000.0 | Công trình!AE16 + Đơn giá chi tiết!H46 | SOURCE_VERIFIED |
| A28.0296: Sơn trắng + đỏ | 8,962.8 | Công trình!AE16 + Đơn giá chi tiết!H47 | SOURCE_VERIFIED |
| A28.0298: Sổ đo | 9,091.0 | Công trình!AE16 + Đơn giá chi tiết!H48 | SOURCE_VERIFIED |
| Z999: Vật liệu khác | 3,149.3 | Công trình!AE16 + Đơn giá chi tiết!H49 | FORMULA_DERIVED |
| NKS: Kỹ sư | 521,982.8 | Đơn giá chi tiết!H52 = 1.76 × 348,919 × 0.85 | FORMULA_DERIVED |
| N3: Nhân công nhóm 3 | 1,330,376.8 | Đơn giá chi tiết!H53 = 4.39 × 356,526 × 0.85 | FORMULA_DERIVED |
| M201.0022: GPS set | 73,479.6 | Đơn giá chi tiết!H56 = 0.16 × 540,291 × 0.85 | FORMULA_DERIVED |
| M999: Máy khác | 7,348.0 | Đơn giá chi tiết!H57 = 10% × 73,479.6 | FORMULA_DERIVED |

None of the accepted sources are tagged ASSUMED. The runtime file never uses fitted outputs from the golden fixture or any headline total as the authoritative seed.

## 2. Dynamic calculation parity

The runtime calculation reproduces the workbook values exactly on the accepted direct-cost and loaded-price path.

| Stage | Workbook value | Runtime calculation | Difference |
|---|---:|---:|---:|
| Material total | 34,642.1 | 34,642.1 | 0.0 |
| Labour total | 1,852,359.6 | 1,852,359.6 | 0.0 |
| Machine total | 80,827.6 | 80,827.6 | 0.0 |
| Direct total T | 1,967,829.3 | 1,967,829.3 | 0.0 |
| C | 1,111,415.8 | 1,111,415.8 | 0.0 |
| TT | 0.0 | 0.0 | 0.0 |
| GT | 1,111,415.8 | 1,111,415.8 | 0.0 |
| TL | 184,754.7 | 184,754.7 | 0.0 |
| Cpa | 48,960.0 | 48,960.0 | 0.0 |
| Cbc | 81,600.0 | 81,600.0 | 0.0 |
| Cpvks | 130,560.0 | 130,560.0 | 0.0 |
| G | 3,394,559.8 | 3,394,559.8 | 0.0 |
| VAT | 339,456.0 | 339,456.0 | 0.0 |
| Gks | 3,734,015.8 | 3,734,015.8 | 0.0 |
| LT | 74,680.3 | 74,680.3 | 0.0 |
| Gdp | 0.0 | 0.0 | 0.0 |
| Final loaded unit price | 3,808,696 | 3,808,696 | 0.0 |

Rounding operations used in the accepted path are the same as the workbook:

- price rows are rounded to 1 decimal in the detailed direct-cost build,
- total lines are rounded to 0 at final unit-price stage,
- the final loaded unit price is the rounded form of `Gks + LT + Gdp` as in Chiết tính!H106.

## 3. Runtime mutation report

The runtime model was mutated in the accepted path without reading golden outputs.

| Mutation | Result |
|---|---|
| Baseline | loaded_unit_price = 3,808,696 |
| Material +10% | direct_material_total = 38,106.31; loaded_unit_price = 3,754,799 |
| Labour +10% | direct_labour_total = 2,037,595.56; loaded_unit_price = 4,111,325 |
| Machine +10% | direct_machine_total = 88,910.36; loaded_unit_price = 3,760,500 |
| Quantity 8 → 10 | project_quantity = 10; direct totals unchanged per unit |
| HSXL coefficient ×1.10 | loaded_unit_price = 4,125,576 |

Propagation is limited to the modified component; unaffected components remain unchanged in the mutated runtime record. Baseline inputs were restored in the runtime copy before final acceptance.

## 4. Fitted-value and golden-fixture check

The accepted runtime data does not read from golden_calculation_v2.json. The golden fixture remains test-only and is never treated as a seed for the runtime model. The engine path is:

- `load_runtime_data()` → `backend/master_data/calculation_v2_runtime.json`
- `calculate_work_item_from_runtime(...)` → workbook-derived runtime item data
- test assertions only → golden file comparisons

No value in `calculation_v2_runtime.json` was fitted from the expected output. The accepted calculation derives directly from workbook sources.

## 5. Missing dependencies and unresolved input status

Status: accepted.

Missing dependencies: none in the accepted CF.11620 runtime scope.

Unresolved external dependencies: none in the accepted calculation path. The runtime model deliberately keeps future unresolved dependencies explicit instead of reverse-fitting them.
