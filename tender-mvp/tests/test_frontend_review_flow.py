import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
import fitz
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def sample_pdf_bytes() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Construction Tender UI test source")
    payload = document.tobytes()
    document.close()
    return payload


def start_app(database_path: Path, document_storage: Path):
    env = os.environ.copy()
    env["MOCK_PARSER"] = "true"
    env["MOCK_AI"] = "true"
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path}"
    env["DOCUMENT_STORAGE_DIR"] = str(document_storage)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(BACKEND),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            resp = httpx.get("http://127.0.0.1:8000/api/parser/contract", timeout=1.5)
            if resp.status_code == 200:
                return proc
        except Exception:
            time.sleep(0.25)

    stdout, stderr = proc.communicate(timeout=5)
    raise RuntimeError(f"Backend failed to start. stdout={stdout} stderr={stderr}")


@pytest.fixture
def app_server(tmp_path):
    proc = start_app(tmp_path / "frontend-test.db", tmp_path / "documents")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def test_upload_processing_flow_renders_review_table(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        try:
            page.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
            page.set_input_files(
                "#pdf-input",
                [{
                    "name": "sample.pdf",
                    "mimeType": "application/pdf",
                    "buffer": sample_pdf_bytes(),
                }],
            )
            page.locator("#upload-btn").click()

            page.wait_for_function(
                "() => document.getElementById('review-section') && getComputedStyle(document.getElementById('review-section')).display !== 'none'",
                timeout=45000,
            )

            review_section = page.locator("#review-section")
            assert review_section.is_visible(), "review section must become visible after processing"

            rows = page.locator("#review-tbody tr")
            assert rows.count() > 0, "Expected review rows to render after upload"

            summary_kpis = page.locator("#summary-bar .kpi")
            assert summary_kpis.count() >= 4, "Summary KPIs should be visible in review section"
            assert page.locator("#dl-btn").is_visible(), "Excel export button should remain available"
            assert page.locator("#review-tbody", has_text="Not applicable").count() == 1

            document_response = page.request.get(
                f"http://127.0.0.1:8000/api/jobs/{page.url.rsplit('/', 1)[-1]}/document"
            )
            assert document_response.status == 200
            assert document_response.headers["content-type"].startswith("application/pdf")
            rendered_page = page.request.get(
                f"http://127.0.0.1:8000/api/jobs/{page.url.rsplit('/', 1)[-1]}/document/pages/1.png"
            )
            assert rendered_page.status == 200
            assert rendered_page.headers["content-type"].startswith("image/png")

            # Exact mapping regressions should be visible in the rendered table.
            assert "KS-002" in page.locator("#review-tbody tr", has_text="Đo vẽ bình đồ tỷ lệ 1/500 vùng đồi núi").first.text_content()
            assert "KS-003" in page.locator("#review-tbody tr", has_text="Đo vẽ bình đồ tỷ lệ 1/200 vùng đồng bằng").first.text_content()
            assert "KS-029" in page.locator("#review-tbody tr", has_text="Khoan thăm dò địa chất đường, lỗ khoan 0–30m, đất cấp III").first.text_content()
            assert "KS-008" in page.locator("#review-tbody tr", has_text="Lấy mẫu đất nguyên dạng (trong lỗ khoan đường)").first.text_content()
            assert "KS-014" in page.locator("#review-tbody tr", has_text="Thí nghiệm xuyên tiêu chuẩn SPT (trong lỗ khoan đường)").first.text_content()

            # A billable row without calculated amount must never display green OK.
            ok_without_amount = page.evaluate("""
                () => {
                    const trs = Array.from(document.querySelectorAll('#review-tbody tr'));
                    return trs
                        .map(tr => Array.from(tr.querySelectorAll('td')).map(td => (td.textContent || '').trim()))
                        .filter(cols => cols.length >= 10)
                        .filter(cols => (cols[5] === '—' || cols[6] === '—') && cols[9].includes('OK'))
                        .map(cols => cols[1]);
                }
            """)
            assert ok_without_amount == [], f"Rows with missing amount still marked OK: {ok_without_amount}"

            first_edit = page.locator(
                "#review-tbody tr", has_text="Đo vẽ bình đồ tỷ lệ 1/500 vùng đồi núi"
            ).first.locator(".btn-edit")
            assert first_edit.is_visible(), "At least one edit control should be present"
            first_edit.click()
            page.locator("#modal-master-sel").select_option(index=1)
            page.locator("#modal-price-input").fill("250000")
            page.locator("#modal-price-source").fill("UAT test approved price decision")
            page.locator("#modal-price-effective").fill("2026-09-28")
            page.locator("#modal-price-approver").fill("uat-reviewer")
            page.locator("#modal-overlay .modal-actions button:has-text('Lưu thay đổi')").click()

            page.wait_for_function(
                "() => !document.getElementById('modal-overlay').classList.contains('open')",
                timeout=20000,
            )
            assert review_section.is_visible(), "Review section should stay visible after override"
            assert page.locator("#review-tbody tr").count() > 0

            edited_row = page.locator(
                "#review-tbody tr", has_text="Đo vẽ bình đồ tỷ lệ 1/500 vùng đồi núi"
            ).first
            assert "edited" in edited_row.text_content()
            edited_row.locator(".btn-edit").click()
            page.locator("#edit-quantity").fill("2,5")
            page.locator("#modal-save").click()
            page.wait_for_function(
                "() => !document.getElementById('modal-overlay').classList.contains('open')",
                timeout=20000,
            )
            assert "2,5" in edited_row.text_content()

            # Calculate uses the corrected data and materialises one immutable snapshot.
            page.locator('[data-route="calculation"]').click()
            page.wait_for_function(
                "() => (document.getElementById('snapshot-id').textContent || '').startsWith('calc-')",
                timeout=20000,
            )
            assert page.locator("#calc-metrics .metric").count() == 6
            assert page.locator("#internal-export").is_enabled()
            assert "aggregate-first" in page.locator("#approval-summary").text_content().lower()
            assert page.locator("#calc-rows tr").count() > 0
            job_id = page.evaluate("currentJobId")
            snapshot_one = page.request.get(f"http://127.0.0.1:8000/api/calculation/{job_id}").json()
            snapshot_two = page.request.get(f"http://127.0.0.1:8000/api/calculation/{job_id}").json()
            assert snapshot_one["snapshot_id"] == snapshot_two["snapshot_id"]
            internal = page.request.get(
                f"http://127.0.0.1:8000/api/export/{job_id}/internal.xlsx?snapshot_id={snapshot_one['snapshot_id']}"
            )
            assert internal.status == 200
            assert internal.headers["x-calculation-snapshot"] == snapshot_one["snapshot_id"]
            final = page.request.get(
                f"http://127.0.0.1:8000/api/export/{job_id}/final.xlsx?snapshot_id={snapshot_one['snapshot_id']}"
            )
            assert final.status == 409

            # Administrative pages are reachable but not inserted into the upload workflow.
            page.locator('[data-route="master"]').click()
            page.wait_for_function(
                "() => document.querySelectorAll('#master-candidates tr').length === 46",
                timeout=20000,
            )
            assert page.locator("#master-conflicts .notice").count() == 3
            assert "not_applied" in page.locator("#master-notice").text_content().lower()

            # A master price edit must retain mapping identity, expose price-editor identity,
            # and require review without silently overwriting the mapped row price.
            before_rows = page.request.get(f"http://127.0.0.1:8000/api/review/{job_id}/rows").json()
            target = next(
                row for row in before_rows
                if row["row_type"] == "line_item" and row["master_item_id"]
                and row["price_source_reference"] and row["price_last_updated_by"] != "local-reviewer"
            )
            old_price = target["unit_price"]
            old_mapping_editor = target["mapping_last_updated_by"]
            update = page.request.patch(
                f"http://127.0.0.1:8000/api/admin/master-data/catalogue/{target['master_item_id']}",
                data={
                    "unit_price": str(int(float(old_price)) + 1),
                    "source_reference": "Signed local acceptance decision",
                    "effective_date": "2026-09-28",
                    "approval_status": "approved",
                    "approved_by": "price-approver",
                    "actor": "price-editor",
                },
            )
            assert update.status == 200
            after = next(
                row for row in page.request.get(f"http://127.0.0.1:8000/api/review/{job_id}/rows").json()
                if row["row_id"] == target["row_id"]
            )
            assert after["unit_price"] == old_price
            assert after["mapping_last_updated_by"] == old_mapping_editor
            assert after["price_last_updated_by"] == "price-editor"
            assert after["price_change_pending_review"] is True

            page.locator('[data-route="formula"]').click()
            page.wait_for_function(
                "() => (document.getElementById('formula-versions').textContent || '').includes('calculation-v2.1')",
                timeout=20000,
            )
            assert "aggregate-first" in page.locator("#formula-versions").text_content().lower()
            assert "approved" in page.locator("#formula-versions").text_content().lower()

            page.locator('[data-route="review"]').click()
            assert review_section.is_visible()
        finally:
            browser.close()


def test_review_fetch_error_shows_explicit_message(app_server):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        try:
            page.add_init_script("""
                const originalFetch = window.fetch.bind(window);
                window.fetch = (...args) => {
                    const url = String(args[0] || '');
                    if (url.includes('/api/review/')) {
                        return Promise.reject(new Error('review fetch failed'));
                    }
                    return originalFetch(...args);
                };
            """)
            page.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
            page.set_input_files(
                "#pdf-input",
                [{
                    "name": "sample.pdf",
                    "mimeType": "application/pdf",
                    "buffer": sample_pdf_bytes(),
                }],
            )
            page.locator("#upload-btn").click()

            page.wait_for_function(
                "() => { const el = document.getElementById('status-bar'); return el && /review|lỗi|error/i.test(el.textContent || ''); }",
                timeout=30000,
            )
            status = page.locator("#status-bar")
            assert "review" in status.text_content().lower() or "lỗi" in status.text_content().lower() or "error" in status.text_content().lower()
            assert "review fetch failed" in status.text_content().lower() or "review" in status.text_content().lower()
        finally:
            browser.close()
