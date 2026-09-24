# Calculation Specification — DuToan KS CauBinhGoi 2609.21 DuThau

## 1. Executive conclusions

1. The workbook contains two materially different calculation branches:

   - **Approved estimate branch:** resource prices and norms → `Đơn giá chi tiết` → `Giá tổng hợp` → `THKP ks duyet`.
   - **Tender branch:** resource prices and norms → `Chiết tính` → `Dự thầu`.

2. `THKP ks duyet!J29` is formula-driven and equals **4,421,407,464** after rounding. Its unrounded control is `THKP ks duyet!O29 = 4,421,407,464.3`.

3. `Dự thầu!J51 = 4,142,692,903` is a literal, not a formula. There is no cell elsewhere in the workbook with the same value and no in-workbook precedent can be traced for it. It is best classified as a **literal approved-value snapshot used for presentation/downstream addition**, not as the current calculated tender result. It may have been copied from an external approval or an earlier workbook state, but that provenance is not recoverable from this file.

4. The current live tender calculation is `Dự thầu!J47 = 4,128,377,433`, independently reproduced by `Dự thầu!J49 = 4,128,377,433.2`. `Dự thầu!J50` is a literal copy of the rounded live result. Therefore `J51` is **14,315,470 higher** than the current tender calculation.

5. The **278,714,561** gap between `THKP ks duyet!J29` and `Dự thầu!J51` is not one discount or one formula. The approved estimate includes `Gdp` contingency of **396,178,426.3**, while the tender unit-price blocks set `Gdp` to zero. The branches also apply category-specific VAT, temporary-facility, indirect-cost and survey-service rules, and the tender sheet rounds most loaded unit prices down to the nearest thousand.

## 2. Calculation architecture

```text
Project quantities / item catalogue / embedded norm recipes
    Công trình (codes, quantities, serialized material/labour/machine recipes)
        │
        ├──> HaoPhiVatTu ──> Tổng hợp VT ──> Đơn giá chi tiết ──> Giá tổng hợp
        │         │                │                  │                  │
        │         ├── Cước VC      └── resource rates│                  └──> THKP ks duyet
        │         └── Cước bộ                         │
        │                                             └──> Chiết tính ──> Dự thầu
        │                                                       ▲
        └──> quantities/descriptions ───────────────────────────┘

Resource/configuration inputs
    Giá tháng <── Máy <── Đầu vào
        ▲            ▲
        └── labour/material prices; Nhân công is a partial labour-rate schedule

Cost loading parameters
    HSXL ──> Chiết tính and THKP ks duyet
```

`Hệ số` is a hidden presentation shell with repeated headings; the operative percentage configuration is `HSXL`. `Cấu hình` contains static application/configuration metadata but is not referenced by the observed core formulas.

## 3. Sheet catalogue and roles

