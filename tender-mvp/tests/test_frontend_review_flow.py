import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"


def start_app():
    env = os.environ.copy()
    env["MOCK_PARSER"] = "true"
    env["MOCK_AI"] = "true"
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
def app_server():
    proc = start_app()
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
                    "buffer": b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
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

            first_edit = page.locator(".btn-edit").first
            assert first_edit.is_visible(), "At least one edit control should be present"
            first_edit.click()
            page.locator("#modal-master-sel").select_option(index=1)
            page.locator("#modal-price-input").fill("250000")
            page.locator("#modal-overlay .modal-actions button:has-text('Lưu thay đổi')").click()

            page.wait_for_function(
                "() => !document.getElementById('modal-overlay').classList.contains('open')",
                timeout=20000,
            )
            assert review_section.is_visible(), "Review section should stay visible after override"
            assert page.locator("#review-tbody tr").count() > 0
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
                    "buffer": b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF",
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
