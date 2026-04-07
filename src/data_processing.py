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

if __name__ == "__main__":
    t, i = load_data()
    df   = merge_data(t, i)
    save_to_sqlite(df)