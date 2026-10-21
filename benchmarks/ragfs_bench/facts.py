"""Versioned facts: validation, half-open intervals and provenance-preserving answers."""
from __future__ import annotations

from datetime import datetime

KINDS = {"user-utterance", "document", "system"}


def timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Timestamps must be RFC3339 UTC ending in Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_facts(records: list[dict]) -> dict[str, dict]:
    by_id = {}
    chains: dict[str, list[dict]] = {}
    successors = set()
    for record in records:
        for key in ("fact_id", "revision_id", "provenance"):
            if not isinstance(record.get(key), str) or not record[key]:
                raise ValueError(f"Missing {key}")
        rid = record["revision_id"]
        if rid in by_id:
            raise ValueError("Duplicate revision_id")
        if record.get("value") is not None and not isinstance(record["value"], str):
            raise ValueError("Fact value must be string or null")
        start = timestamp(record["valid_from"])
        end = record["valid_to"]
        if end is not None and timestamp(end) <= start:
            raise ValueError("Invalid validity interval")
        if record["value"] is None and end is None:
            raise ValueError("Deletion sentinel must have a closed interval")
        source = record["source"]
        if source["kind"] not in KINDS or not isinstance(source["uri"], str) or not source["uri"]:
            raise ValueError("Invalid source")
        timestamp(source["recorded_at"])
        by_id[rid] = record
        chains.setdefault(record["fact_id"], []).append(record)
    for record in records:
        previous = record["supersedes"]
        if previous is None:
            continue
        if previous not in by_id or by_id[previous]["fact_id"] != record["fact_id"]:
            raise ValueError("Missing or cross-fact predecessor")
        if previous in successors:
            raise ValueError("Nonlinear revision chain")
        successors.add(previous)
        if timestamp(by_id[previous]["valid_from"]) >= timestamp(record["valid_from"]):
            raise ValueError("Predecessor must be earlier")
    for chain in chains.values():
        chain.sort(key=lambda item: timestamp(item["valid_from"]))
        if sum(item["supersedes"] is None for item in chain) != 1:
            raise ValueError("Each fact must have one chain root")
        for old, new in zip(chain, chain[1:]):
            if old["valid_to"] is None or timestamp(old["valid_to"]) > timestamp(new["valid_from"]):
                raise ValueError("Overlapping validity intervals")
            if new["supersedes"] != old["revision_id"]:
                raise ValueError("Nonlinear revision chain")
    return by_id


def abstention() -> dict:
    return {"current": None, "replaced": None, "source": {"uri": None, "kind": None}}


def answer(records: list[dict], query: dict, lookup: dict[str, dict]) -> dict:
    """Select current only from retrieved records; predecessor lookup is explicit."""
    at = timestamp(query["at"])
    current = [item for item in records if item["fact_id"] == query["fact_id"]
               and timestamp(item["valid_from"]) <= at
               and (item["valid_to"] is None or at < timestamp(item["valid_to"]))]
    if len(current) > 1:
        raise ValueError("Ambiguous current revision")
    if not current:
        return abstention()
    item = current[0]
    old = lookup.get(item["supersedes"])
    return {"current": item["value"], "replaced": old["value"] if old else None,
            "source": {key: item["source"][key] for key in ("uri", "kind")}}