| Sheet | Role and business meaning | Editable/input status | Main keys | Inputs | Outputs / important formula areas |
|---|---|---|---|---|---|
| `Công trình` | Combined project bill of quantities, work-item catalogue and embedded norm/resource recipe store | Mixed. Project quantities and some direct rates are literal; calculated extensions are formulas | Work-item code `E`; norm code `C`; quantity `P`; standard resource codes inside `AE:AG` | Project take-off and standards/source data | `P` quantities; `Q:T` direct rates; `U:X = quantity × component rate`; `AE:AG` serialized material/labour/machine recipes; consumed by almost every downstream schedule |
| `Giá tháng` | Current resource-price register | Main maintained input for material/labour rates; machine rates are linked from `Máy` | Resource code `B`, normalized code `J` | Literal prices; `Máy!K`; `Đầu vào!D23:D26` | `F6:F70` material prices; `F72:F83` labour prices; `F85:F115` machine rates; `F117:F120` fuel/energy |
| `Đầu vào` | Calculation parameters for labour, machine and fuel | Input/configuration | Parameter label `B` | User-maintained values | Fuel `D23:D26`; fuel add-on factors `D29:D32`; salvage threshold/rate `D35:D36`; rounding `D39:D42`; labour parameters `D5:D20` |
| `Nhân công` (hidden) | Partial labour-rate calculation/audit schedule | Mixed; not authoritative for all active labour rates because several calculated rows return zero while `Giá tháng` contains literal active rates | Labour code `B` | `Đầu vào`, `Giá tháng` | `T8:T15 = ROUND(SUM(H:R), Đầu vào!D40)`; some basic daily wages in `H` are literals |
| `Máy` | Machine-shift rate build | Mixed input/build | Machine code `B` | `Giá tháng`, fuel and rounding parameters from `Đầu vào` | Block totals in `K`; `Giá tháng!F85:F115` links to selected `Máy!K` cells |
| `HaoPhiVatTu` (hidden) | Expanded resource-consumption schedule by work item | Calculated intermediate | Work-item/resource codes | `Công trình`, `Giá tháng`, `Cước VC`, `Cước bộ` | Norm quantities used by `Đơn giá chi tiết` and `Chiết tính`, especially columns `F:H` |
| `Tổng hợp VT` (hidden) | Consolidated resource-price lookup including applicable transport | Calculated intermediate | Resource code | `HaoPhiVatTu`, `Giá tháng`, `Cước VC`, `Cước bộ` | Column `O` is the principal rate consumed by detailed-price sheets |
| `THVT gộp` (hidden) | Further grouped resource summary | Calculated support output | Resource code | `Tổng hợp VT`, `Giá tháng` | Grouped material/resource reporting; not a direct headline-price precedent |
| `Cước VC`, `Cước bộ` (hidden) | Vehicle and manual transport cost schedules | Mixed input/build | Resource code | `Tổng hợp VT` and transport assumptions | Transport additions returned to `HaoPhiVatTu`/`Tổng hợp VT` |
| `NhiênLiệu` (hidden) | Fuel and machine-operator compensation/adjustment schedule | Calculated support schedule | Machine/fuel code | `Công trình`, `HaoPhiVatTu`, `Giá tháng`, `Đầu vào` | Supporting fuel/driver analysis; not a direct precedent of the two headline totals |
| `Đơn giá chi tiết` | Direct unit-cost build by work item | Calculated intermediate | Work-item code and resource code | `Công trình`, `HaoPhiVatTu`, `Tổng hợp VT`, `Giá tháng` | Repeating blocks in `A:H`; resource amount is `ROUND(norm × rate × coefficient,1)`; produces material, labour and machine unit costs only |
| `Giá tổng hợp` | Quantity extension and aggregation of direct unit costs | Calculated intermediate/output | Work-item code | `Công trình`, `Đơn giá chi tiết`, `KLKS BG2 MT` | `E` quantity; `F:H` direct unit costs; `I:K = quantity × unit component`; `L = I+J+K`; section totals such as rows 43, 58, 76 and 113 |
| `HSXL` (hidden) | Operative category-specific cost-loading parameters | Master/configuration input | Category block and parameter row | Literal coefficients | Feeds `Chiết tính` and `THKP ks duyet`; categories use different `TT`, VAT and `LT` rates |
| `Hệ số` (hidden) | Presentation shell for coefficient reports | Mostly calculated labels | Category heading | `Công trình` | Not the operative coefficient source |
| `Chiết tính` | Fully loaded tender unit-price build | Calculated intermediate | Work-item code | Same direct-cost sources as `Đơn giá chi tiết`, plus `HSXL` | Repeating blocks in `A:H`; calculates `T`, `C`, `TT`, `GT`, `TL`, `Cpa`, `Cbc`, `G`, VAT, `Gks`, `LT`, `Gdp` and final loaded unit price |
| `KLKS BG2 MT` | Tender description/line-order schedule | Project input | Tender line number | Mostly literals | Descriptions and ordering used by `Giá tổng hợp` and `Dự thầu` |
| `THKP ks (1)`, `THKP ks (2)` (hidden) | Category/sub-estimate summary variants | Calculated outputs | Cost symbols | `Giá tổng hợp`, `HSXL` | Used for comparison cells on `Dự thầu`; not the main approved total |
| `THKP ks duyet` | Approved survey-cost estimate summary | Final calculated output | Cost symbol (`VL`, `NC`, `M`, `T`, `GT`, etc.) | `Giá tổng hợp`, `HSXL` | Main estimate chain `H7:L29`; headline `J29/L29`; control `O29` |
| `Dự thầu` | Tender presentation by line item and section | Mixed final output plus literal approval snapshots | Work-item code, section | `Công trình`, `Chiết tính`, `KLKS BG2 MT` | `E` quantity; `I` loaded unit price; `J = E×I`; main current total `J47`; literal approval snapshot `J51`; later pages are separate/mostly zero-quantity sections |
| `Cấu hình` (hidden) | Static software/configuration metadata | Configuration | Internal keys | Literals | No observed formula path into the headline calculations |

