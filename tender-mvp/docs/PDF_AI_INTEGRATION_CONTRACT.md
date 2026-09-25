# Parsed BOQ to V2 Review Contract

Status: design guardrail only. This document defines interfaces for isolated PDF/AI integration preparation and does not change the existing MVP execution flow.

## Pipeline boundary

Parsed BOQ -> Semantic WorkItem mapping -> CalculationEngineV2 -> Review payload -> Excel exporter

## Stage contracts

### 1) Parsed BOQ input

Producer: parser pipeline

Shape:
- document_id: string
- source_file: string
- extracted_items: list[ParsedBoqRow]

ParsedBoqRow:
- row_id: string
- code_raw: string
- description_raw: string
- unit_raw: string
- quantity_raw: string
- section_hint: string | null
- evidence: list[CellOrSpanEvidence]

CellOrSpanEvidence:
- source_type: enum("xlsx_cell", "pdf_span")
- locator: string
- confidence: float

Required guardrails:
- preserve original text and units
- preserve traceable source evidence
- no cost calculation in parser stage

### 2) Semantic WorkItem mapping

Producer: semantic_mapper
Consumer: V2 runtime builder

Shape:
- work_item_code: string
- category: string
- unit: string
- quantity: string
- match_status: enum("matched", "ambiguous", "unmatched")
- match_confidence: float
- canonical_item_ref: string | null
- unresolved_reasons: list[string]
- provenance: list[ProvenanceEntry]

ProvenanceEntry:
- field: string
- source: string
- classification: enum("SOURCE_VERIFIED", "FORMULA_DERIVED", "EXTERNAL_UNRESOLVED", "ASSUMED")

Required guardrails:
- unmatched or ambiguous items must stay unresolved
- no silent fallback from ambiguous to matched
- every mapped field carries provenance

### 3) V2 calculation input/output

Producer input: runtime bundle for `calculate_work_item_from_runtime`, `calculate_tender_estimate`, `calculate_approval_estimate`

Required runtime fields per item:
- code
- category
- project_quantity
- work_item_norm
- tender_rounding_mode
- approval_rule_group (or explicit category rules)
- missing_dependencies

V2 output constraints:
- item-level result includes both `loaded_unit_price` (Chiết tính path) and `tender_rounded_unit_price` (Dự thầu path)
- project estimates expose:
  - partial subtotal
  - official total only when status is COMPLETE
  - blocked_items and blocked_item_details when INCOMPLETE

### 4) Review payload

Producer: V2 + provenance layer
Consumer: review UI/API

Shape:
- status: enum("COMPLETE", "INCOMPLETE")
- official_totals: { approval: decimal | null, tender: decimal | null }
- partial_subtotals: { approval: decimal, tender: decimal }
- blocked_items: list[string]
- blocked_item_details: list[BlockedItem]
- coverage: CoverageReport
- item_rows: list[ReviewItemRow]

BlockedItem:
- work_item_code: string
- category: string
- missing_dependencies: list[string]

ReviewItemRow:
- work_item_code: string
- quantity: decimal
- loaded_unit_price: decimal | null
- tender_rounded_unit_price: decimal | null
- tender_extension: decimal | null
- calculation_status: enum("resolved", "blocked")

Required guardrails:
- INCOMPLETE payload must not present official totals
- blocked details must be user-visible and machine-readable

### 5) Excel export payload

Producer: review stage
Consumer: excel exporter

Shape requirements:
- explicit status banner field
- tender/approval official totals nullable
- partial subtotals always present
- unresolved sheet rows from blocked item details

Required guardrails:
- no implicit conversion of partial subtotal to official total
- exported totals must match review payload contract exactly

## Compatibility note

Current MVP flow remains unchanged. This contract is additive and intended to isolate future PDF/AI integration behind stable interfaces.
