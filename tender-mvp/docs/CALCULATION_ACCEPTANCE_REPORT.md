# Calculation Acceptance Report

Contract version: 1.0
Source workbook: `DuToan KS CauBinhGoi 2609.21 DuThau.xls` (read-only)

## Tender branch

| Item | Amount (VND) |
|---|---:|
| Topography — `Dự thầu!J22` | 114,297,433 |
| Geotechnical — `Dự thầu!J30` | 3,047,732,000 |
| Laboratory — `Dự thầu!J46` | 966,348,000 |
| Engine result — `J22 + J30 + J46` | **4,128,377,433** |
| Workbook target — `Dự thầu!J47` | **4,128,377,433** |
| Delta | **0** |

Status: **EXACT**. Main survey loaded unit prices are rounded down to the nearest 1,000 VND before quantity extension.

## Approval / THKP branch

The branch is calculated aggregate-first. Audited amounts are: direct cost `T` 2,125,515,983.0; indirect cost `GT` 1,151,085,965.4; taxable income `TL` 196,596,116.9; survey service `Cpvks` 128,423,991.5; pre-VAT `G` 3,601,622,056.8; VAT 360,162,205.7; post-VAT `Gks` 3,961,784,262.5; temporary facilities `LT` 63,444,775.5; contingency `Gdp` 396,178,426.3.

`Gdp` is exactly 10% of `Gks`. `ROUND(Gks + LT + Gdp, 0)` gives **4,421,407,464 VND**, equal to `THKP ks duyet!J29`; delta **0**, status **EXACT**. The unrounded control is 4,421,407,464.3.

## J51

`Dự thầu!J51 = 4,142,692,903 VND` is **REFERENCE ONLY — NOT ENGINE TARGET**. It is a historical/approved literal snapshot whose provenance is not established.

## External dependency classification

- `'[2]Tong hop'!D13` affects `THKP ks duyet!L32`, two parallel THKP sheets, and `DuToan GoiThau!G19`. It has cached workbook values but affects neither J47 nor J29; not a calculation-UAT blocker.
- `'[1]Trang_tính2'!C23` affects `Máy!D178,D188`. It has cached workbook values and is outside the active J47/J29 closure; not a calculation-UAT blocker.

The live source workflow still preserves unavailable mandatory prices as NULL/“Not available”; partial totals are not exposed as official totals, and the official submission export remains blocked while mandatory price evidence is missing.

## Validation evidence

- All 13 sheets in the active J47/J29 dependency closure scan with zero cached formula-error cells.
- The source workbook contains 114 cached `#DIV/0!` cells on legacy/non-target sheets, principally `Phân tích VT`; none is in the active financial target closure and none is hidden as part of this acceptance.
- The machine-readable contract contains all nine audited HSXL categories.
- The source workbook was read only and was not modified.
