import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import fitz
import httpx
import pytest
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def sample_pdf_bytes() -> bytes:
    document = fitz.open()
    for page_number in range(1, 5):
        page = document.new_page(width=794, height=1123)
        page.insert_text((72, 72), f"Construction Tender UI test source - page {page_number}")
    payload = document.tobytes()
    document.close()
    return payload


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_app(database_path: Path, document_storage: Path):
    port = unused_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["MOCK_PARSER"] = "true"
    env["MOCK_AI"] = "true"
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database_path}"
    env["DOCUMENT_STORAGE_DIR"] = str(document_storage)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/api/parser/contract", timeout=1.5).status_code == 200:
                return proc, base_url
        except Exception:
            time.sleep(0.25)
    stdout, stderr = proc.communicate(timeout=5)
    raise RuntimeError(f"Backend failed to start. stdout={stdout} stderr={stderr}")


@pytest.fixture
def app_server(tmp_path):
    proc, base_url = start_app(tmp_path / "frontend-test.db", tmp_path / "documents")
    yield {"proc": proc, "base_url": base_url}
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def upload_and_wait(page, base_url: str) -> str:
    page.goto(base_url, wait_until="domcontentloaded")
    page.set_input_files("#pdf-input", [{
        "name": "sample.pdf", "mimeType": "application/pdf", "buffer": sample_pdf_bytes(),
    }])
    page.locator("#upload-btn").click()
    page.wait_for_function(
        "() => document.getElementById('page-review').classList.contains('active')",
        timeout=45000,
    )
    page.wait_for_function("() => currentRows.length > 0 && selectedReviewRowId !== null", timeout=20000)
    return page.evaluate("currentJobId")


