"""Capture deterministic local UI acceptance evidence without paid API calls."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import fitz
import httpx
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
OUTPUT = ROOT / "artifacts" / "final_business_rules_local_acceptance"


def sample_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Construction Tender Phase 3-5 local UI acceptance")
    document.save(path)
    document.close()


def wait_for_server() -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get("http://127.0.0.1:8015/health", timeout=1).status_code == 200:
                return
        except Exception:
            time.sleep(.25)
    raise RuntimeError("Local acceptance server did not start")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tender-phase35-") as temporary:
        temp = Path(temporary)
        pdf = temp / "phase3-5-ui-fixture.pdf"
        sample_pdf(pdf)
        env = os.environ.copy()
        env.update({
            "MOCK_PARSER": "true",
            "MOCK_AI": "true",
            "DATABASE_URL": f"sqlite+aiosqlite:///{temp / 'acceptance.db'}",
            "DOCUMENT_STORAGE_DIR": str(temp / "documents"),
            "GOVERNANCE_RUNTIME_DIR": str(temp / "governance"),
            "CALCULATION_SNAPSHOT_DIR": str(temp / "snapshots"),
        })
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8015"],
            cwd=BACKEND,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_server()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
                page.goto("http://127.0.0.1:8015", wait_until="domcontentloaded")
                page.screenshot(path=OUTPUT / "01-projects-upload.png", full_page=True)
                page.set_input_files("#pdf-input", str(pdf))
                page.locator("#upload-btn").click()
                page.wait_for_function("() => getComputedStyle(document.getElementById('review-section')).display !== 'none'", timeout=45000)
                page.wait_for_function("() => (document.getElementById('summary-bar').textContent || '').includes('Pricing unavailable')")
                page.screenshot(path=OUTPUT / "02-review-correct.png", full_page=True)
                page.locator('[data-route="calculation"]').click()
                page.wait_for_function("() => (document.getElementById('snapshot-id').textContent || '').startsWith('calc-')")
                page.wait_for_function("() => (document.getElementById('tender-summary').textContent || '').includes('Unresolved descendants')")
                page.screenshot(path=OUTPUT / "03-calculation-export.png", full_page=True)
                with page.expect_download() as download_info:
                    page.locator("#internal-export").click()
                download_info.value.save_as(OUTPUT / "internal-draft-local-ui.xlsx")
                page.locator('[data-route="master"]').click()
                page.wait_for_function("() => document.querySelectorAll('#master-candidates tr').length === 46")
                page.wait_for_function("() => (document.getElementById('master-governed').textContent || '').includes('source-import')")
                page.screenshot(path=OUTPUT / "04-master-data.png", full_page=True)
                page.locator('[data-route="formula"]').click()
                page.wait_for_function("() => (document.getElementById('formula-versions').textContent || '').includes('calculation-v2.1')")
                page.locator("#formula-name").fill("Local preview only")
                page.locator("#formula-value").fill("0.08")
                page.locator("#formula-effective").fill("2026-10-01")
                page.locator("#formula-preview").click()
                page.wait_for_function("() => (document.getElementById('formula-preview-output').textContent || '').includes('Difference')")
                page.screenshot(path=OUTPUT / "05-formula-configuration.png", full_page=True)
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
