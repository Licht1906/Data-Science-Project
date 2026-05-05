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
4. **Model `.pkl`**: `model_registry` chỉ lưu **đường dẫn** và **JSON metrics**; file artifact vẫn nằm trên disk máy chạy Airflow. Để cả nhóm dùng cùng mô hình: lưu `.pkl` trên S3/Drive/Git LFS/object storage và đồng bộ, hoặc chạy train/deploy trên **một** server và chia sẻ thư mục `models/`.

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
- PostgreSQL: `localhost:5432`, database `tiki_data`

`dag_crawl_tiki` chạy hằng ngày lúc `02:00`, tự động:

1. Search các keyword trong `TIKI_KEYWORDS`.
2. Chọn `CRAWLER_PRODUCTS_PER_KEYWORD=3` sản phẩm/keyword mỗi run để tránh crawl quá tải khi danh sách keyword lớn.
3. Bỏ qua sản phẩm đã crawl xong trong `crawl_product_history`.
4. Crawl toàn bộ page review, chỉ giữ comment có nội dung.
5. Trigger `dag_clean_label` để preprocessing.

## Cấu Hình Quan Trọng

- `CRAWLER_SCHEDULE=0 * * * *` để crawl mỗi giờ một lần
- `TIKI_KEYWORDS`: danh sách khoảng 80 keyword hàng hóa phổ biến hiện nay
- `CRAWLER_PRODUCTS_PER_KEYWORD=3`
- `CRAWLER_SEARCH_PAGES=5`
- `CRAWLER_ALL_REVIEW_PAGES=true`
- `CRAWLER_DELAY_MIN`, `CRAWLER_DELAY_MAX`, `CRAWLER_RETRIES`, `CRAWLER_TIMEOUT`

## Kiểm Tra

```bash
pytest
```

## Ghi Chú Demo

Crawler thật phụ thuộc API public của Tiki và có delay/retry để tránh spam request. Nếu Tiki đổi response hoặc chặn request, cấu hình thêm `TIKI_COOKIE` hoặc `CRAWLER_PROXY_URL` trong `.env`.