No usable business named ranges exist. The converted workbook exposes only `_xleta_PHI`, `_xleta_ROUND` and `_xlfn_SINGLE`, all resolving to `#REF!`.

## 4. `Công trình`: combined project quantities and norm catalogue

`Công trình` is a combination of:

- project-specific scope and quantities (`A`, `F`, `P` and dimensional take-off columns);
- work-item/norm catalogue (`C:E`, `G`, `AC:AD`, `AM`);
- embedded resource recipes (`AE` materials, `AF` labour, `AG` machines);
- direct component rates and quantity extensions (`Q:X`);
- adjustment coefficients (`Y:AA`).

The serialized resource records contain a resource code, name, unit, norm quantity per work-item unit, price, coefficients, normalized code and source note. `Z999` and `M999` are percentage-based auxiliary material/machine lines rather than ordinary resources.

### Representative work items

#### CF.11620 — GPS control survey, terrain class II (`Công trình!A16:AM16`)

- Project quantity: `P16 = 8 điểm`.
- Source: `AC16 = Định mức 38/2026/TT-BXD - Phần KS`; machine basis `AD16 = GM38_2026`.
- Adjustments: labour `Z16 = 0.85`, machine `AA16 = 0.85`.
- Materials per point: cement 3 kg; stone 0.01 m³; sand 0.006 m³; nails/wire 0.1 kg; paint 0.2 kg; field notebook 1; auxiliary materials 10%.
- Labour per point: engineer 1.76 công; group-3 labour 4.39 công.
- Machines per point: GPS set 0.16 ca; other machines 10%.

#### CC.21310 — rotary wash drilling, 0–100 m (`Công trình!A66:AM66`)

- Project quantity: `P66 = 1,583 m khoan`.
- Source: `AC66 = Định mức 38/2026/TT-BXD - Phần KS`; machine basis `AD66 = GM38_2026`.
- Materials per metre: alloy bit 0.056; drill rod 0.017 m; rod connector 0.0055 set; casing 0.03 m; casing connector 0.01; single sample tube 0.04 m; double sample tube 0.002; sample box 0.4; group-V timber 0.0035 m³; auxiliary materials 10%.
- Labour: group-3 labour 2.03 công/m.
- Machines: XY-1A drill 0.10 ca/m; other machines 2%.

#### DC.02001 — laboratory soil density test (`Công trình!A77:AM77`)

- Project quantity: `P77 = 338 tests`.
- Source: `AC77 = Định mức 38/2026/TT-BXD - Phần TNVL`; machine basis `AD77 = GM38_2026`.
- Materials per test: electricity 17.44 kWh; distilled water 0.5 l; enamel tray 0.05; auxiliary materials 10%.
- Labour: group-4 labour 0.76 công.
- Machines: drying oven 2.125 ca; dehumidifier 0.003 ca; technical scale 0.003 ca; other machines 5%.

#### KS.4/8 — traffic-camera survey (`Công trình!A113:T113`)

