from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import classification_report, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.settings import MODEL_DIR


FEATURE_COLUMNS = [
    "distance_to_team_m",
    "base_eta_s",
    "priority_weighted_eta_s",
    "route_edge_count",
    "blocked_edges_in_path",
    "avg_congestion",
    "vehicle_type",
    "team_priority",
    "vehicle_status",
    "operation_sector",
    "vehicle_capacity",
    "vehicle_speed_kmh",
    "team_waiting_time_s",
]


def _build_preprocessor() -> tuple[ColumnTransformer, list[str]]:
    categorical = ["vehicle_type", "team_priority", "vehicle_status", "operation_sector"]
    numeric = [column for column in FEATURE_COLUMNS if column not in categorical]
    preprocessor = ColumnTransformer(
        transformers=[
            ("categorical", OneHotEncoder(handle_unknown="ignore"), categorical),
            ("numeric", "passthrough", numeric),
        ]
    )
    return preprocessor, categorical


def train(dataset_path: str) -> None:
    frame = pd.read_csv(dataset_path)
    required = {"best_vehicle_label", "observed_response_time_s"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Dataset must contain {sorted(required)}")

    X = frame[FEATURE_COLUMNS]
    y_class = frame["best_vehicle_label"]
    y_reg = frame["observed_response_time_s"]

    class_count = int(y_class.nunique())
    min_class_count = int(y_class.value_counts().min())
    stratify_target = y_class if min_class_count >= 2 else None
    test_size = max(0.2, class_count / max(len(frame), 1))
    if test_size >= 1.0:
        test_size = 0.5

    X_train, X_test, y_class_train, y_class_test, y_reg_train, y_reg_test = train_test_split(
        X,
        y_class,
        y_reg,
        test_size=test_size,
        random_state=42,
        stratify=stratify_target,
    )

    class_preprocessor, _ = _build_preprocessor()
    classifier = Pipeline(
        steps=[
            ("preprocess", class_preprocessor),
            ("model", RandomForestClassifier(n_estimators=240, random_state=42, class_weight="balanced")),
        ]
    )
    classifier.fit(X_train, y_class_train)
    class_predictions = classifier.predict(X_test)
    print("=== Classification ===")
    print(classification_report(y_class_test, class_predictions, digits=4, zero_division=0))

    reg_preprocessor, _ = _build_preprocessor()
    regressor = Pipeline(
        steps=[
            ("preprocess", reg_preprocessor),
            ("model", RandomForestRegressor(n_estimators=260, random_state=42)),
        ]
    )
    regressor.fit(X_train, y_reg_train)
    reg_predictions = regressor.predict(X_test)
    print("=== Regression ===")
    print(f"MAE: {mean_absolute_error(y_reg_test, reg_predictions):.4f}")
    print(f"R2: {r2_score(y_reg_test, reg_predictions):.4f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    classifier_path = MODEL_DIR / "vehicle_selector.joblib"
    regressor_path = MODEL_DIR / "travel_time_regressor.joblib"
    joblib.dump({"pipeline": classifier, "feature_columns": FEATURE_COLUMNS}, classifier_path)
    joblib.dump({"pipeline": regressor, "feature_columns": FEATURE_COLUMNS}, regressor_path)
    print(f"Classifier saved to: {classifier_path}")
    print(f"Regressor saved to: {regressor_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train ML models for vehicle selection and travel time.")
    parser.add_argument("dataset_path", help="Path to the synthetic CSV dataset.")
    args = parser.parse_args()
    train(args.dataset_path)


if __name__ == "__main__":
    main()
