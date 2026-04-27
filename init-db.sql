-- ============================================================
-- init-db.sql — N1: Khởi tạo DB và schema cho dự án
-- Chạy tự động khi container PostgreSQL khởi động lần đầu
-- ============================================================

-- ============================================================
-- 1. Tạo user và database riêng cho Airflow metadata
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = current_setting('AIRFLOW_DB_USER', true)) THEN
        EXECUTE format(
            'CREATE USER %I WITH PASSWORD %L',
            current_setting('AIRFLOW_DB_USER', true),
            current_setting('AIRFLOW_DB_PASSWORD', true)
        );
    END IF;
END
$$;

DO $$
DECLARE
    airflow_db TEXT := current_setting('AIRFLOW_DB_NAME', true);
    airflow_user TEXT := current_setting('AIRFLOW_DB_USER', true);
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = airflow_db) THEN
        EXECUTE format('CREATE DATABASE %I OWNER %I', airflow_db, airflow_user);
    END IF;
END
$$;

-- ============================================================
-- 2. Tạo user và database cho dữ liệu Tiki
-- ============================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = current_setting('TIKI_DB_USER', true)) THEN
        EXECUTE format(
            'CREATE USER %I WITH PASSWORD %L',
            current_setting('TIKI_DB_USER', true),
            current_setting('TIKI_DB_PASSWORD', true)
        );
    END IF;
END
$$;

DO $$
DECLARE
    tiki_db TEXT := current_setting('TIKI_DB_NAME', true);
    tiki_user TEXT := current_setting('TIKI_DB_USER', true);
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = tiki_db) THEN
        EXECUTE format('CREATE DATABASE %I OWNER %I', tiki_db, tiki_user);
    END IF;
END
$$;

-- ============================================================
-- 3. Kết nối vào tiki_data để tạo schema
-- ============================================================
\connect tiki_data

-- Đảm bảo owner đúng
GRANT ALL PRIVILEGES ON DATABASE tiki_data TO tiki_user;

