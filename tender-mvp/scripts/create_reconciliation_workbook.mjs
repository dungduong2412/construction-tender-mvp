#!/usr/bin/env node
import fs from "node:fs/promises";
const artifactToolPath = process.env.ARTIFACT_TOOL_MODULE;
if (!artifactToolPath) throw new Error("ARTIFACT_TOOL_MODULE must point to artifact_tool.mjs");
const { SpreadsheetFile, Workbook } = await import(artifactToolPath);

const [inputPath, outputPath] = process.argv.slice(2);
if (!inputPath || !outputPath) {
  throw new Error("Usage: create_reconciliation_workbook.mjs INPUT.json OUTPUT.xlsx");
}

const audit = JSON.parse(await fs.readFile(inputPath, "utf8"));
let ks48 = null;
try {
  ks48 = JSON.parse(await fs.readFile(`${inputPath.substring(0, inputPath.lastIndexOf("/"))}/ks4_8_dependency.json`, "utf8"));
} catch {
  // Optional evidence file; the row audit remains valid without it.
}
const workbook = Workbook.create();
const navy = "#17365D";
const blue = "#D9EAF7";
const green = "#E2F0D9";
const amber = "#FFF2CC";
const red = "#FCE4D6";
const grey = "#E7E6E6";
const literalFormula = (value) => typeof value === "string" && value.startsWith("=") ? `Formula: ${value}` : value;

function styleHeader(range) {
  range.format.fill = navy;
  range.format.font = { bold: true, color: "#FFFFFF" };
  range.format.wrapText = true;
  range.format.verticalAlignment = "center";
}

function finishSheet(sheet, headerRange, widths = []) {
  styleHeader(sheet.getRange(headerRange));
  sheet.freezePanes.freezeRows(1);
  sheet.showGridLines = false;
  widths.forEach(([column, width]) => { sheet.getRange(`${column}:${column}`).format.columnWidth = width; });
  sheet.getUsedRange().format.verticalAlignment = "top";
}

const summary = workbook.worksheets.add("Summary");
summary.getRange("A1:B1").values = [["Construction Tender source reconciliation", "Value"]];
const summaryRows = [
  ["Audit status", audit.status === "INCOMPLETE_MISSING_AUTHORITATIVE_INPUTS" ? "INCOMPLETE — missing authoritative inputs" : audit.status],
  ["PDF rows independently reconciled", Number(audit.reconciliation.pdf_rows)],
  ["Historical Azure extraction rows", Number(audit.reconciliation.historical_azure_extraction_count)],
  ["Numeric billable source rows", Number(audit.reconciliation.numeric_billable_rows)],
  ["Structural / non-billable source rows", Number(audit.reconciliation.non_billable_count)],
  ["Nested subsection rows corrected", Number(audit.reconciliation.nested_subsections_corrected)],
  ["Verified mapped/priced rows", Number(audit.reconciliation.verified_mapped_rows)],
  ["Blocked rows", Number(audit.reconciliation.blocked_rows)],
  ["All 95 rows have treatment", Boolean(audit.reconciliation.all_rows_have_treatment)],
  ["Tender partial total (not official)", Number(audit.reconciliation.tender_partial_total)],
  ["Approval partial total, aggregate-first (not official)", Number(audit.reconciliation.approval_partial_total)],
  ["Azure status", audit.source.azure_status],
  ["Azure REST API version", audit.source.azure_api_version],
  ["Azure model", audit.source.azure_model_id],
  ["Azure pages / tables", `${audit.source.azure_page_count} / ${audit.source.azure_table_count}`],
  ["Workbook sheets", Number(audit.source.workbook_sheet_count)],
  ["Totals note", audit.reconciliation.total_note],
];
summary.getRange("A2").write(summaryRows);
summary.getRange("B2").format.fill = red;
summary.getRange("B8:B9").format.fill = amber;
summary.getRange("B11:B12").format.numberFormat = "#,##0";
summary.getRange("A19:B19").values = [["Workbook formula parity", "Difference (VND)"]];
styleHeader(summary.getRange("A19:B19"));
summary.getRange("A20:B24").values = [
  ["Tender section sum − Dự thầu!J47", Number(audit.workbook_total_evidence.tender.formula_parity_difference)],
  ["Dự thầu!J49 control − J47", Number(audit.workbook_total_evidence.tender.control_minus_formula)],
  ["Tender snapshot J51 − current formula J47", Number(audit.workbook_total_evidence.tender.snapshot_minus_current_formula)],
  ["Approval J29 − rounded O29", Number(audit.workbook_total_evidence.approval.formula_parity_difference)],
  ["Approval J29 − tender snapshot J51", Number(audit.workbook_total_evidence.approval.approval_minus_tender_snapshot)],
];
summary.getRange("B20:B24").format.numberFormat = "#,##0.0";
summary.getRange("A1:B24").format.wrapText = true;
finishSheet(summary, "A1:B1", [["A", 44], ["B", 40]]);