- This is a project-specific/manual labour-only item, not an embedded standard recipe.
- Unit labour cost is literal `S113 = 298,700`; quantity `P113` is blank, so its tender amount is zero.
- This row demonstrates why `Công trình` cannot be treated as only a norm catalogue.

#### CF.21120 — set GPMB boundary stake (`Công trình!A120:AM120`)

- Quantity `P120` is blank in the current workbook.
- Source: `AC120 = Định mức 38/2026/TT-BXD - Phần KS`; machine basis `AD120 = GM38_2026`.
- Materials: cement 13 kg; stone 0.04 m³; sand 0.026 m³; nails/wire 0.1 kg; paint 0.05 kg; notebook 0.5; auxiliary materials 10%.
- Labour: engineer 0.79 công; group-3 labour 1.97 công.
- Machines: total station 0.17 ca; other machines 10%.

#### AG.11112 — precast concrete boundary marker (`Công trình!A142:AM142`)

- Quantity `P142` is blank in the current workbook.
- Source: `AC142 = DM12_2021_XD`; machine basis `AD142 = GM10_2019XD`.
- Materials per m³: PCB40 cement 262.885 kg; sand 0.53592 m³; 1×2 stone 0.884065 m³; water 185.745 l; auxiliary materials 0.5%.
- Labour: group-2 grade 3.0/7, 1.37 công.
- Machines: 250-l mixer 0.095 ca; 1.5-kW vibrator 0.18 ca.

### Future master data versus project data

- **Master candidates:** work-item/norm code, description, unit, norm source/version, material/labour/machine recipe, resource code, resource quantity per unit and default coefficient logic.
- **Project-specific:** selected work items, quantity/take-off, description overrides, project coefficients, price date/location, included/excluded category, manual lump sums and approval snapshots.
- The present workbook stores both in the same row and serializes resource recipes into text fields. Any future model should preserve this distinction without assuming every row is reusable master data.

## 5. Resource pricing model

### Materials

- `Giá tháng!B6:K70` is the active material register.
- `F` is the pre-VAT/current price used in detailed costing; it is mostly literal and therefore user-maintained.
- `G` is the item coefficient.
- `I` holds a price-after-VAT presentation value, but `Đơn giá chi tiết` uses consolidated pre-VAT rates from `Tổng hợp VT!O`.
- `K` stores source text such as decisions and price notices.

### Labour

- Active labour rates are in `Giá tháng!F72:F83`.
- `Nhân công!T8:T15` is a partial formula schedule: `ROUND(SUM(H:R), Đầu vào!D40)`.
- Several `Nhân công` rows calculate to zero because their base wage cells are blank, while corresponding `Giá tháng` rates are literal. Therefore the current calculation treats `Giá tháng` as the authoritative active register, not `Nhân công` alone.

### Machines

- `Máy` builds shift rates from depreciation, repair, other cost, fuel/energy and, where present, operator labour.
- Example: `Máy!K49 = ROUND(K50+K52, Đầu vào!D41)` for a 25-CV diesel pump; `K51 = fuel norm × fuel price × auxiliary-fuel factor` and `K52` sums depreciation/repair/other cost.
- `Giá tháng!F85:F115` links selected machine totals from `Máy!K`.

### Fuel, coefficients and rounding

- Fuel prices: `Đầu vào!D23:D26` (diesel 28,540; mazut 17,680; electricity 2,204.0655; petrol 21,830).
- Auxiliary fuel factors: `D29:D32` (1.03 diesel, 1.00 mazut, 1.05 electricity, 1.02 petrol).
- Salvage: threshold `D35 = 30 million`; recovery rate `D36 = 10%`.
- Rounding controls: price `D39 = 1`; labour/operator rate `D40 = 0`; total rate `D41 = 0`; wage coefficient `D42 = 3`.
- Cost-loading parameters are held in category blocks on `HSXL`, not `Đầu vào`.

### Workbook-to-data-model mapping

