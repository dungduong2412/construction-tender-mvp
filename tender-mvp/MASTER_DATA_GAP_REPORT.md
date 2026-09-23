# Master Data Gap Report

**Project:** Construction Tender MVP — ĐT.827E  
**Reference XLS:** DuToan KS CauBinhGoi 2609.21 DuThau.xls  
**Date:** 2026-09-23  

---

## 1. XLS Analysis Summary

The reference workbook `DuToan KS CauBinhGoi 2609.21 DuThau.xls` contains 62 sheets. This MVP performed a **one-time, read-only** analysis. The following sheets were inspected for seed data:

| Sheet | Used? | Notes |
|-------|-------|-------|
| Đơn giá chi tiết | ✅ Yes | Primary source for unit prices (items KS-001 to KS-030) |
| Giá tổng hợp | ✅ Yes | Report-level pricing (KS-020, KS-021) |
| Hệ số | ✅ Yes | Coefficients: K_TT, K_XD, K_NVCP seeded (all = 1.0 base) |
| Đầu vào | ⚠️ Partial | Input parameters read; some depend on external price indices not available offline |
| Giá tháng | ⚠️ Partial | Monthly price index — K_TT set to 1.0; requires monthly update from Ministry |
| Chiết tính | ❌ Skipped | Detailed cost breakdown sheets; would require wholesale port of formulas |
| Dự thầu | ✅ Reference only | Used as format reference for Excel export layout |
| Remaining 55 sheets | ❌ Skipped | Cover machinery rates, labour rates, material prices for construction phase; not in scope for survey BOQ |

---

## 2. Items Seeded vs Unresolved

### Seeded Items (items_v1.json — 30 items)

| Code | Description | Unit | Source |
|------|-------------|------|--------|
| KS-001 | Đo vẽ bình đồ 1/500 đồng bằng | ha | Đơn giá chi tiết |
| KS-002 | Đo vẽ bình đồ 1/500 đồi núi | ha | Đơn giá chi tiết |
| KS-003 | Đo vẽ bình đồ 1/200 đồng bằng | ha | Đơn giá chi tiết |
| KS-004 | Đo trắc dọc tuyến đường | km | Đơn giá chi tiết |
| KS-005 | Đo trắc ngang 20m/mặt cắt | km | Đơn giá chi tiết |
| KS-006 | Khoan đường 0–30m, đất cấp II | m | Đơn giá chi tiết |
| KS-007 | Khoan cầu 0–60m, đất cấp II | m | Đơn giá chi tiết |
| KS-008 | Lấy mẫu đất nguyên dạng | mẫu | Đơn giá chi tiết |
| KS-009 | Thí nghiệm cơ lý đất (bộ cơ bản) | mẫu | Đơn giá chi tiết |
| KS-010 | Thí nghiệm thành phần hạt | TN | Đơn giá chi tiết |
| KS-011 | Thí nghiệm CBR ngâm nước | TN | Đơn giá chi tiết |
| KS-012 | Thí nghiệm cắt trực tiếp | TN | Đơn giá chi tiết |
| KS-013 | Thí nghiệm nén cố kết | TN | Đơn giá chi tiết |
| KS-014 | Thí nghiệm xuyên tiêu chuẩn SPT | TN | Đơn giá chi tiết |
| KS-015 | Bơm hút thí nghiệm thủy văn | hố | Đơn giá chi tiết |
| KS-016 | Đo vẽ địa hình mặt cắt dọc tim đường | km | Đơn giá chi tiết |
| KS-017 | Khảo sát thủy văn, thu thập tài liệu | km | Đơn giá chi tiết |
| KS-018 | Đo đạc mặt cắt ngang sông tại cầu | mặt cắt | Đơn giá chi tiết |
| KS-019 | Thí nghiệm nước | TN | Đơn giá chi tiết |
| KS-020 | Lập báo cáo khảo sát địa hình | báo cáo | Giá tổng hợp |
| KS-021 | Lập báo cáo khảo sát địa chất | báo cáo | Giá tổng hợp |
| KS-022 | Đo trắc dọc sông suối | km | Đơn giá chi tiết |
| KS-023 | Xây dựng lưới khống chế trắc địa | điểm | Đơn giá chi tiết |
| KS-024 | Thí nghiệm độ ẩm tự nhiên | TN | Đơn giá chi tiết |
| KS-025 | Thí nghiệm giới hạn Atterberg | TN | Đơn giá chi tiết |
| KS-026 | Thí nghiệm dung trọng tự nhiên | TN | Đơn giá chi tiết |
| KS-027 | Thí nghiệm tỷ trọng hạt đất | TN | Đơn giá chi tiết |
| KS-028 | Đóng cọc thử nghiệm D300 | m | Đơn giá chi tiết |
| KS-029 | Khoan đường 0–30m, đất cấp III | m | Đơn giá chi tiết |
| KS-030 | Khoan cầu 0–60m, đất cấp III | m | Đơn giá chi tiết |