const rows = workbook.worksheets.add("Rows");
const rowHeaders = [
  "Source #", "Page", "STT", "Status", "Treatment", "Description", "Source unit", "Source qty",
  "Mapped item", "Mapped description", "Master unit", "Unit match", "Conversion", "Converted qty",
  "Category", "Material", "Labour", "Machine", "Tender loaded unit", "Tender rounded unit",
  "Tender extension", "Approval indicative unit", "Master provenance", "Loaded price provenance", "Reason / note",
  "Price status", "Price display", "Price editable", "Source origin", "Source provenance", "Azure polygon",
];
rows.getRange("A1").write([rowHeaders]);
const rowValues = audit.rows.map((row) => [
  row.source_index, row.page, row.stt, row.status, row.treatment, row.description, row.source_unit,
  row.source_quantity === null ? null : Number(row.source_quantity), row.mapped_work_item ?? null,
  row.mapped_description ?? null, row.master_unit ?? null, row.unit_match ?? null,
  row.conversion_factor === undefined ? null : Number(row.conversion_factor),
  row.converted_quantity === undefined ? null : Number(row.converted_quantity), row.category ?? null,
  row.direct_components ? Number(row.direct_components.material) : null,
  row.direct_components ? Number(row.direct_components.labour) : null,
  row.direct_components ? Number(row.direct_components.machine) : null,
  row.tender ? Number(row.tender.loaded_unit_price_used) : null,
  row.tender ? Number(row.tender.rounded_unit_price) : null,
  row.tender ? Number(row.tender.extension) : null,
  row.approval ? Number(row.approval.indicative_unit_price_only) : null,
  row.workbook_provenance?.master_row ?? null,
  row.workbook_provenance?.loaded_price_cell ?? null,
  row.reason ?? row.approval?.note ?? null, row.pricing_availability ?? null, row.price_display ?? null,
  Boolean(row.unit_price_editable), row.source_origin ?? null, row.source_provenance ?? null,
  Boolean(row.azure_polygon_available),
]);
rows.getRange("A2").write(rowValues);
rows.getRange(`H2:H${rowValues.length + 1}`).format.numberFormat = "0.000";
rows.getRange(`M2:N${rowValues.length + 1}`).format.numberFormat = "0.000";
rows.getRange(`P2:V${rowValues.length + 1}`).format.numberFormat = "#,##0.0";
rows.getRange(`A2:AE${rowValues.length + 1}`).format.wrapText = true;
finishSheet(rows, "A1:AE1", [["A", 9], ["B", 7], ["C", 10], ["D", 12], ["E", 24], ["F", 58], ["G", 13], ["H", 12], ["I", 18], ["J", 58], ["K", 13], ["L", 18], ["M", 11], ["N", 13], ["O", 24], ["P", 16], ["Q", 16], ["R", 16], ["S", 18], ["T", 18], ["U", 18], ["V", 20], ["W", 28], ["X", 25], ["Y", 55], ["Z", 18], ["AA", 18], ["AB", 14], ["AC", 25], ["AD", 70], ["AE", 15]]);

const norms = workbook.worksheets.add("Norms and prices");
const normHeaders = ["Source #", "Mapped item", "Resource type", "Resource code", "Description", "Unit", "Norm", "Unit price", "Line total", "Pricing rule", "Workbook provenance"];
norms.getRange("A1").write([normHeaders]);
const normValues = [];
for (const row of audit.rows) {
  for (const line of row.norms ?? []) {
    normValues.push([row.source_index, row.mapped_work_item, line.resource_type, line.code, line.description, line.unit, Number(line.norm_quantity), Number(line.unit_price), Number(line.line_total), line.pricing_rule, line.provenance]);
  }
}
if (normValues.length) norms.getRange("A2").write(normValues);
norms.getRange(`G2:I${Math.max(2, normValues.length + 1)}`).format.numberFormat = "#,##0.000";
finishSheet(norms, "A1:K1", [["A", 9], ["B", 18], ["C", 14], ["D", 18], ["E", 42], ["F", 12], ["G", 12], ["H", 16], ["I", 16], ["J", 24], ["K", 42]]);