| Proposed entity | Workbook source |
|---|---|
| `Resource` | `Giá tháng!B:D,J` plus machine/labour codes |
| `MaterialPrice` | `Giá tháng!F6:F70`, coefficient `G`, source `K` |
| `LaborRate` | Active `Giá tháng!F72:F83`; partial build/audit in `Nhân công` |
| `MachineRate` | `Máy!K` and linked `Giá tháng!F85:F115` |
| `CalculationParameter` | `Đầu vào!D5:D42`, category blocks in `HSXL!D`, item coefficients `Công trình!Y:AA` |
| `EffectiveDate` | Not normalized; embedded in titles/notes such as `Giá tháng!K` and `Máy!A2` |
| `Version` | Not normalized; embedded in norm/source codes such as `GM38_2026`, `DM12_2021_XD` |
| `Source` | `Giá tháng!K`, `Công trình!AC:AD`, recipe notes in `AE:AG` |

## 6. `Đơn giá chi tiết`: direct unit cost only

For CF.11620 (`Đơn giá chi tiết!A41:H58`):

- Material line formula pattern: `H = ROUND(E × F × G,1)`, where `E` is norm quantity, `F` is consolidated resource rate and `G` is coefficient.
- Materials total: `H42 = ROUND(H50,1) = 34,642.1`.
- Labour total: `H51 = ROUND(H54,1) = 1,852,359.6`.
- Machine total: `H55 = ROUND(H58,1) = 80,827.6`.
- Auxiliary material: `H49 = ROUND(E49 × F49 / 100,1)` with 10% applied to the ordinary material subtotal.
- Other machine: `H57 = ROUND(E57 × F57 / 100,1)` with 10% applied to the identified machine subtotal.

There are no `C`, `GT`, `TL`, VAT, `LT` or contingency rows in this block. Therefore `Đơn giá chi tiết` is a **direct unit-cost schedule only**. Indirect costs and tax appear later in `Chiết tính` or at aggregate level in `THKP ks duyet`.

## 7. `Giá tổng hợp`: quantity × direct unit cost

`Giá tổng hợp` extends quantities separately for material, labour and machines:

- `E` = project quantity from `Công trình!P`.
- `F:H` = direct unit component costs from `Đơn giá chi tiết`.
- `I = ROUND(E×F,1)`, `J = ROUND(E×G,1)`, `K = ROUND(E×H,1)`.
- `L = I+J+K`.

Worked example CF.11620 (`Giá tổng hợp!A15:M15`):

- Quantity `E15 = 8` from `Công trình!P16`.
- Direct material `F15 = 34,642.1` from `Đơn giá chi tiết!H42`; extended `I15 = 277,136.8`.
- Direct labour `G15 = 1,852,359.6` from `Đơn giá chi tiết!H51`; extended `J15 = 14,818,876.8`.
- Direct machine `H15 = 80,827.6` from `Đơn giá chi tiết!H55`; extended `K15 = 646,620.8`.
- Direct total `L15 = 15,742,634.4`.

No overhead, VAT or contingency is added in `Giá tổng hợp`.

The cells feeding `THKP ks duyet` are:

- Field material: `Giá tổng hợp!I76 + I43 = 79,545,152`.
- Laboratory material: `I113 = 58,216,018`.
- Field labour: `J76 + J43 = 1,565,161,618`.
- Laboratory labour: `J113 = 353,314,991`.
- Field machines: `K76 + K43 = 32,173,611`.
- Laboratory machines: `K113 = 37,104,593`.
- Safety/waterway branch is disabled by multiplication by zero (`THKP ks duyet!K9:K13` and `Giá tổng hợp!K116`).

## 8. `Chiết tính`: fully loaded tender unit price

The general block is:

