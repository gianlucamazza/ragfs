"""ADR-009 normalizers and multi-evidence retrieval denominators."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter


def normalize(value: str | None, *, lenient: bool = False, free_text: bool = False):
    if value is None:
        return None
    value = unicodedata.normalize("NFKC", value).strip()
    if lenient:
        value = " ".join(value.casefold().split())
        if free_text:
            value = re.sub(r"^(a|an|the)\s+", "", value)
    return value


def lexical(prediction, gold, *, lenient=False, free_text=False):
    pred = normalize(prediction, lenient=lenient, free_text=free_text)
    truth = normalize(gold, lenient=lenient, free_text=free_text)
    exact = float(pred == truth)
    if pred is None or truth is None:
        return exact, exact
    p, g = Counter(pred.split()), Counter(truth.split())
    if not p or not g:
        return exact, exact
    overlap = sum((p & g).values())
    return exact, 2 * overlap / (sum(p.values()) + sum(g.values()))


def recall(retrieved: list[str], gold: list[str], k: int) -> dict:
    if k < 1:
        raise ValueError("k must be positive")
    expected, actual = set(gold), set(retrieved[:k])
    if not expected:
        return {"any": None, "all": None, "frac": None}
    overlap = expected & actual
    return {"any": float(bool(overlap)), "all": float(expected <= actual),
            "frac": len(overlap) / len(expected)}


def fact_match(prediction: dict, gold: dict, *, lenient: bool = False) -> bool:
    return prediction["source"] == gold["source"] and all(
        normalize(prediction[key], lenient=lenient) == normalize(gold[key], lenient=lenient)
        for key in ("current", "replaced")
    )
