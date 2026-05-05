# Chi tiết Dự án: Tiki Auto Crawler & Preprocessing

Tài liệu này cung cấp mô tả chi tiết về kiến trúc toàn bộ dự án, cấu trúc thư mục, và chức năng cụ thể của từng file mã nguồn.

Dự án này tập trung vào việc tự động hóa quá trình thu thập dữ liệu đánh giá sản phẩm (review) trên Tiki và thực hiện tiền xử lý (preprocessing) để phát hiện và gán nhãn sơ bộ cho các đánh giá nghi vấn (spam, review ảo).

---

## 1. Cấu trúc Tổng quan Thư mục

Dự án được chia thành 3 phần chính, tương ứng với các giai đoạn khác nhau trong vòng đời dữ liệu:
- **`CRAWLER/`**: Quản lý việc thu thập dữ liệu thô (sản phẩm, người dùng, đánh giá) từ Tiki.
- **`PREPROCESSING/`**: Quản lý việc làm sạch, chuẩn hóa văn bản, và gán nhãn heuristic (theo luật) cho các đánh giá.
- **`NEXT_STEP/`**: Chứa mã nguồn cho các bước phát triển tiếp theo (như xây dựng API, giao diện phân tích, mô hình học máy, các notebook EDA).
- Các thư mục/file gốc khác phục vụ cho cấu hình môi trường, triển khai (Docker Compose), cơ sở dữ liệu và kiểm thử.

---

## 2. Chi tiết từng Thư mục và File Code

### 2.1. Thư mục Gốc (Root)

Đây là nơi chứa các cấu hình chung, kịch bản triển khai và điểm chạy chính của giao diện.

- **`README.md`**: Tài liệu hướng dẫn sử dụng nhanh, giải thích cách cài đặt, cách chạy qua Docker và Airflow, và một số lưu ý chung về database chung cho nhóm.
- **`update_pipeline.md`**: File ghi chú (review kiến trúc) trình bày những vấn đề ở pipeline hiện tại, các rủi ro và cách khắc phục trong tương lai (vd: cải thiện Deduplicate, nâng cấp heuristic rules, xây dựng feature cho Machine Learning).
- **`streamlit_app.py`**: File khởi động chính của giao diện Dashboard bằng Streamlit. Nó thiết lập giao diện (page config) và gọi hàm `render_crawler_dashboard()` từ thư mục `CRAWLER`.
- **`docker-compose.yml`**: Cấu hình các dịch vụ Docker để triển khai hệ thống (PostgreSQL, Airflow webserver, Airflow scheduler, airflow-init).
- **`init-db.sql`**: Script SQL dùng để tạo database `tiki_data` và các bảng dữ liệu ban đầu gồm: `raw_products`, `crawl_product_history`, `raw_reviews`, `raw_users`, `processed_reviews`, `model_registry`, và `crawl_metadata`.
- **`db_schema_compat.py`**: Chứa code hỗ trợ tương thích schema database, ánh xạ khi cấu trúc bảng có thay đổi.
- **`.env`** / **`.env.example`**: Các biến môi trường (credentials cho database, chuỗi kết nối Airflow, API keys nếu có). Chỉ commit `.env.example`.
- **`requirements.txt`**: Danh sách các thư viện Python (streamlit, pandas, psycopg2, v.v.).
- **`pytest.ini`**: File cấu hình cho trình chạy kiểm thử tự động `pytest`.
- **`.gitignore`**: Danh sách các thư mục, tệp không được commit lên git.
- **`migrations/001_extend_model_registry.sql`**: Script SQL để cập nhật các bảng database cũ — mở rộng tính năng theo dõi mô hình học máy trong bảng `model_registry`.
- **`tests/`**: Thư mục chứa các script kiểm thử (unit tests).
  - `conftest.py`: Các thiết lập môi trường test dùng chung (fixtures).
  - `test_crawlers.py`: Test các hàm và logic trong module CRAWLER.
  - `test_preprocessing.py`: Test các tính năng làm sạch văn bản, labeling.

---

### 2.2. Thư mục `CRAWLER/`

Chịu trách nhiệm hoàn toàn cho việc crawl dữ liệu tự động.

- **`CRAWLER/dashboard.py`**: Code xây dựng giao diện Streamlit, vẽ các biểu đồ phân tích, hiển thị thống kê dữ liệu đã crawl được (số lượng product, review, user; tỷ lệ review nghi vấn; phân bố flag, v.v.).
- **`CRAWLER/keywords_env.py`**: Đọc và expose danh sách keyword tìm kiếm sản phẩm từ biến môi trường `TIKI_KEYWORDS`.

**Thư mục `CRAWLER/crawlers/`** (Logic crawler cốt lõi):
- **`base_crawler.py`**: Lớp cha `BaseCrawler` — cung cấp HTTP client với retry tự động, delay ngẫu nhiên (polite crawling), xử lý 403/429, lưu checkpoint JSON.
- **`product_crawler.py`**: `ProductCrawler` — tìm kiếm keyword trên Tiki API (`/products`), sắp xếp theo lượt bán/review, lọc sản phẩm đã crawl, hỗ trợ cả crawl theo category.
- **`review_crawler.py`**: `ReviewCrawler` — crawl tất cả các trang bình luận của một product_id, chỉ giữ review có nội dung, normalize dữ liệu review.
- **`user_crawler.py`**: `UserCrawler` — thu thập thông tin lịch sử của người dùng Tiki (số review, ngày join, điểm trung bình đã cho).