1. `VL`, `NC`, `M`: direct material, labour and machine unit costs.
2. `T = VL + NC + M`.
3. `C`: category-specific overhead, usually 60% of labour; for construction-style marker-production blocks it is 60% of `T`.
4. `TT`: other indirect cost, 0%, 1% or 3% of `T` by category.
5. `GT = C + TT`.
6. `TL = (T + GT) × 6%`.
7. `Cpa` and `Cbc`: survey plan and report costs, normally 1.5% and 2.5%; marker-production blocks use 2% and 3%; some components are explicitly disabled by `×0`.
8. `Cpvks = Cpa + Cbc`.
9. `G = T + GT + TL + Cpvks`.
10. VAT (`GTGT`) = 8% or 10% of `G` by category.
11. `Gks = G + VAT`.
12. `LT` = 0%, 2% or 2.2% of `Gks` by category.
13. `Gdp = 0` in the inspected tender blocks.
14. Final loaded unit price = `ROUND(Gks + LT + Gdp,0)`.

Representative outcomes:

| Work item / category | T | C base/rate | TT | VAT | Cpa/Cbc | LT | Gdp | Final |
|---|---:|---|---:|---:|---|---:|---:|---:|
| CF.11620 topography (`H91:H106`) | 1,967,829.3 | NC × 60% | 0% | 10% | 1.5% / 2.5% | 2% | 0 | 3,808,696 |
| CC.21310 geotechnical drilling (`H405:H420`) | 733,074.0 | NC × 60% | 0% | 10% | 1.5% / 2.5% | 2% | 0 | 1,414,311 |
| DC.02001 laboratory (`H600:H615`) | 357,525.0 | NC × 60% | 0% | 10% | Cpa disabled by `×0`; Cbc 2.5% | 0% | 0 | 634,808 |
| KS.4/8 traffic (`H1452:H1467`) | 298,700.0 | NC × 60% | 1% | 8% | 1.5% / 2.5% | 2% | 0 | 584,015 |
| CF.21120 GPMB stake (`H1566:H1581`) | 1,065,580.7 | NC × 60% | 3% | 8% | 1.5% / 2.5% | 2% | 0 | 2,045,481 |
| AG.11112 GPMB marker (`H1653:H1668`) | 1,460,669.6 | T × 60% | 3% | 8% | 2% / 3% | 2% | 0 | 2,919,165 |
| AG.11112 road marker (`H1936:H1951`) | 1,460,669.6 | T × 60% | 3% | 8% | 2% / 3% | 2.2% | 0 | 2,924,889 |

Thus `Chiết tính` is the fully loaded tender unit-price engine. `Dự thầu` then applies additional presentation rounding: active main survey lines use `ROUNDDOWN(Chiết tính final,-3)` before multiplying by quantity.

## 9. `THKP ks duyet`: exact approved-estimate chain

| Component | Field | Laboratory | Total | Formula logic |
|---|---:|---:|---:|---|
| Material | 79,545,152.0 | 58,216,018.0 | 137,761,170.0 | From `Giá tổng hợp!I76`, `I43`, `I113` |
| Labour | 1,565,161,618.0 | 353,314,991.0 | 1,918,476,609.0 | From `J76`, `J43`, `J113` |
| Machines | 32,173,611.0 | 37,104,593.0 | 69,278,204.0 | From `K76`, `K43`, `K113` |
| `T` | 1,676,880,381.0 | 448,635,602.0 | 2,125,515,983.0 | `VL+NC+M` |
| `GT` | 939,096,970.8 | 211,988,994.6 | 1,151,085,965.4 | `C = NC×60%`; `TT=0` |
| `TL` | 156,958,641.1 | 39,637,475.8 | 196,596,116.9 | Field `(T+GT)×6%`; laboratory uses `HSXL!D73=6%` |
| `Cpa` | 41,594,039.9 | 0.0 | 41,594,039.9 | 1.5%; laboratory disabled with `×0` |
| `Cbc` | 69,323,399.8 | 17,506,551.8 | 86,829,951.6 | 2.5% |
| `Cpvks` | 110,917,439.7 | 17,506,551.8 | 128,423,991.5 | `Cpa+Cbc` |
| `G` before VAT | 2,883,853,432.6 | 717,768,624.2 | 3,601,622,056.8 | `T+GT+TL+Cpvks` |
| VAT | 288,385,343.3 | 71,776,862.4 | 360,162,205.7 | `G×10%` |
| `Gks` | 3,172,238,775.9 | 789,545,486.6 | 3,961,784,262.5 | `G+VAT` |
| `LT` | 63,444,775.5 | 0.0 | 63,444,775.5 | `Gks×2%`; laboratory disabled with `×0` |
| `Gdp` | 317,223,877.6 | 78,954,548.7 | 396,178,426.3 | `Gks×10%` |
| Final | 3,552,907,429 | 868,500,035 | **4,421,407,464** | `ROUND(Gks+LT+Gdp,0)` by branch, then sum |

