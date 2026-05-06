# Tiki Auto Crawler & Preprocessing

Giai đoạn hiện tại tập trung vào 2 thư mục chính:

- `CRAWLER/`: tự search keyword trên Tiki, chọn top sản phẩm theo lượt bán/review, crawl toàn bộ comment có nội dung và ghi raw data vào PostgreSQL.
- `PREPROCESSING/`: làm sạch comment, deduplicate, gán nhãn heuristic ban đầu và ghi `processed_reviews`.

Các phần chưa ưu tiên ngay như API phân tích URL thủ công, modeling, notebook/report cũ đã được chuyển vào `NEXT_STEP/`.

## Database dùng chung cho cả nhóm

Mặc định Docker Compose chạy PostgreSQL trên máy bạn; dữ liệu chỉ nằm trong volume local nên **người khác không thấy** được crawl của bạn.

### Cách làm chung một “source of truth”

1. Tạo **một** PostgreSQL mà mọi người trỏ tới, ví dụ: [Neon](https://neon.tech), [Supabase](https://supabase.com), Railway, Render, hoặc VPS + Postgres (mở port có firewall / chỉ IP nhóm).
2. **Clone schema**: chạy `init-db.sql` trên DB cloud (hoặc `pg_dump` từ local rồi restore). Nếu DB đã tồn tại từ trước, chạy thêm migration `migrations/001_extend_model_registry.sql`.
3. Mỗi thành viên đặt cùng chuỗi kết nối trong `.env`:
   - `TIKI_DATA_DB=postgresql+psycopg2://USER:PASSWORD@HOST:5432/tiki_data?sslmode=require`
   - Với Airflow trong Docker: dùng host public của cloud DB (không dùng `localhost` trong container). Trên Airflow UI, sửa connection `tiki_data` cho khớp.
4. Nếu `raw` / `processed` lệch kiểu **`12345` vs `12345.0`** (import CSV): chạy migration `migrations/002_canonicalize_review_ids.sql` (sao lưu trước) rồi chạy lại `dag_clean_label`.
5. **Model `.pkl`**: `model_registry` chỉ lưu **đường dẫn** và **JSON metrics**; file artifact vẫn nằm trên disk máy chạy Airflow. Để cả nhóm dùng cùng mô hình: lưu `.pkl` trên S3/Drive/Git LFS/object storage và đồng bộ, hoặc chạy train/deploy trên **một** server và chia sẻ thư mục `models/`.

### Metrics sau `train_and_evaluate`

Bảng `model_registry` ghi: `model_name` (candidate thắng), `auc_pr`, `f1_score`, `auc_roc`, `threshold`, `n_train`, `fake_rate`, và **`metrics_detail` (JSONB)** — toàn bộ `candidate_metrics` (LR / RF / XGBoost) + danh sách feature như file `*_metrics.json` tạo ra trong `modeling.py`. Tab **Model registry** trong `streamlit_app.py` đọc trực tiếp từ DB này.

---

## Chạy Local Dashboard

```bash
cd DS
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres
streamlit run streamlit_app.py
```

Mở dashboard tại `http://localhost:8501`.

## Chạy Airflow Tự Động Crawl

```bash
docker compose up airflow-init
docker compose up -d
```

- Airflow UI: `http://localhost:8080` với `admin/admin`
- PostgreSQL (metadata Airflow): `localhost:5432`, database `airflow` trong Docker; **`tiki_data` / Neon** do bạn chỉ trong `TIKI_DATA_DB`.

`dag_crawl_tiki` đọc lịch từ `CRAWLER_SCHEDULE` (mặc định mỗi giờ):

1. Search các keyword trong `TIKI_KEYWORDS`.
2. Chọn `CRAWLER_PRODUCTS_PER_KEYWORD` sản phẩm/keyword.
3. Bỏ qua sản phẩm đã crawl trong `crawl_product_history`.
4. Crawl review, chỉ giữ comment có nội dung.
5. Cuối chuỗi **trigger** DAG `dag_clean_label` để preprocessing (DAG này dùng **`TIKI_DATA_DB` trong `.env`**, trùng với Streamlit/Neon).

### Vì sao Comments ≠ Processed trên Neon?

- **Đổi Neon / đổi `.env`** mà **connection Airflow UI** `tiki_data` vẫn localhost → trigger có thể ghi sai chỗ. Dùng **`TIKI_DATA_DB` trùng Neon** trong `.env` (container Airflow đọc `env_file: .env`) và sau khi đổi URI hãy **`docker compose run --rm airflow-init`** để cập nhật connection `tiki_data`, hoặc sửa tay trên UI Airflow.
- Task `clean_and_label` trước đây insert **từng dòng** → với ~60k review qua Neon dễ **timeout**; DAG đã chuyển sang **UPSERT batch** + `PREPROCESSING_TASK_TIMEOUT_HOURS`.
- Bật lịch sửa tay: **`PREPROCESSING_SCHEDULE`** (xem `.env.example`). Mặc định có thể để trống nếu chỉ nhờ trigger sau crawl.
- Trên dashboard, mục **Chẩn đoán processed vs Comments** và nút **Làm mới dashboard** để xem `pending` và `last_clean_label_summary`.

## Cấu Hình Quan Trọng

- `CRAWLER_SCHEDULE`, `TIKI_KEYWORDS`, `TIKI_DATA_DB`
- Preprocessing (`dag_clean_label`): `PREPROCESSING_INCREMENTAL=true`, `PREPROCESSING_BATCH_SIZE`, `PREPROCESSING_TASK_TIMEOUT_HOURS`, tuỳ chọn `PREPROCESSING_SCHEDULE`

## Kiểm Tra

```bash
pytest
```

## Ghi Chú Demo

Crawler thật phụ thuộc API public của Tiki và có delay/retry để tránh spam request. Nếu Tiki đổi response hoặc chặn request, cấu hình thêm `TIKI_COOKIE` hoặc `CRAWLER_PROXY_URL` trong `.env`.
