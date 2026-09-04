from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pandas as pd

from spotlab.indicators import ema, rsi


def run_ml_research(
    candles: pd.DataFrame,
    output: str | Path,
    *,
    model_name: Literal["logistic", "random_forest"] = "logistic",
    horizon: int = 1,
) -> dict[str, object]:
    """Walk-forward classification experiment; deliberately disconnected from execution."""

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score, precision_score, roc_auc_score
        from sklearn.model_selection import TimeSeriesSplit
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as error:
        raise RuntimeError("Install optional dependency: pip install -e '.[ml]'") from error

    frame = candles.sort_values("open_time").copy()
    returns = frame["close"].pct_change()
    frame["return_1"] = returns
    frame["return_3"] = frame["close"].pct_change(3)
    frame["volatility_12"] = returns.rolling(12).std()
    frame["volume_ratio"] = frame["volume"] / frame["volume"].rolling(20).mean()
    frame["ema_gap"] = ema(frame["close"], 12) / ema(frame["close"], 26) - 1
    frame["rsi"] = rsi(frame["close"], 14) / 100
    future_return = frame["close"].shift(-horizon) / frame["close"] - 1
    frame["target"] = (future_return > 0).astype(int)
    features = ["return_1", "return_3", "volatility_12", "volume_ratio", "ema_gap", "rsi"]
    dataset = frame.dropna(subset=features).iloc[:-horizon].copy()
    x = dataset[features]
    y = dataset["target"]
    splitter = TimeSeriesSplit(n_splits=5, gap=horizon)
    predictions = pd.Series(index=dataset.index, dtype=float)
    probabilities = pd.Series(index=dataset.index, dtype=float)

    for train, test in splitter.split(x):
        if model_name == "logistic":
            model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        else:
            model = RandomForestClassifier(
                n_estimators=300, max_depth=5, min_samples_leaf=20, random_state=42
            )
        model.fit(x.iloc[train], y.iloc[train])
        predictions.iloc[test] = model.predict(x.iloc[test])
        probabilities.iloc[test] = model.predict_proba(x.iloc[test])[:, 1]

    evaluated = predictions.notna()
    actual = y[evaluated]
    predicted = predictions[evaluated].astype(int)
    probability = probabilities[evaluated]
    metrics: dict[str, object] = {
        "model": model_name,
        "horizon_candles": horizon,
        "samples": int(evaluated.sum()),
        "accuracy": float(accuracy_score(actual, predicted)),
        "precision": float(precision_score(actual, predicted, zero_division=0)),
        "roc_auc": (float(roc_auc_score(actual, probability)) if actual.nunique() == 2 else None),
        "execution_connected": False,
        "warning": "Eksperimen ML tidak dapat membuka live gate.",
    }
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    exported = dataset.loc[evaluated, ["open_time", *features, "target"]].copy()
    exported["prediction"] = predicted
    exported["probability_up"] = probability
    exported.to_csv(destination / "ml_predictions.csv", index=False)
    (destination / "ml_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    return metrics
