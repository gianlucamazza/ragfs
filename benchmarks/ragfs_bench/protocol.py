"""Fail-closed protocol and content-pin validation."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def load_protocol(path: Path) -> tuple[dict, list[dict]]:
    protocol = tomllib.loads(path.read_text())
    if protocol.get("schema_version") != 1:
        raise ValueError("Unsupported protocol schema_version")
    if not isinstance(protocol.get("protocol_id"), str) or not protocol["protocol_id"]:
        raise ValueError("protocol_id is required")
    if type(protocol.get("seed")) is not int:
        raise ValueError("seed must be an integer")
    if protocol.get("dataset") != "versioned-facts-v0":
        raise ValueError("Only the frozen synthetic dataset is implemented")
    if protocol.get("judge", {}).get("enabled", False):
        raise ValueError("LLM judges are not enabled by this protocol")
    systems = protocol.get("systems", [])
    if not systems or len(set(systems)) != len(systems) or any(
        system not in {"bm25", "vector", "ragfs"} for system in systems
    ):
        raise ValueError("Unsupported or duplicate systems")
    k = protocol.get("query", {}).get("k")
    if type(k) is not int or k < 1:
        raise ValueError("query.k must be a positive integer")
    pin_path = path.parent / protocol["pins"]
    pins = tomllib.loads(pin_path.read_text()).get("pins", [])
    if not pins:
        raise ValueError("At least one content pin is required")
    names = set()
    for pin in pins:
        for field in ("name", "uri", "path", "sha256", "license"):
            if not isinstance(pin.get(field), str) or not pin[field]:
                raise ValueError(f"Missing pin field: {field}")
        if pin["name"] in names:
            raise ValueError("Duplicate pin name")
        names.add(pin["name"])
        revision = pin.get("git_commit") or pin.get("revision")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40,64}", revision):
            raise ValueError("Pins require an immutable full revision")
        if not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
            raise ValueError("Invalid sha256")
        artifact = (pin_path.parent / pin["path"]).resolve()
        if digest(artifact) != pin["sha256"]:
            raise ValueError(f"Pin mismatch: {pin['name']}")
        pin["resolved_path"] = str(artifact)
    required = {"facts", "queries", "scenario"}
    if not required <= names:
        raise ValueError("Missing synthetic fixture pins")
    return protocol, pins


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
