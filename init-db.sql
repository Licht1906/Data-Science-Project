CREATE DATABASE tiki_data;

\connect tiki_data;

CREATE TABLE IF NOT EXISTS raw_products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    price REAL,
    brand TEXT,
    rating_avg REAL,
    review_count INTEGER DEFAULT 0,
    url TEXT,
    crawled_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS crawl_product_history (
    keyword TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES raw_products(product_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'discovered',
    selected_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    review_count INTEGER DEFAULT 0,
    PRIMARY KEY (keyword, product_id)
);

CREATE TABLE IF NOT EXISTS raw_reviews (
    review_id TEXT PRIMARY KEY,
    product_id TEXT REFERENCES raw_products(product_id) ON DELETE CASCADE,
    user_id TEXT,
    rating INTEGER,
    content TEXT,
    created_at TIMESTAMP,
    helpful_count INTEGER DEFAULT 0,
    purchased BOOLEAN DEFAULT FALSE,
    title TEXT,
    crawled_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS raw_users (
    user_id TEXT PRIMARY KEY,
    name TEXT,
    join_date TIMESTAMP,
    total_reviews INTEGER DEFAULT 0,
    avg_rating_given REAL,
    crawled_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS processed_reviews (
    review_id TEXT PRIMARY KEY,
    product_id TEXT,
    user_id TEXT,
    rating INTEGER,
    content_clean TEXT,
    is_fake INTEGER NOT NULL,
    fake_probability REAL,
    flag_count INTEGER NOT NULL,
    flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    label_version TEXT DEFAULT 'heuristic_v1',
    processed_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_id SERIAL PRIMARY KEY,
    model_path TEXT NOT NULL,
    model_name TEXT,
    auc_pr REAL,
    f1_score REAL,
    auc_roc REAL,
    threshold REAL,
    n_train INTEGER,
    fake_rate REAL,
    metrics_path TEXT,
    metrics_detail JSONB,
    is_active BOOLEAN DEFAULT FALSE,
    trained_at TIMESTAMP DEFAULT NOW(),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS crawl_metadata (
    crawl_key TEXT PRIMARY KEY,
    last_value TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reviews_crawled ON raw_reviews(crawled_at);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON raw_reviews(product_id);
CREATE INDEX IF NOT EXISTS idx_reviews_user ON raw_reviews(user_id);
CREATE INDEX IF NOT EXISTS idx_crawl_history_keyword_status ON crawl_product_history(keyword, status);
CREATE INDEX IF NOT EXISTS idx_crawl_history_keyword_product ON crawl_product_history(keyword, product_id);
CREATE INDEX IF NOT EXISTS idx_processed_review_time ON processed_reviews(processed_at);
CREATE INDEX IF NOT EXISTS idx_processed_fake ON processed_reviews(is_fake);
CREATE INDEX IF NOT EXISTS idx_model_registry_active ON model_registry(is_active);
