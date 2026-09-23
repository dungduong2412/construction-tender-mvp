# Construction Tender MVP

Hệ thống tự động hóa lập dự toán khảo sát xây dựng.  
Tải lên file BOQ PDF bằng tiếng Việt → Azure Document Intelligence trích xuất cấu trúc → AI ánh xạ hạng mục vào định mức → Engine tính giá → Người dùng kiểm tra và tải xuống Excel.

---

## Kiến trúc

```
tender-mvp/
├── backend/
│   ├── adapters/
│   │   └── parser_adapter.py   # Parser Adapter Contract + mock fixture
│   ├── engine/
│   │   ├── reconstructor.py    # BOQ hierarchy reconstruction
│   │   ├── master_loader.py    # Versioned master data loader
│   │   ├── mapper.py           # AI Semantic Mapping module
│   │   ├── pricing.py          # Deterministic pricing engine
│   │   └── exporter.py         # Excel (.xlsx) exporter
│   ├── models/
│   │   ├── domain.py           # Pydantic domain models
│   │   └── store.py            # In-memory job store
│   ├── routes/
│   │   └── jobs.py             # FastAPI REST API endpoints
│   ├── seeds/
│   │   └── master_data_v1.json # Versioned master pricing data
│   └── main.py                 # FastAPI application entry point
├── frontend/
│   └── index.html              # Single-page review UI
├── tests/
│   ├── test_parser.py
│   ├── test_reconstructor.py
│   ├── test_mapper.py
│   ├── test_pricing.py
│   └── test_exporter.py
├── .env.template               # Environment variable template
└── requirements.txt
```

---

## Cài đặt và chạy

### 1. Cài đặt phụ thuộc

```bash
cd tender-mvp
pip install -r requirements.txt
```

### 2. Cấu hình môi trường

```bash
cp .env.template .env
# Chỉnh sửa .env – mặc định PARSER_USE_MOCK=true để dùng mock fixture
```

### 3. Khởi động server

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Mở trình duyệt tại: `http://localhost:8000`

Hoặc chạy trực tiếp file HTML (cần sửa `const API = 'http://localhost:8000'` trong `frontend/index.html`).

### 4. Chạy tests

```bash
cd tender-mvp
pytest tests/ -v
```

---

## API Endpoints

| Method | URL | Mô tả |
|--------|-----|--------|
| POST | `/api/jobs` | Tải lên PDF, bắt đầu pipeline |
| GET | `/api/jobs` | Danh sách jobs |
| GET | `/api/jobs/{id}` | Trạng thái và bảng giá |
| POST | `/api/jobs/{id}/override` | Ghi đè giá/khối lượng |
| GET | `/api/jobs/{id}/export` | Tải xuống .xlsx |
| GET | `/health` | Health check |

---

## Parser Adapter Contract

**Adapter file:** `backend/adapters/parser_adapter.py`

### External API (đang được phát triển độc lập)

```
POST {PARSER_API_URL}/jobs
  Body: multipart/form-data  file=<pdf bytes>
  Returns: {"job_id": "<uuid>", "status": "queued"}

GET {PARSER_API_URL}/jobs/{job_id}
  Returns: {
    "status": "completed|processing|failed",
    "result": <AnalyzeResult JSON>   # Azure Document Intelligence schema
  }
```

**Biến môi trường bắt buộc khi dùng API thật:**
- `PARSER_API_URL` – Base URL
- `PARSER_API_KEY` – API key (giữ bí mật, chỉ để ở backend)

**Chế độ mock:** đặt `PARSER_USE_MOCK=true` (mặc định) để dùng fixture tích hợp sẵn,  
cho phép toàn bộ workflow chạy trước khi API thật sẵn sàng.

---

## Job States

```
uploaded → parsing → mapping → pricing → needs_review / ready → exported
                                                              ↘ failed (bất cứ giai đoạn nào)
```

---

## Dữ liệu định mức (Master Data)

File: `backend/seeds/master_data_v1.json`  
Phiên bản: `1.0.0`  
Nguồn: Phân tích đọc-chỉ từ `DuToan KS CauBinhGoi 2609.21 DuThau.xls` (62 sheets).

File JSON được nạp một lần khi khởi động. **Workbook Excel không bao giờ được đọc lại trong quá trình xử lý PDF.**

### Quy tắc đơn vị được phê duyệt

| Từ | Sang | Hệ số | Ghi chú |
|----|------|--------|---------|
| 100m | m | 100 | Chuyển đơn giá/100m sang đơn giá/m |
| 100ha | ha | 100 | |
| km | m | 1000 | |
| 100m² | m² | 100 | |

**Quan trọng:** Đơn vị không có quy tắc được phê duyệt sẽ KHÔNG được tự động chuyển đổi.  
`TN` ≠ `thí nghiệm` nếu không có quy tắc tường minh.

---

## Báo cáo khoảng trống định mức (Master Data Gap Report)

Xem phần `unresolved_gap_report` trong `master_data_v1.json`.

| Hạng mục | Lý do | Đề xuất |
|----------|--------|---------|
| Chi phí di chuyển thiết bị khoan | Không có đơn giá tổng trong Excel | Yêu cầu báo giá nhà thầu phụ |
| Thí nghiệm nước ngầm | Sheet 'Đơn giá chi tiết' có tham chiếu nhưng không đọc được đơn giá | Đánh dấu UNRESOLVED |
| Cắm cọc tim tuyến | Không có mã định mức phù hợp trong 62 sheet | Tra cứu QCVN hiện hành |
| Hệ số điều chỉnh lương | Sheet 'Hệ số' phụ thuộc vùng/thời kỳ chưa xác minh | Dùng hệ số = 1,0 và trình chủ đầu tư xem xét |
| Thuế VAT | Tỷ lệ 8% hay 10% chưa xác nhận cho kỳ hợp đồng | Áp dụng 10% mặc định; chủ đầu tư xác nhận |

---

## Các quy tắc không thể vi phạm (Non-Negotiables)

- ✅ Phân biệt khoan đường 0–30m (624m) và khoan cầu 0–60m (600m).
- ✅ Không tự ý chuyển đổi 100ha↔ha, 100m↔m, TN↔thí nghiệm khi chưa có quy tắc phê duyệt.
- ✅ Giữ nguyên dấu phẩy thập phân tiếng Việt: 29,5; 19,50; 0,030; 342,34.
- ✅ IV.1 18.57 Km là siêu dữ liệu nhóm, không phải hàng tính tiền.
- ✅ Số hàng lặp lại ở các phần khác nhau được nhận diện theo ngữ cảnh.
- ✅ Số 0 không được dùng làm giá trị mặc định cho khối lượng hoặc đơn giá bị thiếu.
- ✅ Mọi số liệu đầu ra đều phải truy vết được đến PDF, định mức đã phiên bản hóa, override của người dùng, hoặc công thức xác định.
- ✅ LLM chỉ được dùng để phân loại/ánh xạ; KHÔNG tính toán tiền.

---

## Lưu ý bảo mật

- Thông tin xác thực API chỉ lưu ở backend qua biến môi trường.
- Không commit file `.env` vào version control.
- MVP này dùng bộ nhớ trong (in-memory store); dữ liệu mất khi server khởi động lại.
- **Không deploy lên Production khi chưa được phép tường minh.**