**Thư mục `CRAWLER/dags/`**:
- **`dag_crawl_tiki.py`**: DAG Airflow chạy hàng ngày lúc 2 giờ sáng — tự động search keyword, chọn top sản phẩm, crawl review và user, lưu vào DB, kích hoạt `dag_clean_label`.

---

### 2.3. Thư mục `PREPROCESSING/`

Nơi diễn ra quá trình làm sạch dữ liệu và phát hiện các đánh giá bất thường.

- **`PREPROCESSING/db.py`**: Hàm kết nối và truy vấn PostgreSQL cho pipeline tiền xử lý (đọc `raw_reviews`, ghi `processed_reviews`).
- **`PREPROCESSING/nlp_utils.py`**: Bộ công cụ NLP cho tiếng Việt: `clean_text` (xoá URL, emoji, lower case, nén ký tự lặp), `count_words`, `is_noise_text`, `is_only_generic`, `caps_ratio`, `has_generic_phrase`.
- **`PREPROCESSING/labeling.py`**: Logic gán nhãn heuristic với hệ thống tín hiệu có trọng số (weighted signals):
  - **Strong signals** (weight 1.2–1.5): `s_noise`, `s_duplicate_content`, `s_burst_review`
  - **Medium signals** (weight 0.6–0.8): `m_only_generic`, `m_angry_short`, `m_empty_praise`, `m_excessive_caps`
  - **Weak signals** (weight 0.2–0.4): `w_zero_activity`, `w_rating_deviation`, `w_short_content`
  - Ngưỡng mặc định `score_threshold = 1.8` — review vượt ngưỡng bị gán `is_fake=1`.

**Thư mục `PREPROCESSING/dags/`**:
- **`dag_clean_label.py`**: DAG Airflow — đọc `raw_reviews`, join với `raw_users`/`raw_products`, deduplicate theo `review_id`, clean text, chấm điểm heuristic, lưu vào `processed_reviews`.

---

### 2.4. Thư mục `NEXT_STEP/`

Chứa mã nguồn cho các bước mở rộng sau giai đoạn heuristic.

**Thư mục `NEXT_STEP/api/`** (Backend FastAPI):
- **`main.py`**: Khởi động FastAPI app với tiêu đề "Tiki Fake Review Detection API", thêm CORS middleware.
- **`routes.py`**: Định nghĩa các API endpoints (phân tích URL sản phẩm, dự đoán fake probability).
- **`services.py`**: Business logic — tích hợp model ML với API, query DB để lấy review.
- **`schemas.py`**: Pydantic models cho request/response validation.
- **`deps.py`**: FastAPI dependencies (DB connection, auth).

**Thư mục `NEXT_STEP/app/`** (Dashboard mở rộng):
- **`dashboard.py`**: Phiên bản Dashboard Streamlit nâng cao cho giai đoạn ML.
- **`product_analyzer.py`**: Công cụ cho phép người dùng paste link Tiki để nhận báo cáo phân tích review của sản phẩm đó.

**Thư mục `NEXT_STEP/src/`** (ML core):
- **`feature_engineering.py`**: Trích xuất 20+ features từ DataFrame: rating, word count, caps ratio, review hour, exclamation count, unique word ratio, generic phrase flag, rating deviation vs. product average, user activity, v.v. Kèm `FEATURE_LABELS_VI` cho UI tiếng Việt.
- **`modeling.py`**: Train Logistic Regression, Random Forest, XGBoost; chọn model tốt nhất theo AUC-PR; lưu `.pkl` và `_metrics.json`; expose hàm `predict_fake_probability()` và `load_model()`.

**Thư mục `NEXT_STEP/dags/`**:
- **`dag_retrain_model.py`**: DAG Airflow để tự động retrain model ML định kỳ khi có đủ dữ liệu mới.

**Thư mục `NEXT_STEP/notebooks/`**:
- `01_EDA.ipynb` — Khảo sát phân bố dữ liệu sản phẩm và đánh giá.
- `02_Labeling.ipynb` — Thử nghiệm và điều chỉnh các luật heuristic.
- `03_Feature_Engineering.ipynb` — Tạo nháp và xem tương quan của features.
- `04_Modeling.ipynb` — Chạy thử nghiệm các mô hình ML.
- `05_NLP_Analysis.ipynb` — Phân tích sâu văn bản, clustering câu từ phổ biến.

**`NEXT_STEP/models/`** & **`NEXT_STEP/reports/`**:
- `models/` — Thư mục lưu artifact `.pkl` sau khi train (gitignored, chỉ giữ `.gitkeep`).
- `reports/figures/` — Lưu biểu đồ kết quả đánh giá model.

**`NEXT_STEP/Dockerfile.api`** — Docker image build cho FastAPI server.