def test_reconciliation_selection_is_deterministic_and_compact(app_server):
    base_url = app_server["base_url"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            upload_and_wait(page, base_url)
            assert page.locator(".step[data-route]").count() == 3
            assert page.locator("#review-tbody tr").count() > 1

            target = page.locator("#review-tbody tr").filter(has_text="Đo vẽ bình đồ tỷ lệ 1/500 vùng đồi núi").first
            target_id = target.get_attribute("data-row")
            target.click()
            assert page.evaluate("selectedReviewRowId") == target_id
            assert page.locator("#highlight-box").evaluate("el => getComputedStyle(el).display") == "block"

            page.evaluate("renderReview()")
            assert page.evaluate("selectedReviewRowId") == target_id
            assert page.locator(f'#review-tbody tr[data-row="{target_id}"]').get_attribute("class").find("selected") >= 0

            selected_before_page_change = page.evaluate("selectedReviewRowId")
            page.locator("#pdf-next").click()
            assert page.evaluate("selectedReviewRowId") == selected_before_page_change
            page.locator("#pdf-prev").click()
            assert page.evaluate("selectedReviewRowId") == selected_before_page_change

            page.locator("#review-filter").select_option("attention")
            expected = page.evaluate("deterministicFallback(visibleReviewRows)?.row_id || null")
            assert page.evaluate("selectedReviewRowId") == expected
            page.locator("#review-search").fill("không có dòng nào phù hợp 123")
            assert page.evaluate("selectedReviewRowId") is None
            assert page.locator("#highlight-box").evaluate("el => getComputedStyle(el).display") == "none"
            page.locator("#review-search").fill("")
            assert page.evaluate("selectedReviewRowId") == page.evaluate("deterministicFallback(visibleReviewRows)?.row_id || null")

            scroll_metrics = page.locator("#review-scroll").evaluate("el => ({scrollWidth: el.scrollWidth, clientWidth: el.clientWidth})")
            assert scroll_metrics["scrollWidth"] <= scroll_metrics["clientWidth"] + 1
            assert page.locator(".two-line").first.evaluate("el => getComputedStyle(el).webkitLineClamp") == "2"

            page.locator("[data-evidence]").first.click()
            assert page.locator("#evidence-modal").get_attribute("class").find("open") >= 0
            evidence = page.locator("#evidence-body").text_content()
            for label in ["Công việc danh mục", "Mức phù hợp", "Ngày hiệu lực", "Provenance", "Nguồn đơn giá", "Phiên bản / audit"]:
                assert label in evidence
            page.locator('[data-close="evidence-modal"]').click()

            job_id = page.evaluate("currentJobId")
            created = page.request.post(f"{base_url}/api/review/{job_id}/rows", data={
                "description_vi": "Dòng không có vùng nguồn", "unit": "m", "quantity_raw": "1",
                "section_path": "Kiểm tra provenance", "row_type": "line_item", "user": "uat",
            })
            assert created.status == 201
            page.evaluate("loadReview()")
            page.wait_for_function("() => currentRows.some(row => row.description_vi === 'Dòng không có vùng nguồn')")
            page.locator("#review-filter").select_option("all")
            page.locator("#review-search").fill("Dòng không có vùng nguồn")
            missing_source_row = page.locator("#review-tbody tr").first
            missing_source_row.click()
            assert "Không xác định vị trí nguồn" in page.locator("#source-locator").text_content()
            assert page.locator("#highlight-box").evaluate("el => getComputedStyle(el).display") == "none"
        finally:
            browser.close()


def test_hierarchical_estimate_editing_audit_and_exports(app_server):
    base_url = app_server["base_url"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.on("dialog", lambda dialog: dialog.accept())
        try:
            job_id = upload_and_wait(page, base_url)
            source_row = page.locator("#review-tbody tr").filter(has_text="Đo vẽ bình đồ tỷ lệ 1/500 vùng đồi núi").first
            source_id = source_row.get_attribute("data-row")
            provenance_before = page.evaluate("id => currentRows.find(row => row.row_id === id).source_provenance", source_id)

            source_row.locator(".btn-edit").click()
            page.locator("#modal-master-sel").select_option(index=1)
            page.locator("#modal-price-input").fill("250000")
            page.locator("#modal-price-source").fill("Biên bản duyệt đơn giá UAT")
            page.locator("#modal-price-effective").fill("2026-09-28")
            page.locator("#modal-price-approver").fill("uat-reviewer")
            page.locator("#modal-save").click()
            page.wait_for_function("() => !document.getElementById('modal-overlay').classList.contains('open')", timeout=20000)
            provenance_after = page.evaluate("id => currentRows.find(row => row.row_id === id).source_provenance", source_id)
            assert provenance_after == provenance_before

            forbidden = page.request.post(f"{base_url}/api/review/{job_id}/override", data={
                "row_id": source_id, "field": "source_provenance", "old_value": None,
                "new_value": "tamper", "user": "uat",
            })
            assert forbidden.status == 400

            page.locator('[data-route="estimate"]').click()
            page.wait_for_function("() => currentSnapshot !== null", timeout=20000)
            assert page.locator(".group-row").count() >= 2
            assert page.locator(".group-row.level-1").count() >= 1
            group_texts = page.locator(".group-row").all_text_contents()
            assert any("CÔNG TÁC TRẮC ĐỊA" in text for text in group_texts)
            assert any("Đo vẽ bình đồ tỷ lệ 1/500" in text for text in group_texts)
            assert page.locator(".estimate-detail").count() > 0
            assert page.locator(".subtotal-row").count() >= 1
            assert page.locator(".grand-row").count() == 1
            assert page.locator("#draft-warn").is_visible()
            assert "Chưa có đơn giá" in page.locator("#estimate-rows").text_content()

            first_group = page.locator("[data-toggle-group]").first
            group_key = first_group.get_attribute("data-toggle-group")
            subtotal_before = page.locator(f'[data-subtotal-group="{group_key}"]').text_content()
            detail_count_before = page.locator(".estimate-detail").count()
            first_group.click()
            assert page.locator(".estimate-detail").count() < detail_count_before
            subtotal_after = page.locator(f'[data-subtotal-group="{group_key}"]').text_content()
            assert subtotal_after == subtotal_before
            page.locator(f'[data-toggle-group="{group_key}"]').click()
            assert page.locator(".estimate-detail").count() == detail_count_before

            page.locator("#add-section").click()
            page.locator("#row-description").fill("VI Hạng mục bổ sung UAT")
            page.locator("#row-section").fill("VI")
            page.locator("#row-save").click()
            page.wait_for_function("() => (document.getElementById('estimate-rows').textContent || '').includes('Hạng mục bổ sung UAT')", timeout=20000)

            page.locator("#add-row").click()
            page.locator("#row-description").fill("Công việc khảo sát bổ sung")
            page.locator("#row-unit").fill("m")
            page.locator("#row-quantity").fill("2,5")
            page.locator("#row-section").fill("VI")
            page.locator("#row-save").click()
            page.wait_for_function("() => (document.getElementById('estimate-rows').textContent || '').includes('Công việc khảo sát bổ sung')", timeout=20000)
            manual_row = page.locator(".estimate-detail").filter(has_text="Công việc khảo sát bổ sung").first
            manual_id = manual_row.get_attribute("data-estimate-row")
            manual_row.locator('[data-estimate-edit]').click()
            page.locator("#edit-quantity").fill("3,5")
            page.locator("#modal-save").click()
            page.wait_for_function("() => !document.getElementById('modal-overlay').classList.contains('open')", timeout=20000)
            page.wait_for_function("id => currentRows.find(row => row.row_id === id)?.quantity_raw === '3,5'", arg=manual_id)
            audit_rows = page.request.get(f"{base_url}/api/review/{job_id}/rows").json()
            manual_api_row = next(row for row in audit_rows if row["row_id"] == manual_id)
            assert {event["field"] for event in manual_api_row["overrides"]} >= {"row_added", "quantity_raw"}

            page.locator(f'[data-estimate-row="{manual_id}"] [data-exclude-row]').click()
            page.wait_for_function("id => currentSnapshot && !currentSnapshot.rows.some(row => row.row_id === id && row.row_type === 'line_item')", arg=manual_id)
            audit_rows = page.request.get(f"{base_url}/api/review/{job_id}/rows").json()
            excluded = next(row for row in audit_rows if row["row_id"] == manual_id)
            assert excluded["source_origin"] == "manual_entry"
            assert any(event["field"] == "row_type" and event["new_value"] == "metadata" for event in excluded["overrides"])

            snapshot_id = page.evaluate("currentSnapshot.snapshot_id")
            approval_partial = page.evaluate("currentSnapshot.approval.partial_subtotal")
            assert page.evaluate("currentSnapshot.approval.hierarchy.branch") == "approval"
            page.locator('[data-estimate-tab="tender"]').click()
            assert page.locator("#estimate-title").text_content() == "Dự thầu"
            tender_partial = page.evaluate("currentSnapshot.tender.partial_subtotal")
            assert page.evaluate("estimateTab") == "tender"
            assert page.evaluate("currentSnapshot.tender.hierarchy.branch") == "tender"
            assert approval_partial is None or isinstance(approval_partial, (int, float, str))
            assert tender_partial is None or isinstance(tender_partial, (int, float, str))
            page.locator('[data-estimate-tab="approval"]').click()
            assert page.locator("#estimate-title").text_content() == "Phê duyệt nội bộ"

            for view, expected_sheet in [("approval", "Phê duyệt nội bộ"), ("tender", "Dự thầu")]:
                response = page.request.get(f"{base_url}/api/export/{job_id}/estimate.xlsx?view={view}&snapshot_id={snapshot_id}")
                assert response.status == 200
                assert response.headers["x-export-status"] == "draft-incomplete"
                workbook = load_workbook(io.BytesIO(response.body()), data_only=False)
                assert workbook.sheetnames == [expected_sheet]
                assert "DRAFT / INCOMPLETE" in str(workbook[expected_sheet]["A3"].value)
                values = [cell.value for cells in workbook[expected_sheet].iter_rows() for cell in cells]
                assert "Chưa có đơn giá / Not available" in values
        finally:
            browser.close()


def test_catalogue_crud_and_review_fetch_error(app_server):
    base_url = app_server["base_url"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            page.goto(base_url, wait_until="domcontentloaded")
            created = page.request.post(f"{base_url}/api/admin/master-data/catalogue", data={
                "code":"UX.TEST.001","name_vi":"Công việc thử danh mục","name_en":"Catalogue UX test",
                "long_description":"Mô tả dài dùng làm bằng chứng đối chiếu","aliases":["từ khóa thử","bí danh"],
                "category":"Khảo sát","unit":"m","unit_price":None,"status":"active","actor":"uat",
            })
            assert created.status == 201
            item_id = created.json()["item_id"]
            updated = page.request.patch(f"{base_url}/api/admin/master-data/catalogue/{item_id}", data={
                "name_vi":"Công việc thử danh mục đã sửa","long_description":"Mô tả chi tiết đã cập nhật để AI đối chiếu",
                "aliases":["từ khóa thử","bí danh mới"],"category":"Trắc địa","unit":"m","actor":"uat",
            })
            assert updated.status == 200
            retired = page.request.delete(f"{base_url}/api/admin/master-data/catalogue/{item_id}?actor=uat")
            assert retired.status == 200 and retired.json()["physically_deleted"] is False
            page.locator("#catalogue-open").click()
            page.wait_for_function("() => catalogue.some(item => item.code === 'UX.TEST.001')", timeout=20000)
            page.locator("#catalogue-status").select_option("all")
            page.locator("#catalogue-search").fill("UX.TEST.001")
            assert "Ngừng sử dụng" in page.locator("#catalogue-body").text_content()
            assert "đã sửa" in page.locator("#catalogue-body").text_content()

            page.add_init_script("""
                const originalFetch = window.fetch.bind(window);
                window.fetch = (...args) => String(args[0] || '').includes('/api/review/')
                    ? Promise.reject(new Error('review fetch failed')) : originalFetch(...args);
            """)
            page.goto(base_url, wait_until="domcontentloaded")
            page.set_input_files("#pdf-input", [{
                "name": "sample.pdf", "mimeType": "application/pdf", "buffer": sample_pdf_bytes(),
            }])
            page.locator("#upload-btn").click()
            page.wait_for_function(
                "() => /lỗi|error/i.test(document.getElementById('status-bar').textContent || '')",
                timeout=30000,
            )
            assert "review fetch failed" in page.locator("#status-bar").text_content().lower()
        finally:
            browser.close()