-- ============================================================
-- TABLE: raw_products
-- Lưu metadata sản phẩm thu thập từ Tiki (N3 ghi)
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_products (
    id                  BIGSERIAL PRIMARY KEY,
    product_id          BIGINT NOT NULL UNIQUE,
    name                TEXT,
    category            TEXT,
    sub_category        TEXT,
    brand               TEXT,
    price               NUMERIC(15, 2),
    rating_average      NUMERIC(3, 2),
    review_count        INT DEFAULT 0,
    url                 TEXT,
    seller_id           BIGINT,
    seller_name         TEXT,
    is_official_store   BOOLEAN DEFAULT FALSE,
    raw_json            JSONB,              -- toàn bộ payload API gốc
    crawled_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index hỗ trợ incremental crawl (kiểm tra sản phẩm đã tồn tại)
CREATE INDEX IF NOT EXISTS idx_raw_products_product_id   ON raw_products (product_id);
CREATE INDEX IF NOT EXISTS idx_raw_products_category     ON raw_products (category);
CREATE INDEX IF NOT EXISTS idx_raw_products_crawled_at   ON raw_products (crawled_at);

-- ============================================================
-- TABLE: raw_reviews
-- Review thô từ Tiki (N3 ghi, N4 đọc để xử lý)
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_reviews (
    id              BIGSERIAL PRIMARY KEY,
    review_id       BIGINT NOT NULL UNIQUE,
    product_id      BIGINT NOT NULL REFERENCES raw_products (product_id) ON DELETE CASCADE,
    user_id         BIGINT,
    content         TEXT,
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    purchased       BOOLEAN DEFAULT FALSE,  -- đã mua hàng xác nhận
    helpful_count   INT DEFAULT 0,
    title           TEXT,
    images          JSONB,                  -- mảng URL ảnh đính kèm
    raw_json        JSONB,
    review_time     TIMESTAMPTZ,            -- thời điểm user viết review
    crawled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index phục vụ incremental (crawl review mới nhất theo product)
CREATE INDEX IF NOT EXISTS idx_raw_reviews_product_id  ON raw_reviews (product_id);
CREATE INDEX IF NOT EXISTS idx_raw_reviews_user_id     ON raw_reviews (user_id);
CREATE INDEX IF NOT EXISTS idx_raw_reviews_review_time ON raw_reviews (review_time DESC);
CREATE INDEX IF NOT EXISTS idx_raw_reviews_crawled_at  ON raw_reviews (crawled_at DESC);

-- ============================================================
-- TABLE: raw_users
-- Thông tin user lấy từ review (N3 ghi)
-- ============================================================
CREATE TABLE IF NOT EXISTS raw_users (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL UNIQUE,
    name            TEXT,
    avatar_url      TEXT,
    review_count    INT DEFAULT 0,
    join_date       TIMESTAMPTZ,
    is_verified     BOOLEAN DEFAULT FALSE,
    raw_json        JSONB,
    crawled_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_users_user_id    ON raw_users (user_id);
CREATE INDEX IF NOT EXISTS idx_raw_users_crawled_at ON raw_users (crawled_at DESC);

-- ============================================================
-- TABLE: processed_reviews
-- Review đã làm sạch + gán nhãn (N4 ghi, N5 đọc)
-- ============================================================
CREATE TABLE IF NOT EXISTS processed_reviews (
    id                  BIGSERIAL PRIMARY KEY,
    review_id           BIGINT NOT NULL UNIQUE REFERENCES raw_reviews (review_id) ON DELETE CASCADE,
    product_id          BIGINT NOT NULL,
    user_id             BIGINT,
    -- Text đã xử lý
    content_clean       TEXT,
    -- Features heuristic
    rating              SMALLINT,
    content_length      INT,
    user_review_count   INT,
    purchased           BOOLEAN,
    -- Nhãn heuristic (N4)
    flag_extreme_rating         BOOLEAN DEFAULT FALSE,
    flag_short_content          BOOLEAN DEFAULT FALSE,
    flag_new_account            BOOLEAN DEFAULT FALSE,
    flag_not_verified_purchase  BOOLEAN DEFAULT FALSE,
    flag_generic_phrase         BOOLEAN DEFAULT FALSE,
    flag_count                  SMALLINT DEFAULT 0,
    is_fake                     SMALLINT DEFAULT 0,  -- 0/1 weak label
    -- Xác suất từ model (N5 cập nhật sau khi predict)
    fake_probability    NUMERIC(5, 4),
    model_version       TEXT,
    predicted_at        TIMESTAMPTZ,
    -- Metadata
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dag_run_id          TEXT        -- traceability: DAG run nào tạo bản ghi này
);

CREATE INDEX IF NOT EXISTS idx_processed_reviews_review_id   ON processed_reviews (review_id);
CREATE INDEX IF NOT EXISTS idx_processed_reviews_product_id  ON processed_reviews (product_id);
CREATE INDEX IF NOT EXISTS idx_processed_reviews_is_fake     ON processed_reviews (is_fake);
CREATE INDEX IF NOT EXISTS idx_processed_reviews_processed_at ON processed_reviews (processed_at DESC);

-- ============================================================
-- TABLE: model_registry
-- Lưu metadata mỗi lần train/retrain (N5 ghi, N1/N2 đọc)
-- ============================================================
CREATE TABLE IF NOT EXISTS model_registry (
    id              BIGSERIAL PRIMARY KEY,
    version         TEXT NOT NULL UNIQUE,   -- vd: "v20240115_xgb"
    algorithm       TEXT NOT NULL,          -- LogisticRegression / RandomForest / XGBoost
    artifact_path   TEXT NOT NULL,          -- đường dẫn file .pkl trong container
    -- Metrics đánh giá
    auc_roc         NUMERIC(6, 4),
    auc_pr          NUMERIC(6, 4),
    f1_score        NUMERIC(6, 4),
    precision_score NUMERIC(6, 4),
    recall_score    NUMERIC(6, 4),
    -- Ngưỡng deploy
    threshold_auc_pr NUMERIC(6, 4) DEFAULT 0.70,
    is_deployed     BOOLEAN DEFAULT FALSE,
    deployed_at     TIMESTAMPTZ,
    -- Dataset dùng train
    train_size      INT,
    test_size       INT,
    fake_ratio_train NUMERIC(5, 4),
    -- Metadata
    trained_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dag_run_id      TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_model_registry_version     ON model_registry (version);
CREATE INDEX IF NOT EXISTS idx_model_registry_is_deployed ON model_registry (is_deployed);
CREATE INDEX IF NOT EXISTS idx_model_registry_trained_at  ON model_registry (trained_at DESC);

-- ============================================================
-- TABLE: crawl_metadata
-- Ghi lại lịch sử từng DAG run crawl (N3 ghi, N1 dùng monitoring)
-- ============================================================
CREATE TABLE IF NOT EXISTS crawl_metadata (
    id              BIGSERIAL PRIMARY KEY,
    dag_id          TEXT NOT NULL,
    dag_run_id      TEXT NOT NULL UNIQUE,
    task_id         TEXT,
    status          TEXT NOT NULL DEFAULT 'running', -- running / success / failed
    -- Thống kê
    products_crawled    INT DEFAULT 0,
    reviews_crawled     INT DEFAULT 0,
    reviews_new         INT DEFAULT 0,
    users_crawled       INT DEFAULT 0,
    -- Thời gian
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    duration_sec    INT GENERATED ALWAYS AS (
        EXTRACT(EPOCH FROM (finished_at - started_at))::INT
    ) STORED,
    -- Thông tin incremental
    last_review_time    TIMESTAMPTZ,    -- mốc thời gian review mới nhất đã crawl
    error_message       TEXT
);

CREATE INDEX IF NOT EXISTS idx_crawl_metadata_dag_id      ON crawl_metadata (dag_id);
CREATE INDEX IF NOT EXISTS idx_crawl_metadata_started_at  ON crawl_metadata (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawl_metadata_status      ON crawl_metadata (status);

-- ============================================================
-- Cấp quyền cho tiki_user trên tất cả bảng
-- ============================================================
GRANT ALL PRIVILEGES ON ALL TABLES    IN SCHEMA public TO tiki_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO tiki_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON TABLES    TO tiki_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT ALL ON SEQUENCES TO tiki_user;