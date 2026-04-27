# Hướng dẫn khởi động stack (N1 — Hạ tầng)

## Yêu cầu

- Docker Desktop ≥ 4.x hoặc Docker Engine ≥ 24
- docker compose plugin (v2) — lệnh `docker compose` (không có dấu `-`)
- RAM khuyến nghị: ≥ 4 GB dành cho containers

---

## 1. Cài đặt lần đầu

```bash
# 1. Clone repo và chuyển vào thư mục gốc
git clone https://github.com/Licht1906/Data-Science-Project.git
cd Data-Science-Project
git checkout develop

# 2. Tạo file .env từ mẫu
cp .env.example .env
```

Mở `.env` và điền các giá trị:

| Biến | Mô tả |
|------|-------|
| `POSTGRES_PASSWORD` | Mật khẩu root PostgreSQL |
| `TIKI_DB_PASSWORD` | Mật khẩu DB dữ liệu Tiki |
| `AIRFLOW_DB_PASSWORD` | Mật khẩu DB Airflow metadata |
| `AIRFLOW_FERNET_KEY` | Tạo bằng lệnh bên dưới |
| `AIRFLOW_SECRET_KEY` | Chuỗi bất kỳ, dùng ký session |
| `AIRFLOW_ADMIN_PASSWORD` | Mật khẩu đăng nhập UI Airflow |

**Tạo Fernet key:**
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 2. Khởi động stack

```bash
# Khởi tạo Airflow DB và tạo user admin (chạy 1 lần)
docker compose run --rm airflow-init

# Sau đó chạy toàn bộ stack
docker compose up -d
```

Kiểm tra trạng thái:
```bash
docker compose ps
```

| Service | URL | Ghi chú |
|---------|-----|---------|
| Airflow UI | http://localhost:8080 | user/pass trong `.env` |
| FastAPI | http://localhost:8000/docs | Swagger UI |
| PostgreSQL | localhost:5432 | psql hoặc DBeaver |

---

## 3. Cấu hình Airflow Connection

Sau khi stack chạy, vào **Airflow UI → Admin → Connections** và thêm:

| Field | Giá trị |
|-------|---------|
| Conn Id | `tiki_data` |
| Conn Type | `Postgres` |
| Host | `postgres` |
| Schema | `tiki_data` |
| Login | giá trị `TIKI_DB_USER` trong `.env` |
| Password | giá trị `TIKI_DB_PASSWORD` trong `.env` |
| Port | `5432` |

> Connection này đã được tự động inject qua biến môi trường `AIRFLOW_CONN_TIKI_DATA` trong `docker-compose.yml`. Bước trên chỉ cần thiết nếu muốn kiểm tra thủ công qua UI.

---

## 4. Kiểm tra schema PostgreSQL

```bash
# Kết nối vào DB tiki_data
docker exec -it tiki_postgres psql -U tiki_user -d tiki_data

# Xem danh sách bảng
\dt

# Kiểm tra index
\di
```

Các bảng cần có: `raw_products`, `raw_reviews`, `raw_users`, `processed_reviews`, `model_registry`, `crawl_metadata`.

---

## 5. Chạy DAG mẫu (hello world)

```python
# dags/dag_hello_world.py — test kết nối
from airflow import DAG
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.operators.python import PythonOperator
from datetime import datetime

def check_connection():
    hook = PostgresHook(postgres_conn_id="tiki_data")
    conn = hook.get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM raw_products;")
    count = cursor.fetchone()[0]
    print(f"raw_products count: {count}")

with DAG("hello_world", start_date=datetime(2024, 1, 1), schedule=None, catchup=False) as dag:
    PythonOperator(task_id="check_db", python_callable=check_connection)
```

Đặt file trên vào `dags/`, sau đó trong Airflow UI bật DAG và nhấn **Trigger**.

---

## 6. Troubleshooting

### Port 5432 bị chiếm
```bash
# Đổi port trong .env
POSTGRES_PORT=5433
# Hoặc dừng PostgreSQL cục bộ
sudo systemctl stop postgresql
```

### Reset toàn bộ volume (mất dữ liệu)
```bash
docker compose down -v
docker compose run --rm airflow-init
docker compose up -d
```

### Migrate Airflow DB sau khi nâng cấp image
```bash
docker compose run --rm airflow-webserver airflow db migrate
```

### Quyền thư mục `models/`
```bash
chmod -R 777 models/
# Hoặc trong compose đã mount ./models:/opt/airflow/models
```

### Airflow scheduler không nhận DAG mới
- Đảm bảo file DAG không có lỗi Python: `python dags/dag_xxx.py`
- Kiểm tra log: `docker compose logs airflow-scheduler`

---

## 7. Tắt stack

```bash
# Tắt và giữ data
docker compose down

# Tắt và XÓA data (cẩn thận)
docker compose down -v
```