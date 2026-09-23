# Construction Tender MVP

An isolated end-to-end pipeline for processing Vietnamese construction/survey BOQ PDFs, matching items to versioned pricing master data, calculating bid prices, and generating an editable Excel bid worksheet.

> **DEMO ONLY** — Not for production use without explicit authorization. All outputs labelled DRAFT until reviewed and approved.

---

## Quick Start

```bash
cd tender-mvp/backend
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.template .env            # edit .env, set MOCK_PARSER=true for demo
uvicorn main:app --reload --port 8000
# Open http://localhost:8000
```

---

## Architecture

```
tender-mvp/
  backend/
    main.py                     # FastAPI app, lifespan, CORS, routers
    database.py                 # SQLAlchemy 2.x models, AsyncSession
    requirements.txt
    pytest.ini
    routers/
      jobs.py                   # POST /api/jobs/upload, GET /api/jobs/{id}
      parser.py                 # GET /api/parser/contract
      review.py                 # GET /api/review/{job_id}/rows, POST override
      export.py                 # GET /api/export/{job_id}/xlsx
    parser_adapter/
      adapter.py                # ParserAdapter (real Azure or mock fixture)
      normalizer.py             # DocumentNormalizer → ParsedDocument + NormalizedRow
    boq/
      reconstructor.py          # BOQReconstructor → BOQLineItem list
    semantic_mapper/
      mapper.py                 # SemanticMapper (OpenAI JSON mode or mock)
    pricing_engine/
      engine.py                 # PricingEngine (Decimal arithmetic)
    master_data/
      loader.py                 # Seed loader (idempotent upsert at startup)
    excel_exporter/
      exporter.py               # ExcelExporter → .xlsx bytes
  frontend/
    index.html                  # Single-page review UI (vanilla JS)
  master-data/
    items_v1.json               # 30 versioned master pricing items
    unit_rules_v1.json          # Approved unit conversion rules
    coeff_v1.json               # Price coefficients (K_TT, K_XD, K_NVCP)
  fixtures/
    bang_tien_luong_mock.json   # Realistic 4-page BOQ fixture for offline dev
  tests/
    test_parser.py
    test_semantic_mapper.py
    test_pricing_engine.py
    test_excel_exporter.py
  .env.template
  README.md
  MASTER_DATA_GAP_REPORT.md
```

---

## Pipeline

```
PDF upload
   ↓ ParserAdapter (Azure Doc Intel or mock fixture)
   ↓ DocumentNormalizer → ParsedDocument (pages, tables, cells, page/region refs)
   ↓ BOQReconstructor → BOQLineItem list (headings, metadata, line_items)
   ↓ SemanticMapper → MappingOutput per line_item (OpenAI JSON mode or mock)
   ↓ PricingEngine → PriceResult per line_item (Decimal arithmetic)
   ↓ Job status: needs_review / ready
   ↓ User reviews via HTML table; records overrides
   ↓ ExcelExporter → .xlsx (Dự thầu + Mapping/Audit + Unresolved)
```

Job states: `uploaded → parsing → mapping → pricing → needs_review / ready → exported; failed`

---

## Environment Variables

See `.env.template` for all variables. Key ones:

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_PARSER` | `true` | Use fixture instead of real Azure API |
| `MOCK_AI` | `false` | Use deterministic first-candidate mapper instead of OpenAI |
| `AZURE_DOC_INTEL_ENDPOINT` | — | Azure Document Intelligence endpoint URL |
| `AZURE_DOC_INTEL_KEY` | — | Azure API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `DEMO_TENANT_ID` | `demo-tenant-001` | Fixed demo tenant |
| `MASTER_DATA_VERSION` | `v1` | Master data version to load |

---

## Parser Adapter Contract

See `GET /api/parser/contract` for the live contract documentation.

**Submit:** `POST {AZURE_DOC_INTEL_ENDPOINT}/formrecognizer/documentModels/prebuilt-layout:analyze?api-version=2024-02-29-preview`  
- Body: raw PDF bytes  
- Header: `Ocp-Apim-Subscription-Key: <key>`, `Content-Type: application/pdf`  
- Response: `202 Accepted`, header `Operation-Location: <poll_url>`

**Poll:** `GET <Operation-Location>` → `{"status": "succeeded", "analyzeResult": {...}}`

Set `MOCK_PARSER=true` to skip the real API and use the 4-page fixture.

---

## Non-Negotiable Rules

- **Road drilling 0–30m / 624m ≠ Bridge drilling 0–60m / 600m** — always distinct master IDs (KS-006 vs KS-007)
- **No silent unit conflation:** ha↔100ha, m↔100m, TN↔thí nghiệm all require an explicit unit rule
- **Vietnamese decimals:** `29,5`, `19,50`, `0,030`, `342,34` preserved and parsed correctly (comma = decimal separator)
- **IV.1 18.57 Km** and similar group metadata rows are never priced as billable line items
- **Repeated row numbers** are disambiguated by section_path
- **Zero ≠ default** for missing quantities; missing → `unresolved`
- **All output numbers** traceable to: PDF source + versioned master data + deterministic formula + explicit user override
- **Partial totals** are never shown as complete bid totals; DRAFT watermark applied

---

## Running Tests

```bash
cd tender-mvp/backend
pip install -r requirements.txt
pytest ../tests/ -v
```

Expected: ~40+ tests, all passing with `MOCK_PARSER=true` and `MOCK_AI=true` (default).

---

## Master Data Gap Report

See [`MASTER_DATA_GAP_REPORT.md`](MASTER_DATA_GAP_REPORT.md) for:
- Which XLS sheets were used
- Items seeded vs items that could not be established
- PDF items likely to remain unresolved
- Recommended next steps before a real bid

---

## Integrating the Real Azure Parser API

1. Set `MOCK_PARSER=false` in `.env`
2. Set `AZURE_DOC_INTEL_ENDPOINT` and `AZURE_DOC_INTEL_KEY`
3. Upload a real PDF — the adapter automatically submits and polls

No code changes required; the adapter switches mode based on `MOCK_PARSER`.

---

## Integrating Real OpenAI

1. Set `OPENAI_API_KEY` in `.env`
2. Set `MOCK_AI=false` (or remove it)
3. Optionally set `OPENAI_MODEL=gpt-4o`

The SemanticMapper will call the real API with a strict JSON schema prompt.

---

## Security Notes

- API credentials are **backend-only** — never exposed to the frontend
- All outputs are labelled DRAFT until a domain expert reviews and approves
- Do not deploy to production without explicit authorization
- The demo tenant is isolated; no production data is touched
