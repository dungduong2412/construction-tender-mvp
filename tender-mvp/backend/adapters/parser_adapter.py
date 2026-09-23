"""
Parser Adapter Contract
=======================
Interface between the Construction Tender MVP and Azure Document Intelligence.

External API (being prepared independently):
  POST  {PARSER_API_URL}/jobs
        Body: multipart/form-data  file=<pdf bytes>
        Returns: {"job_id": "<uuid>", "status": "queued"}

  GET   {PARSER_API_URL}/jobs/{job_id}
        Returns: {"status": "completed|processing|failed",
                  "result": <AnalyzeResult JSON>}  # Azure DI schema

Configuration (environment variables, never hard-coded):
  PARSER_API_URL       Base URL of the Azure DI wrapper service
  PARSER_API_KEY       ****** API key for that service
  PARSER_USE_MOCK      "true" to use built-in fixture; "false" for live API

The adapter converts between our canonical ParsedDocument and the external
API payload. All external API logic lives HERE, not in business logic layers.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

import httpx

from ..models.domain import (
    BoundingRegion,
    CellContent,
    ParsedDocument,
    ParsedPage,
    ParsedTable,
    RawParserOutput,
)

# ---------------------------------------------------------------------------
# Mock fixture – represents four pages of the ĐT.827E survey BOQ
# This fixture lets the full workflow run before the real API is available.
# ---------------------------------------------------------------------------

MOCK_FIXTURE: dict = {
    "api_version": "2023-07-31",
    "model_id": "prebuilt-layout",
    "pages": [
        # ---- PAGE 1 ----
        {
            "page_number": 1,
            "text": (
                "BẢNG DỰ TOÁN CHI PHÍ KHẢO SÁT XÂY DỰNG\n"
                "Công trình: Đường tỉnh 827E\n"
                "I. KHẢO SÁT ĐỊA HÌNH\n"
                "TT  Nội dung công việc  Đơn vị  Khối lượng  Đơn giá  Thành tiền\n"
                "1  Đo đạc bình đồ tỷ lệ 1/500 khu vực cầu, địa hình đồng bằng  ha  2,50\n"
                "2  Đo đạc mặt cắt dọc tuyến  km  18,57\n"
                "3  Đo đạc mặt cắt ngang tuyến đường, địa hình đồng bằng  km  18,57\n"
                "II. KHẢO SÁT ĐỊA CHẤT ĐƯỜNG\n"
                "1  Khoan địa chất công trình đường, đất cấp I-II, độ sâu 0-30m  m  624\n"
                "2  Lấy mẫu đất nguyên dạng  mẫu  42\n"
                "3  Thí nghiệm SPT trong hố khoan  lần  36\n"
            ),
            "tables": [
                {
                    "table_index": 0,
                    "page_number": 1,
                    "row_count": 10,
                    "col_count": 6,
                    "cells": [
                        # Header row
                        {"row_index": 0, "col_index": 0, "text": "TT", "confidence": 0.98},
                        {"row_index": 0, "col_index": 1, "text": "Nội dung công việc", "confidence": 0.98},
                        {"row_index": 0, "col_index": 2, "text": "Đơn vị", "confidence": 0.97},
                        {"row_index": 0, "col_index": 3, "text": "Khối lượng", "confidence": 0.97},
                        {"row_index": 0, "col_index": 4, "text": "Đơn giá", "confidence": 0.96},
                        {"row_index": 0, "col_index": 5, "text": "Thành tiền", "confidence": 0.96},
                        # Section I
                        {"row_index": 1, "col_index": 0, "text": "I", "confidence": 0.99},
                        {"row_index": 1, "col_index": 1, "text": "KHẢO SÁT ĐỊA HÌNH", "confidence": 0.99},
                        {"row_index": 1, "col_index": 2, "text": "", "confidence": 0.95},
                        {"row_index": 1, "col_index": 3, "text": "", "confidence": 0.95},
                        {"row_index": 1, "col_index": 4, "text": "", "confidence": 0.95},
                        {"row_index": 1, "col_index": 5, "text": "", "confidence": 0.95},
                        # Item I.1
                        {"row_index": 2, "col_index": 0, "text": "1", "confidence": 0.98},
                        {"row_index": 2, "col_index": 1, "text": "Đo đạc bình đồ tỷ lệ 1/500 khu vực cầu, địa hình đồng bằng", "confidence": 0.92},
                        {"row_index": 2, "col_index": 2, "text": "ha", "confidence": 0.97},
                        {"row_index": 2, "col_index": 3, "text": "2,50", "confidence": 0.95},
                        {"row_index": 2, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 2, "col_index": 5, "text": "", "confidence": 0.90},
                        # Item I.2
                        {"row_index": 3, "col_index": 0, "text": "2", "confidence": 0.98},
                        {"row_index": 3, "col_index": 1, "text": "Đo đạc mặt cắt dọc tuyến", "confidence": 0.94},
                        {"row_index": 3, "col_index": 2, "text": "km", "confidence": 0.97},
                        {"row_index": 3, "col_index": 3, "text": "18,57", "confidence": 0.95},
                        {"row_index": 3, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 3, "col_index": 5, "text": "", "confidence": 0.90},
                        # Item I.3
                        {"row_index": 4, "col_index": 0, "text": "3", "confidence": 0.98},
                        {"row_index": 4, "col_index": 1, "text": "Đo đạc mặt cắt ngang tuyến đường, địa hình đồng bằng", "confidence": 0.93},
                        {"row_index": 4, "col_index": 2, "text": "km", "confidence": 0.97},
                        {"row_index": 4, "col_index": 3, "text": "18,57", "confidence": 0.95},
                        {"row_index": 4, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 4, "col_index": 5, "text": "", "confidence": 0.90},
                        # Section II
                        {"row_index": 5, "col_index": 0, "text": "II", "confidence": 0.99},
                        {"row_index": 5, "col_index": 1, "text": "KHẢO SÁT ĐỊA CHẤT ĐƯỜNG", "confidence": 0.98},
                        {"row_index": 5, "col_index": 2, "text": "", "confidence": 0.95},
                        {"row_index": 5, "col_index": 3, "text": "", "confidence": 0.95},
                        {"row_index": 5, "col_index": 4, "text": "", "confidence": 0.95},
                        {"row_index": 5, "col_index": 5, "text": "", "confidence": 0.95},
                        # Item II.1 – road drilling 0-30m (NOT bridge)
                        {"row_index": 6, "col_index": 0, "text": "1", "confidence": 0.98},
                        {"row_index": 6, "col_index": 1, "text": "Khoan địa chất công trình đường, đất cấp I-II, độ sâu 0-30m", "confidence": 0.94},
                        {"row_index": 6, "col_index": 2, "text": "m", "confidence": 0.97},
                        {"row_index": 6, "col_index": 3, "text": "624", "confidence": 0.96},
                        {"row_index": 6, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 6, "col_index": 5, "text": "", "confidence": 0.90},
                        # Item II.2
                        {"row_index": 7, "col_index": 0, "text": "2", "confidence": 0.98},
                        {"row_index": 7, "col_index": 1, "text": "Lấy mẫu đất nguyên dạng", "confidence": 0.96},
                        {"row_index": 7, "col_index": 2, "text": "mẫu", "confidence": 0.97},
                        {"row_index": 7, "col_index": 3, "text": "42", "confidence": 0.97},
                        {"row_index": 7, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 7, "col_index": 5, "text": "", "confidence": 0.90},
                        # Item II.3
                        {"row_index": 8, "col_index": 0, "text": "3", "confidence": 0.98},
                        {"row_index": 8, "col_index": 1, "text": "Thí nghiệm SPT trong hố khoan", "confidence": 0.95},
                        {"row_index": 8, "col_index": 2, "text": "lần", "confidence": 0.97},
                        {"row_index": 8, "col_index": 3, "text": "36", "confidence": 0.97},
                        {"row_index": 8, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 8, "col_index": 5, "text": "", "confidence": 0.90},
                    ],
                }
            ],
        },
        # ---- PAGE 2 ----
        {
            "page_number": 2,
            "text": (
                "(Tiếp theo trang 1)\n"
                "II. KHẢO SÁT ĐỊA CHẤT ĐƯỜNG (tiếp)\n"
                "4  Thí nghiệm đất trong phòng – chỉ tiêu cơ lý cơ bản  mẫu  42\n"
                "III. KHẢO SÁT ĐỊA CHẤT CẦU\n"
                "IV.1  18,57 Km tuyến đường 827E\n"
                "1  Khoan địa chất công trình cầu, đất cấp I-II, độ sâu 0-60m, trên cạn  m  600\n"
                "2  Lấy mẫu đất nguyên dạng  mẫu  30\n"
                "3  Thí nghiệm đất trong phòng – chỉ tiêu cơ lý cơ bản  mẫu  30\n"
                "4  Thí nghiệm SPT trong hố khoan  lần  24\n"
                "5  Khảo sát thủy văn công trình cầu  công trình  3\n"
            ),
            "tables": [
                {
                    "table_index": 0,
                    "page_number": 2,
                    "row_count": 9,
                    "col_count": 6,
                    "cells": [
                        # Section heading continuation
                        {"row_index": 0, "col_index": 0, "text": "II", "confidence": 0.98},
                        {"row_index": 0, "col_index": 1, "text": "KHẢO SÁT ĐỊA CHẤT ĐƯỜNG (tiếp)", "confidence": 0.92},
                        {"row_index": 0, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 0, "col_index": 3, "text": "", "confidence": 0.90},
                        {"row_index": 0, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 0, "col_index": 5, "text": "", "confidence": 0.90},
                        # Item II.4 – continues from page 1
                        {"row_index": 1, "col_index": 0, "text": "4", "confidence": 0.98},
                        {"row_index": 1, "col_index": 1, "text": "Thí nghiệm đất trong phòng – chỉ tiêu cơ lý cơ bản", "confidence": 0.94},
                        {"row_index": 1, "col_index": 2, "text": "mẫu", "confidence": 0.97},
                        {"row_index": 1, "col_index": 3, "text": "42", "confidence": 0.97},
                        {"row_index": 1, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 1, "col_index": 5, "text": "", "confidence": 0.90},
                        # Section III heading
                        {"row_index": 2, "col_index": 0, "text": "III", "confidence": 0.99},
                        {"row_index": 2, "col_index": 1, "text": "KHẢO SÁT ĐỊA CHẤT CẦU", "confidence": 0.98},
                        {"row_index": 2, "col_index": 2, "text": "", "confidence": 0.95},
                        {"row_index": 2, "col_index": 3, "text": "", "confidence": 0.95},
                        {"row_index": 2, "col_index": 4, "text": "", "confidence": 0.95},
                        {"row_index": 2, "col_index": 5, "text": "", "confidence": 0.95},
                        # IV.1 group metadata – NOT a billable line item
                        {"row_index": 3, "col_index": 0, "text": "IV.1", "confidence": 0.96},
                        {"row_index": 3, "col_index": 1, "text": "18,57 Km tuyến đường 827E", "confidence": 0.91},
                        {"row_index": 3, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 3, "col_index": 3, "text": "", "confidence": 0.90},
                        {"row_index": 3, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 3, "col_index": 5, "text": "", "confidence": 0.90},
                        # Bridge drilling (row number "1" – same number as road section II row 1 → different context)
                        {"row_index": 4, "col_index": 0, "text": "1", "confidence": 0.98},
                        {"row_index": 4, "col_index": 1, "text": "Khoan địa chất công trình cầu, đất cấp I-II, độ sâu 0-60m, trên cạn", "confidence": 0.93},
                        {"row_index": 4, "col_index": 2, "text": "m", "confidence": 0.97},
                        {"row_index": 4, "col_index": 3, "text": "600", "confidence": 0.96},
                        {"row_index": 4, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 4, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 5, "col_index": 0, "text": "2", "confidence": 0.98},
                        {"row_index": 5, "col_index": 1, "text": "Lấy mẫu đất nguyên dạng", "confidence": 0.96},
                        {"row_index": 5, "col_index": 2, "text": "mẫu", "confidence": 0.97},
                        {"row_index": 5, "col_index": 3, "text": "30", "confidence": 0.97},
                        {"row_index": 5, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 5, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 6, "col_index": 0, "text": "3", "confidence": 0.98},
                        {"row_index": 6, "col_index": 1, "text": "Thí nghiệm đất trong phòng – chỉ tiêu cơ lý cơ bản", "confidence": 0.94},
                        {"row_index": 6, "col_index": 2, "text": "mẫu", "confidence": 0.97},
                        {"row_index": 6, "col_index": 3, "text": "30", "confidence": 0.97},
                        {"row_index": 6, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 6, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 7, "col_index": 0, "text": "4", "confidence": 0.98},
                        {"row_index": 7, "col_index": 1, "text": "Thí nghiệm SPT trong hố khoan", "confidence": 0.95},
                        {"row_index": 7, "col_index": 2, "text": "lần", "confidence": 0.97},
                        {"row_index": 7, "col_index": 3, "text": "24", "confidence": 0.97},
                        {"row_index": 7, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 7, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 8, "col_index": 0, "text": "5", "confidence": 0.98},
                        {"row_index": 8, "col_index": 1, "text": "Khảo sát thủy văn công trình cầu", "confidence": 0.95},
                        {"row_index": 8, "col_index": 2, "text": "công trình", "confidence": 0.95},
                        {"row_index": 8, "col_index": 3, "text": "3", "confidence": 0.97},
                        {"row_index": 8, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 8, "col_index": 5, "text": "", "confidence": 0.90},
                    ],
                }
            ],
        },
        # ---- PAGE 3 ----
        {
            "page_number": 3,
            "text": (
                "(Tiếp theo trang 2)\n"
                "IV. CÔNG TÁC THÍ NGHIỆM\n"
                "1  Thí nghiệm SPT trong hố khoan cầu  lần  24\n"
                "2  Thí nghiệm đá trong phòng – chỉ tiêu cơ lý cơ bản  mẫu  18\n"
                "3  Thí nghiệm xuyên tĩnh CPT  m  29,5\n"
                "V. LẬP BÁO CÁO\n"
                "1  Lập báo cáo khảo sát địa chất  báo cáo  1\n"
                "2  Lập báo cáo khảo sát địa hình  báo cáo  1\n"
            ),
            "tables": [
                {
                    "table_index": 0,
                    "page_number": 3,
                    "row_count": 8,
                    "col_count": 6,
                    "cells": [
                        {"row_index": 0, "col_index": 0, "text": "IV", "confidence": 0.99},
                        {"row_index": 0, "col_index": 1, "text": "CÔNG TÁC THÍ NGHIỆM", "confidence": 0.98},
                        {"row_index": 0, "col_index": 2, "text": "", "confidence": 0.95},
                        {"row_index": 0, "col_index": 3, "text": "", "confidence": 0.95},
                        {"row_index": 0, "col_index": 4, "text": "", "confidence": 0.95},
                        {"row_index": 0, "col_index": 5, "text": "", "confidence": 0.95},
                        {"row_index": 1, "col_index": 0, "text": "1", "confidence": 0.98},
                        {"row_index": 1, "col_index": 1, "text": "Thí nghiệm SPT trong hố khoan cầu", "confidence": 0.94},
                        {"row_index": 1, "col_index": 2, "text": "lần", "confidence": 0.97},
                        {"row_index": 1, "col_index": 3, "text": "24", "confidence": 0.97},
                        {"row_index": 1, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 1, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 2, "col_index": 0, "text": "2", "confidence": 0.98},
                        {"row_index": 2, "col_index": 1, "text": "Thí nghiệm đá trong phòng – chỉ tiêu cơ lý cơ bản", "confidence": 0.94},
                        {"row_index": 2, "col_index": 2, "text": "mẫu", "confidence": 0.97},
                        {"row_index": 2, "col_index": 3, "text": "18", "confidence": 0.97},
                        {"row_index": 2, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 2, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 3, "col_index": 0, "text": "3", "confidence": 0.98},
                        {"row_index": 3, "col_index": 1, "text": "Thí nghiệm xuyên tĩnh CPT", "confidence": 0.95},
                        {"row_index": 3, "col_index": 2, "text": "m", "confidence": 0.97},
                        {"row_index": 3, "col_index": 3, "text": "29,5", "confidence": 0.94},
                        {"row_index": 3, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 3, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 4, "col_index": 0, "text": "V", "confidence": 0.99},
                        {"row_index": 4, "col_index": 1, "text": "LẬP BÁO CÁO", "confidence": 0.98},
                        {"row_index": 4, "col_index": 2, "text": "", "confidence": 0.95},
                        {"row_index": 4, "col_index": 3, "text": "", "confidence": 0.95},
                        {"row_index": 4, "col_index": 4, "text": "", "confidence": 0.95},
                        {"row_index": 4, "col_index": 5, "text": "", "confidence": 0.95},
                        {"row_index": 5, "col_index": 0, "text": "1", "confidence": 0.98},
                        {"row_index": 5, "col_index": 1, "text": "Lập báo cáo khảo sát địa chất", "confidence": 0.96},
                        {"row_index": 5, "col_index": 2, "text": "báo cáo", "confidence": 0.96},
                        {"row_index": 5, "col_index": 3, "text": "1", "confidence": 0.97},
                        {"row_index": 5, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 5, "col_index": 5, "text": "", "confidence": 0.90},
                        {"row_index": 6, "col_index": 0, "text": "2", "confidence": 0.98},
                        {"row_index": 6, "col_index": 1, "text": "Lập báo cáo khảo sát địa hình", "confidence": 0.96},
                        {"row_index": 6, "col_index": 2, "text": "báo cáo", "confidence": 0.96},
                        {"row_index": 6, "col_index": 3, "text": "1", "confidence": 0.97},
                        {"row_index": 6, "col_index": 4, "text": "", "confidence": 0.90},
                        {"row_index": 6, "col_index": 5, "text": "", "confidence": 0.90},
                    ],
                }
            ],
        },
        # ---- PAGE 4 ----
        {
            "page_number": 4,
            "text": (
                "TỔNG HỢP DỰ TOÁN\n"
                "I. Khảo sát địa hình\n"
                "II. Khảo sát địa chất đường\n"
                "III. Khảo sát địa chất cầu\n"
                "IV. Công tác thí nghiệm\n"
                "V. Lập báo cáo\n"
                "Cộng chi phí trực tiếp\n"
                "Chi phí chung\n"
                "Thu nhập chịu thuế tính trước\n"
                "Thuế VAT 10%\n"
                "TỔNG CỘNG\n"
            ),
            "tables": [
                {
                    "table_index": 0,
                    "page_number": 4,
                    "row_count": 11,
                    "col_count": 3,
                    "cells": [
                        {"row_index": 0, "col_index": 0, "text": "STT", "confidence": 0.98},
                        {"row_index": 0, "col_index": 1, "text": "Khoản mục", "confidence": 0.98},
                        {"row_index": 0, "col_index": 2, "text": "Giá trị (đồng)", "confidence": 0.97},
                        {"row_index": 1, "col_index": 0, "text": "I", "confidence": 0.99},
                        {"row_index": 1, "col_index": 1, "text": "Khảo sát địa hình", "confidence": 0.98},
                        {"row_index": 1, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 2, "col_index": 0, "text": "II", "confidence": 0.99},
                        {"row_index": 2, "col_index": 1, "text": "Khảo sát địa chất đường", "confidence": 0.98},
                        {"row_index": 2, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 3, "col_index": 0, "text": "III", "confidence": 0.99},
                        {"row_index": 3, "col_index": 1, "text": "Khảo sát địa chất cầu", "confidence": 0.98},
                        {"row_index": 3, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 4, "col_index": 0, "text": "IV", "confidence": 0.99},
                        {"row_index": 4, "col_index": 1, "text": "Công tác thí nghiệm", "confidence": 0.98},
                        {"row_index": 4, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 5, "col_index": 0, "text": "V", "confidence": 0.99},
                        {"row_index": 5, "col_index": 1, "text": "Lập báo cáo", "confidence": 0.98},
                        {"row_index": 5, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 6, "col_index": 0, "text": "", "confidence": 0.90},
                        {"row_index": 6, "col_index": 1, "text": "Cộng chi phí trực tiếp", "confidence": 0.97},
                        {"row_index": 6, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 7, "col_index": 0, "text": "", "confidence": 0.90},
                        {"row_index": 7, "col_index": 1, "text": "Chi phí chung", "confidence": 0.97},
                        {"row_index": 7, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 8, "col_index": 0, "text": "", "confidence": 0.90},
                        {"row_index": 8, "col_index": 1, "text": "Thu nhập chịu thuế tính trước", "confidence": 0.96},
                        {"row_index": 8, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 9, "col_index": 0, "text": "", "confidence": 0.90},
                        {"row_index": 9, "col_index": 1, "text": "Thuế VAT 10%", "confidence": 0.97},
                        {"row_index": 9, "col_index": 2, "text": "", "confidence": 0.90},
                        {"row_index": 10, "col_index": 0, "text": "", "confidence": 0.90},
                        {"row_index": 10, "col_index": 1, "text": "TỔNG CỘNG", "confidence": 0.98},
                        {"row_index": 10, "col_index": 2, "text": "", "confidence": 0.90},
                    ],
                }
            ],
        },
    ],
}


def _build_parsed_document(job_id: str, filename: str, raw: dict) -> ParsedDocument:
    """Convert raw fixture / API response dict to canonical ParsedDocument."""
    pages = []
    for p in raw["pages"]:
        tables = []
        for t in p.get("tables", []):
            cells = [
                CellContent(
                    row_index=c["row_index"],
                    col_index=c["col_index"],
                    text=c["text"],
                    confidence=c.get("confidence"),
                )
                for c in t["cells"]
            ]
            tables.append(
                ParsedTable(
                    table_index=t["table_index"],
                    page_number=t["page_number"],
                    row_count=t["row_count"],
                    col_count=t["col_count"],
                    cells=cells,
                )
            )
        pages.append(
            ParsedPage(
                page_number=p["page_number"],
                text=p.get("text", ""),
                tables=tables,
            )
        )

    raw_output = RawParserOutput(
        api_version=raw["api_version"],
        model_id=raw["model_id"],
        pages=pages,
        raw_json=raw,
    )

    return ParsedDocument(
        job_id=job_id,
        source_filename=filename,
        page_count=len(pages),
        pages=pages,
        raw_output=raw_output,
    )


async def parse_pdf(job_id: str, filename: str, pdf_bytes: bytes) -> ParsedDocument:
    """
    Main entry point for parsing a PDF.

    If PARSER_USE_MOCK=true (default for development), returns the built-in
    fixture without making any external calls.

    Otherwise, submits pdf_bytes to the configured PARSER_API_URL, polls for
    completion, and normalises the response.

    All external API credentials are read from environment – never passed in
    from business logic.
    """
    use_mock = os.getenv("PARSER_USE_MOCK", "true").lower() == "true"

    if use_mock:
        return _build_parsed_document(job_id, filename, MOCK_FIXTURE)

    api_url = os.getenv("PARSER_API_URL", "")
    api_key = os.getenv("PARSER_API_KEY", "")
    if not api_url:
        raise RuntimeError("PARSER_API_URL not configured and PARSER_USE_MOCK is not 'true'")

    headers = {"Authorization": f"******"}

    async with httpx.AsyncClient(timeout=120) as client:
        # Submit
        submit_resp = await client.post(
            f"{api_url}/jobs",
            files={"file": (filename, pdf_bytes, "application/pdf")},
            headers=headers,
        )
        submit_resp.raise_for_status()
        remote_job_id = submit_resp.json()["job_id"]

        # Poll
        import asyncio
        for _ in range(60):
            await asyncio.sleep(5)
            poll_resp = await client.get(
                f"{api_url}/jobs/{remote_job_id}",
                headers=headers,
            )
            poll_resp.raise_for_status()
            data = poll_resp.json()
            if data["status"] == "completed":
                return _build_parsed_document(job_id, filename, data["result"])
            if data["status"] == "failed":
                raise RuntimeError(f"Parser API returned failed status: {data.get('error')}")

    raise TimeoutError("Parser API did not complete within 5 minutes")