const blockers = workbook.worksheets.add("Blockers");
blockers.getRange("A1:E1").values = [["Source #", "Page", "Description", "Exact missing input / conflict", "Required resolution"]];
const blockerValues = audit.blockers.map((item) => [item.source_index, item.page, item.description, item.reason, "Provide an authoritative matching code/norm/rate or a signed equivalence/conversion decision."]);
blockers.getRange("A2").write(blockerValues);
blockers.getRange(`A2:E${blockerValues.length + 1}`).format.fill = red;
blockers.getRange(`A2:E${blockerValues.length + 1}`).format.wrapText = true;
finishSheet(blockers, "A1:E1", [["A", 10], ["B", 8], ["C", 60], ["D", 70], ["E", 58]]);

const parity = workbook.worksheets.add("Formula parity");
parity.getRange("A1:G1").values = [["Branch", "Cell", "Formula / classification", "Cached value", "Compared value", "Difference", "Conclusion"]];
const t = audit.workbook_total_evidence.tender;
const a = audit.workbook_total_evidence.approval;
parity.getRange("A2:G8").values = [
  ["Tender", t.formula_total_cell, literalFormula(t.formula), Number(t.formula_total), Number(t.recomputed_sum), Number(t.formula_parity_difference), "Exact parity"],
  ["Tender control", t.control_cell, literalFormula(t.control_formula), Number(t.control_value), Number(t.formula_total), Number(t.control_minus_formula), "0.2 VND floating-point difference"],
  ["Tender rounded copy", t.rounded_copy_cell, "Literal cached copy", Number(t.rounded_copy_value), Number(t.formula_total), Number(t.rounded_copy_value) - Number(t.formula_total), "Matches current formula"],
  ["Tender snapshot", t.snapshot_cell, "Unlinked literal snapshot", Number(t.snapshot_value), Number(t.formula_total), Number(t.snapshot_minus_current_formula), "Not formula parity target"],
  ["Approval", a.formula_total_cell, literalFormula(a.formula), Number(a.formula_total), Number(a.rounded_control), Number(a.formula_parity_difference), "Exact rounded parity"],
  ["Approval control", a.unrounded_control_cell, literalFormula(a.unrounded_formula), Number(a.unrounded_value), Number(a.formula_total), Number(a.unrounded_value) - Number(a.formula_total), "0.3 VND before rounding"],
  ["Approval vs tender snapshot", "J29 − J51", "Explicit branch difference", Number(a.formula_total), Number(t.snapshot_value), Number(a.approval_minus_tender_snapshot), "Includes contingency and branch-rule differences"],
];
parity.getRange("D2:F8").format.numberFormat = "#,##0.0";
finishSheet(parity, "A1:G1", [["A", 22], ["B", 24], ["C", 42], ["D", 18], ["E", 18], ["F", 18], ["G", 42]]);

if (ks48) {
  const ks = workbook.worksheets.add("KS4_8 dependency");
  ks.getRange("A1:F1").values = [["Scope", "Work item", "Labour rate", "Master cell", "Tender unit price", "Conclusion / missing input"]];
  const values = ks48.camera_survey_items.map((item) => ["Camera survey", item.work_item, item.labour_rate, item.master_cell, item.tender_unit_price, ks48.safe_runtime_treatment]);
  values.push(["Conflicting same code", ks48.conflicting_same_code_item.work_item, ks48.conflicting_same_code_item.labour_rate, ks48.conflicting_same_code_item.master_cell, ks48.conflicting_same_code_item.tender_unit_price, ks48.missing_external_input]);
  ks.getRange("A2").write(values);
  ks.getRange("C2:C4").format.numberFormat = "#,##0";
  ks.getRange("E2:E4").format.numberFormat = "#,##0";
  ks.getRange("A2:F4").format.wrapText = true;
  finishSheet(ks, "A1:F1", [["A", 22], ["B", 55], ["C", 16], ["D", 22], ["E", 18], ["F", 72]]);
}

summary.getRange("A1:B24").format.borders = { style: "continuous", color: "#BFBFBF" };
rows.getRange(`A1:AE${rowValues.length + 1}`).format.borders = { style: "continuous", color: "#D9D9D9" };
norms.getRange(`A1:K${Math.max(2, normValues.length + 1)}`).format.borders = { style: "continuous", color: "#D9D9D9" };
blockers.getRange(`A1:E${blockerValues.length + 1}`).format.borders = { style: "continuous", color: "#D9D9D9" };
parity.getRange("A1:G8").format.borders = { style: "continuous", color: "#D9D9D9" };

await workbook.recalculate();
const check = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A", options: { useRegex: true, maxResults: 50 }, maxChars: 4000 });
if (check.ndjson && check.ndjson.includes('"kind":"match"')) {
  throw new Error(`Formula error found: ${check.ndjson}`);
}
await fs.mkdir(outputPath.substring(0, outputPath.lastIndexOf("/")), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, sheets: ks48 ? 6 : 5, rows: rowValues.length, norms: normValues.length, blockers: blockerValues.length }));
