"""In-memory synthetic benchmark using donor ML, never deployment data."""
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
import time
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, balanced_accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


@dataclass(frozen=True)
class Split:
    train: slice
    validation: slice
    test: slice


def make_split(size: int) -> Split:
    if isinstance(size, bool) or not isinstance(size, int) or size < 300:
        raise ValueError("at least 300 ordered samples are required")
    return Split(slice(0, int(size * .6)), slice(int(size * .6), int(size * .8)),
                 slice(int(size * .8), size))


def synthetic(size: int = 2400, seed: int = 17):
    make_split(size)
    if size > 50000:
        raise ValueError("sample budget exceeded")
    rng = np.random.default_rng(seed)
    x = rng.uniform(-1, 1, (size, 6))
    # A deliberately generic toy relationship, not a deployment-specific feature.
    signal = 2.5*x[:, 0] - 1.8*x[:, 1] + 1.2*x[:, 2]*x[:, 3] + .4*x[:, 4]**2
    y = (signal + rng.normal(0, .35, size) > .2).astype(np.int64)
    return x, y


def scores(y, probability):
    p = np.asarray(probability, dtype=np.float64)
    if p.shape != y.shape or not np.all(np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("invalid prediction scores")
    return {"log_loss": float(log_loss(y, p, labels=[0, 1])),
            "brier": float(brier_score_loss(y, p)),
            "average_precision": float(average_precision_score(y, p)),
            "roc_auc": float(roc_auc_score(y, p)),
            "balanced_accuracy": float(balanced_accuracy_score(y, p >= .5))}


def torch_predictor(x_train, y_train, seed, epochs=100):
    import torch
    from torch import nn
    if not 1 <= epochs <= 300:
        raise ValueError("epoch budget exceeded")
    torch.manual_seed(seed)
    previous_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        mean, scale = x_train.mean(0), x_train.std(0)
        scale[scale == 0] = 1.0
        x = torch.tensor((x_train - mean) / scale, dtype=torch.float32)
        y = torch.tensor(y_train, dtype=torch.float32)
        model = nn.Sequential(nn.Linear(6, 24), nn.Tanh(), nn.Linear(24, 12),
                              nn.Tanh(), nn.Linear(12, 1))
        optimizer = torch.optim.Adam(model.parameters(), lr=.01)
        loss_function = nn.BCEWithLogitsLoss()
        for _ in range(epochs):
            optimizer.zero_grad()
            loss = loss_function(model(x).squeeze(1), y)
            loss.backward()
            optimizer.step()
        model.eval()
        def predict(data):
            with torch.inference_mode():
                value = torch.tensor((data - mean) / scale, dtype=torch.float32)
                return torch.sigmoid(model(value).squeeze(1)).cpu().numpy()
        return predict
    finally:
        torch.set_num_threads(previous_threads)


def benchmark(*, size=2400, seed=17, neural=False):
    x, y = synthetic(size, seed)
    parts = make_split(size)
    predictors, timings = {}, {}
    with threadpool_limits(limits=1):
        for name, model in {
            "logistic": make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, random_state=seed)),
            "histogram_boosting": HistGradientBoostingClassifier(max_iter=90, max_leaf_nodes=15,
                early_stopping=False, random_state=seed),
        }.items():
            started = time.perf_counter()
            model.fit(x[parts.train], y[parts.train])
            timings[name] = time.perf_counter() - started
            predictors[name] = lambda data, model=model: model.predict_proba(data)[:, 1]
        if neural:
            started = time.perf_counter()
            predictors["torch_mlp"] = torch_predictor(x[parts.train], y[parts.train], seed)
            timings["torch_mlp"] = time.perf_counter() - started
        validation = {name: scores(y[parts.validation], fn(x[parts.validation]))
                      for name, fn in predictors.items()}
        # Model selection is complete before any test results are calculated.
        winner = min(validation, key=lambda name: (validation[name]["log_loss"], name))
        test = {name: scores(y[parts.test], fn(x[parts.test]))
                for name, fn in predictors.items()}
    fingerprint = hashlib.sha256(x.astype("<f8").tobytes() + y.astype("<i8").tobytes()).hexdigest()
    versions = {p: importlib.metadata.version(p) for p in ("numpy", "scikit-learn", "rdflib")}
    if neural:
        versions["torch"] = importlib.metadata.version("torch")
    return {"scope": "synthetic_demonstration_only", "seed": seed, "samples": size,
            "dataset_sha256": fingerprint, "split": {"train": [0,parts.train.stop],
            "validation": [parts.validation.start,parts.validation.stop],
            "test": [parts.test.start,size]}, "selected_by": "validation_log_loss",
            "selected_model": winner, "validation": validation, "test": test,
            "training_seconds": timings, "versions": versions, "calibration_established": False,
            "production_qualified": False, "saved_weights": False, "external_actions": 0}
