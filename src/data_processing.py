import pandas as pd
import sqlite3
import os

def load_data(raw_dir="data/raw"):
    train_transaction = pd.read_csv(f"{raw_dir}/train_transaction.csv")
    train_identity    = pd.read_csv(f"{raw_dir}/train_identity.csv")
    print(f"Transaction: {train_transaction.shape}")
    print(f"Identity:    {train_identity.shape}")
    return train_transaction, train_identity

def merge_data(train_transaction, train_identity):
    df = train_transaction.merge(train_identity, on="TransactionID", how="left")
    print(f"Shape sau merge: {df.shape}")
    return df

def save_to_sqlite(df, db_path="data/processed/fraud.db"):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    df.to_sql("transactions", conn, if_exists="replace", index=False)
    conn.close()
    print(f"Đã lưu {len(df)} dòng vào {db_path}")

def load_from_sqlite(db_path="data/processed/fraud.db"):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql("SELECT * FROM transactions", conn)
    conn.close()
    return df

def save_clean_data(df_clean, db_path="data/processed/fraud.db"):
    conn = sqlite3.connect(db_path)
    df_clean.to_sql("transactions_clean", conn, if_exists="replace", index=False)
    conn.close()
    print(f"Đã lưu {len(df_clean)} dòng vào transactions_clean")

def run_sql_analysis(db_path="data/processed/fraud.db"):
    """Chạy SQL queries phân tích gian lận"""
    conn = sqlite3.connect(db_path)

    print("\nTỷ lệ gian lận theo loại thẻ:")
    q1 = pd.read_sql("""
        SELECT card4,
               COUNT(*) as total,
               SUM(isFraud) as fraud_count,
               ROUND(AVG(isFraud) * 100, 2) as fraud_rate_pct
        FROM transactions
        GROUP BY card4
        ORDER BY fraud_rate_pct DESC
    """, conn)
    print(q1.to_string())

    print("\nTỷ lệ gian lận theo giá trị giao dịch:")
    q2 = pd.read_sql("""
        SELECT
            CASE
                WHEN TransactionAmt < 50   THEN '< $50'
                WHEN TransactionAmt < 200  THEN '$50-200'
                WHEN TransactionAmt < 1000 THEN '$200-1000'
                ELSE '> $1000'
            END as amt_bucket,
            COUNT(*) as total,
            ROUND(AVG(isFraud) * 100, 2) as fraud_rate_pct
        FROM transactions
        GROUP BY amt_bucket
        ORDER BY fraud_rate_pct DESC
    """, conn)
    print(q2.to_string())

    conn.close()

if __name__ == "__main__":
    t, i = load_data()
    df   = merge_data(t, i)
    save_to_sqlite(df)