Exact headline formulas:

- `H29 = ROUND(H26+H27+H28,0) = 3,552,907,429`.
- `I29 = ROUND(I26+I27+I28,0) = 868,500,035`.
- `J29 = SUM(H29:I29) = 4,421,407,464`.
- `O29 = L26+L27+L28 = 4,421,407,464.3` is the unrounded control.

## 10. `Dự thầu`: line sources and totals

Every detail line follows this pattern:

- Description/code/unit from `Công trình` or `KLKS BG2 MT`.
- Quantity `E = ROUND(Công trình!P,4)`.
- Direct component displays `F:H` from `Chiết tính` component totals or, for manual items, from `Công trình!Q:T`.
- Loaded tender unit price `I` from the final `Chiết tính!H` cell.
- Main active survey lines use `ROUNDDOWN(final,-3)`; later ancillary pages generally use `ROUND(final,1)`.
- Amount `J = quantity × unit price`, usually rounded to 0.1; section totals are rounded to whole đồng.

### Lines included in the current headline total

| Row | Code | Quantity | Loaded price | Amount |
|---:|---|---:|---:|---:|
| 15 | CF.11620 | 8 | 3,808,000 | 30,464,000.0 |
| 16 | CG.11320 | 1.942 | 1,958,000 | 3,802,436.0 |
| 17 | CK.11520 | 0.1171 | 130,321,000 | 15,260,589.1 |
| 18 | CK.31510 | 0.0209 | 113,987,000 | 2,382,328.3 |
| 19 | CH.11120 | 17.33 | 1,148,000 | 19,894,840.0 |
| 20 | CH.11410 | 2.09 | 1,832,000 | 3,828,880.0 |
| 21 | CH.11220 | 27.48 | 1,407,000 | 38,664,360.0 |
| 24 | CC.21110 | 114 | 1,235,000 | 140,790,000.0 |
| 25 | CC.21310 | 1,583 | 1,414,000 | 2,238,362,000.0 |
| 26 | CC.31310 | 141 | 1,998,000 | 281,718,000.0 |
| 27 | MTC I-III | 141 | 61,000 | 8,601,000.0 |
| 28 | CE.11410 | 711 | 459,000 | 326,349,000.0 |
| 29 | CE.11310 | 63 | 824,000 | 51,912,000.0 |
| 32 | DC.02001 | 338 | 634,000 | 214,292,000.0 |
| 33 | DC.02002 | 338 | 128,000 | 43,264,000.0 |
| 34 | DC.02003 | 338 | 234,000 | 79,092,000.0 |
| 35 | DC.02004 | 338 | 387,000 | 130,806,000.0 |
| 36 | DC.02006 | 338 | 76,000 | 25,688,000.0 |
| 37 | DC.02009 | 338 | 72,000 | 24,336,000.0 |
| 38 | DC.02007 | 338 | 188,000 | 63,544,000.0 |
| 39 | DC.02007 | 24 | 754,000 | 18,096,000.0 |
| 40 | DC.02011 | 72 | 906,000 | 65,232,000.0 |
| 41 | DC.02004 | 58 | 387,000 | 22,446,000.0 |
| 42 | DC.02003 | 58 | 234,000 | 13,572,000.0 |
| 43 | DC.02004 | 155 | 387,000 | 59,985,000.0 |
| 44 | DC.02010 | 155 | 182,000 | 28,210,000.0 |
| 45 | DC.02008 | 155 | 1,147,000 | 177,785,000.0 |

