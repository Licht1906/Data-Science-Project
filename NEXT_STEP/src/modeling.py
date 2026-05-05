from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.feature_engineering import FEATURE_COLUMNS, build_features


@dataclass
class TrainResult:
    model_name: str
    model_path: str
    auc_pr: float
    f1_score: float
    auc_roc: float
    n_train: int
    fake_rate: float
    threshold: float
    metrics_path: str


def train_baseline_models(df: pd.DataFrame, model_dir: str | Path = "models") -> TrainResult:
    if "is_fake" not in df.columns:
        raise ValueError("Training dataframe must include is_fake")
    if len(df) < 20:
        raise ValueError("Need at least 20 labeled rows to train a useful model")

    X = build_features(df)
    y = df["is_fake"].astype(int)
    if y.nunique() < 2:
        raise ValueError("Training dataframe must contain both fake and non-fake labels")
    stratify = y if y.nunique() == 2 else None
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=42,
        stratify=stratify,
    )

    candidates: dict[str, Any] = {
        "logistic_regression": Pipeline(
            [
                ("scaler", StandardScaler()),
                ("model", LogisticRegression(class_weight="balanced", max_iter=1000)),
            ]
        ),
        "random_forest": RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=42),
    }

    try:
        from xgboost import XGBClassifier

        pos = max(int(y_train.sum()), 1)
        neg = max(int((1 - y_train).sum()), 1)
        candidates["xgboost"] = XGBClassifier(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            eval_metric="logloss",
            scale_pos_weight=neg / pos,
            random_state=42,
        )
    except Exception:
        pass

    best_name = ""
    best_model: Any = None
    best_metrics = {"auc_pr": -1.0, "f1": 0.0, "auc_roc": 0.0, "threshold": 0.5}
    all_metrics: dict[str, dict[str, float]] = {}

    for name, model in candidates.items():
        model.fit(X_train, y_train)
        probability = _predict_probability(model, X_test)
        threshold, best_f1 = _best_threshold(y_test, probability)
        prediction = (probability >= threshold).astype(int)
        metrics = {
            "auc_pr": average_precision_score(y_test, probability),
            "f1": best_f1,
            "auc_roc": roc_auc_score(y_test, probability) if y_test.nunique() == 2 else 0.0,
            "threshold": threshold,
        }
        all_metrics[name] = {key: float(value) for key, value in metrics.items()}
        if metrics["auc_pr"] > best_metrics["auc_pr"]:
            best_name = name
            best_model = model
            best_metrics = metrics

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / f"{best_name}_model.pkl"
    bundle = {"model": best_model, "features": FEATURE_COLUMNS, "model_name": best_name, "threshold": best_metrics["threshold"]}
    joblib.dump(bundle, model_path)
    joblib.dump(bundle, model_dir / "xgb_model.pkl")

    metrics_path = model_dir / f"{best_name}_metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "best_model": best_name,
                "best_metrics": {key: float(value) for key, value in best_metrics.items()},
                "candidate_metrics": all_metrics,
                "features": FEATURE_COLUMNS,
                "n_rows": int(len(df)),
                "n_train": int(len(X_train)),
                "fake_rate": float(y.mean()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return TrainResult(
        model_name=best_name,
        model_path=str(model_path),
        auc_pr=float(best_metrics["auc_pr"]),
        f1_score=float(best_metrics["f1"]),
        auc_roc=float(best_metrics["auc_roc"]),
        n_train=int(len(X_train)),
        fake_rate=float(y.mean()),
        threshold=float(best_metrics["threshold"]),
        metrics_path=str(metrics_path),
    )


def predict_fake_probability(model_bundle: Any, features: pd.DataFrame) -> list[float]:
    model = model_bundle.get("model") if isinstance(model_bundle, dict) else model_bundle
    return _predict_probability(model, features).tolist()


def load_model(path: str | Path) -> Any:
    return joblib.load(path)


def _predict_probability(model: Any, features: pd.DataFrame):
    if hasattr(model, "predict_proba"):
        return model.predict_proba(features)[:, 1]
    return model.predict(features)


def _best_threshold(y_true: pd.Series, probability) -> tuple[float, float]:
    best_threshold = 0.5
    best_f1 = 0.0
    for threshold in [value / 100 for value in range(20, 81, 5)]:
        score = f1_score(y_true, (probability >= threshold).astype(int), zero_division=0)
        if score > best_f1:
            best_threshold = threshold
            best_f1 = float(score)
    return best_threshold, best_f1