---

## 3. PDF Items Likely Unresolved After AI Mapping

The following PDF BOQ rows (from the 4-page fixture) are at risk of remaining unresolved:

| Row # | Description | Reason |
|-------|-------------|--------|
| 6 | Xây dựng lưới khống chế trắc địa | PDF unit "điểm" matches KS-023 — should resolve |
| 27 | Đo trắc dọc sông suối (qty 0,030 km) | Very small quantity — may trigger unit confusion; should resolve via KS-022 |
| 29–30 | Lập báo cáo (hành chính) | Usually resolves to KS-020/KS-021 |
| 31 | Đo vẽ địa hình mặt cắt dọc (qty 342,34 km) | Unusual large quantity — should resolve via KS-016 |
| 32 | Xây dựng lưới giải tích (section V) | Repeated row number — must be resolved by section context, not row number alone |
| 33 | Đóng cọc thử nghiệm D300 | Should resolve to KS-028 |
| 34 | Tổng hợp lập dự toán | No direct master item — **UNRESOLVED** — not covered by current seed |

### Items with No Master Coverage (Gap)

| PDF Description | Gap Reason |
|-----------------|------------|
| Tổng hợp lập dự toán | This item was not extractable from the reference XLS for ĐT.827E |
| Any items beyond row 34 in the full PDF (~82 items) | Fixture covers only representative sample; full PDF processing needed once real parser API is available |
| Terrain-specific rates for hilly/mountain drilling | XLS covers đất cấp II/III; terrain-class coefficients for rock classes not seeded |
| Labour/equipment overhead rates | Chiết tính sheets not imported; would need separate seeding pass |

---

## 4. Unit Rules and Coefficient Gaps

- **K_TT (Giá tháng):** Set to 1.0. Actual value must be sourced from the Ministry of Construction monthly price bulletin for the bid month. **This must be updated before any real bid.**
- **K_XD:** Set to 1.0. Actual regional coefficient varies by province; must be confirmed with project owner.
- **ha vs 100ha, TN vs thí nghiệm:** Approved unit rules seeded for 100m→m and 100ha→ha. The TN/thí nghiệm equivalence is treated as a forbidden silent conflation — an explicit rule must be added by a domain expert before these units can be auto-converted.

---

## 5. Recommended Next Steps

1. **Obtain real parser API credentials** and run the full PDF through Azure Document Intelligence to extract all ~82 rows.
2. **Expand master-data seed** to cover all extracted rows; add rock-class drilling variants and Tổng hợp lập dự toán.
3. **Set K_TT and K_XD** from the official monthly price bulletin for ĐT.827E project location and bid month.
4. **Add TN↔thí nghiệm unit rule** if officially confirmed by the project owner.
5. **Import Chiết tính sheets** for labour and equipment rate breakdowns if needed for audit transparency.
6. **Run full AI mapping** with real OpenAI API key (or Azure OpenAI) and validate all 82 rows.
7. **User review session** — domain expert reviews all unresolved rows, records overrides, approves bid.
8. **Do NOT deploy to production** or share the Excel output as a formal bid without completing steps 1–7.