Rows 13 and 14 have zero quantity. The current totals are:

- `J22 = ROUND(SUM(J6:J21),0) = 114,297,433`.
- `J30 = ROUND(SUM(J23:J29),0) = 3,047,732,000`.
- `J46 = ROUND(SUM(J31:J45),0) = 966,348,000`.
- `J47 = J22+J30+J46 = 4,128,377,433`.
- `J49 = SUM(J15:J46)/2 = 4,128,377,433.2`; division by two compensates for summing both detail rows and the three section totals.
- `J50 = 4,128,377,433` is a literal copy of the live result.

Later pages cover material-source/waste-site surveys (`65:68`), traffic surveys (`74:79`), GPMB/road-marker work (`85:128`). Most have zero quantities. The nonzero GPMB marker-production page totals `J108 = 532,718`; it is not included in `J47`.

## 11. Provenance of 4,142,692,903

Evidence:

- `Dự thầu!J51` contains the literal number `4142692903`, not a formula.
- The label is `I51 = "Giá trị duyệt"` and `O51 = "chưa tính 10% dự phòng"`.
- No other cell in the workbook contains the same value.
- The nearest live calculated cells are `J47 = 4,128,377,433` and `J49 = 4,128,377,433.2`.
- `J50` is already a literal copy of the live rounded result, which shows that the author used literal presentation snapshots in this area.
- `J130 = 407,741,802` is another literal labelled `DP phí`; `J131 = J51+J130 = 4,550,434,705`.

Conclusion: `J51` is **not derived from the current workbook calculation**. It is a manually stored approval/presentation value. The workbook supports the inference that it was copied from an approval or earlier calculation, but it does not contain the upstream source needed to prove which one. Calling it a current “manual override” would be misleading because no formula is being overridden in that cell; it is better described as an **unlinked approved-value snapshot**.

## 12. Reconciliation of the two headline values

| Comparison | Amount |
|---|---:|
| `THKP ks duyet!J29` | 4,421,407,464 |
| Less `THKP ks duyet` contingency `J28` | (396,178,426.3) |
| Approved-estimate value before contingency (`J26+J27`) | 4,025,229,038.0 |
| Current calculated tender total `Dự thầu!J47` | 4,128,377,433 |
| Literal approved snapshot `Dự thầu!J51` | 4,142,692,903 |
| `J51 − J47` | 14,315,470 |
| `THKP J29 − Dự thầu J51` | 278,714,561 |

The remaining differences after removing contingency arise from different calculation granularity and rules:

- aggregate estimate loading in `THKP ks duyet` versus item-level loading in `Chiết tính`;
- category-specific 8%/10% VAT and 0%/2%/2.2% temporary-facility rates in tender unit prices;
- `TT` at 0%/1%/3% by category;
- survey-plan/report components disabled with `×0` for some categories;
- tender loaded-unit-price rounding, including `ROUNDDOWN(...,-3)` for the main active lines;
- `J51` itself is not the current calculated tender subtotal.

## 13. Integrity and traceability limitations

- The source is a legacy `.xls`; it was inspected through a temporary `.xlsx` conversion without editing the original.
- Two external links remain in the workbook. `THKP ks duyet!L32` and related cells reference `'[2]Tong hop'!D13`; `Máy!D178` and `D188` reference `[1]Trang_tính2!C23`. The linked source workbooks were not supplied, so those values can only be treated as cached external results.
- The external BIM value at `THKP ks duyet!L32` affects the broader `L33` total, not the `4,421,407,464` survey-cost headline at `J29/L29`.
- The workbook contains no usable business named ranges and no normalized effective-date/version fields.
- No formula or source cell inside the workbook establishes the origin of `Dự thầu!J51`.
- No cached Excel error value (`#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`, `#NUM!`, `#NULL!`, `#SPILL!` or `#CALC!`) was found in the inspected key-sheet ranges. This does not resolve the broken defined names or missing external-link sources noted above.
