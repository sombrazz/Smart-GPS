from __future__ import annotations

from typing import Any

import joblib
import pandas as pd

from app.core.settings import MODEL_DIR


class ModelService:
    def __init__(self) -> None:
        self.classifier_bundle: dict[str, Any] | None = None
        self.regressor_bundle: dict[str, Any] | None = None
        self.classifier_path = MODEL_DIR / "vehicle_selector.joblib"
        self.regressor_path = MODEL_DIR / "travel_time_regressor.joblib"
        self.load_if_available()

    def load_if_available(self) -> None:
        if self.classifier_path.exists():
            self.classifier_bundle = joblib.load(self.classifier_path)
        if self.regressor_path.exists():
            self.regressor_bundle = joblib.load(self.regressor_path)

    @property
    def is_loaded(self) -> bool:
        return self.classifier_bundle is not None or self.regressor_bundle is not None

    @property
    def has_regressor(self) -> bool:
        return self.regressor_bundle is not None

    def predict_best_vehicle(self, candidate_rows: list[dict]) -> dict[str, Any] | None:
        if not candidate_rows:
            return None

        if self.regressor_bundle is not None:
            frame = pd.DataFrame(candidate_rows)
            feature_frame = frame[self.regressor_bundle["feature_columns"]]
            predictions = self.regressor_bundle["pipeline"].predict(feature_frame)
            best_idx = int(predictions.argmin())
            selected = candidate_rows[best_idx].copy()
            selected["ml_predicted_response_time_s"] = float(predictions[best_idx])
            selected["ml_strategy"] = "regression"
            return selected

        if self.classifier_bundle is not None:
            frame = pd.DataFrame(candidate_rows)
            feature_frame = frame[self.classifier_bundle["feature_columns"]]
            probabilities = self.classifier_bundle["pipeline"].predict_proba(feature_frame)[:, 1]
            best_idx = int(probabilities.argmax())
            selected = candidate_rows[best_idx].copy()
            selected["ml_score"] = float(probabilities[best_idx])
            selected["ml_strategy"] = "classification"
            return selected

        return None
