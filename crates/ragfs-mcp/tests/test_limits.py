"""Tests for MCP input caps, batch schema, timeout, and rate limit."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import TypeAdapter, ValidationError

from ragfs_mcp.server import (
    DEFAULT_MAX_BATCH_OPS,
    DEFAULT_MAX_GROUPS,
    DEFAULT_MAX_LIMIT,
    DEFAULT_MAX_OP_CONTENT_BYTES,
    DEFAULT_MAX_QUERY_LENGTH,
    DEFAULT_RATE_LIMIT,
    DEFAULT_RATE_WINDOW_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    BatchOperation,
    max_batch_ops,
    max_groups,
    max_limit,
    max_op_content_bytes,
    max_query_length,
    ragfs_batch_operations,
    ragfs_find_duplicates,
    ragfs_get_history,
    ragfs_list_indices,
    ragfs_propose_organization,
    ragfs_search,
    ragfs_similar,
    rate_limit,
    rate_window_seconds,
    reset_rate_limiter,
    run_limited,
    timeout_seconds,
)


def _error(result: str) -> str:
    data = json.loads(result)
    assert "error" in data, data
    return data["error"]


def _not_validation(result: str, *needles: str) -> None:
    data = json.loads(result)
    err = data.get("error", "")
    lowered = err.lower()
    for needle in needles:
        assert needle.lower() not in lowered, data


class TestDefaultCaps:
    def test_documented_defaults(self):
        assert DEFAULT_MAX_LIMIT == 100
        assert DEFAULT_MAX_QUERY_LENGTH == 2000
        assert DEFAULT_MAX_GROUPS == 10
        assert DEFAULT_MAX_BATCH_OPS == 10
        assert DEFAULT_MAX_OP_CONTENT_BYTES == 1_048_576
        assert DEFAULT_TIMEOUT_SECONDS == 30.0
        assert DEFAULT_RATE_LIMIT == 30
        assert DEFAULT_RATE_WINDOW_SECONDS == 60.0
        assert max_limit() == DEFAULT_MAX_LIMIT
        assert max_query_length() == DEFAULT_MAX_QUERY_LENGTH
        assert max_groups() == DEFAULT_MAX_GROUPS
        assert max_batch_ops() == DEFAULT_MAX_BATCH_OPS
        assert max_op_content_bytes() == DEFAULT_MAX_OP_CONTENT_BYTES
        assert timeout_seconds() == DEFAULT_TIMEOUT_SECONDS
        assert rate_limit() == DEFAULT_RATE_LIMIT
        assert rate_window_seconds() == DEFAULT_RATE_WINDOW_SECONDS


class TestLimitCap:
    @pytest.mark.asyncio
    async def test_search_rejects_over_limit(self):
        err = _error(await ragfs_search(query="auth", limit=DEFAULT_MAX_LIMIT + 1))
        assert "limit" in err.lower()

    @pytest.mark.asyncio
    async def test_search_accepts_at_limit(self):
        _not_validation(
            await ragfs_search(query="auth", limit=DEFAULT_MAX_LIMIT),
            "limit",
        )

    @pytest.mark.asyncio
    async def test_search_rejects_non_positive_limit(self):
        err = _error(await ragfs_search(query="auth", limit=0))
        assert "limit" in err.lower()

    @pytest.mark.asyncio
    async def test_similar_rejects_over_limit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        err = _error(
            await ragfs_similar(file_path="note.txt", limit=DEFAULT_MAX_LIMIT + 1)
        )
        assert "limit" in err.lower()

    @pytest.mark.asyncio
    async def test_history_rejects_over_limit(self):
        err = _error(await ragfs_get_history(limit=DEFAULT_MAX_LIMIT + 1))
        assert "limit" in err.lower()

    @pytest.mark.asyncio
    async def test_history_accepts_at_limit(self):
        _not_validation(await ragfs_get_history(limit=DEFAULT_MAX_LIMIT), "limit")


class TestQueryLengthCap:
    @pytest.mark.asyncio
    async def test_search_rejects_over_limit_query(self):
        err = _error(await ragfs_search(query="q" * (DEFAULT_MAX_QUERY_LENGTH + 1)))
        assert "query" in err.lower()

    @pytest.mark.asyncio
    async def test_search_accepts_at_limit_query(self):
        _not_validation(
            await ragfs_search(query="q" * DEFAULT_MAX_QUERY_LENGTH),
            "query",
        )


class TestMaxGroupsCap:
    @pytest.mark.asyncio
    async def test_rejects_over_limit(self):
        err = _error(
            await ragfs_propose_organization(
                scope="./", max_groups=DEFAULT_MAX_GROUPS + 1
            )
        )
        assert "max_groups" in err.lower()

    @pytest.mark.asyncio
    async def test_accepts_at_limit(self):
        _not_validation(
            await ragfs_propose_organization(scope="./", max_groups=DEFAULT_MAX_GROUPS),
            "max_groups",
        )


class TestThresholdRange:
    @pytest.mark.asyncio
    async def test_find_duplicates_rejects_above_one(self):
        err = _error(await ragfs_find_duplicates(threshold=1.01))
        assert "threshold" in err.lower()

    @pytest.mark.asyncio
    async def test_find_duplicates_accepts_one(self):
        _not_validation(await ragfs_find_duplicates(threshold=1.0), "threshold")

    @pytest.mark.asyncio
    async def test_propose_rejects_negative_similarity(self):
        err = _error(
            await ragfs_propose_organization(scope="./", similarity_threshold=-0.1)
        )
        assert "threshold" in err.lower()


class TestBatchCaps:
    @pytest.mark.asyncio
    async def test_rejects_too_many_operations(self):
        operations = [
            {"action": "mkdir", "target": f"d{i}"}
            for i in range(DEFAULT_MAX_BATCH_OPS + 1)
        ]
        err = _error(await ragfs_batch_operations(operations=operations, dry_run=True))
        assert "operations" in err.lower()

    @pytest.mark.asyncio
    async def test_accepts_at_limit_operations(self):
        operations = [
            {"action": "mkdir", "target": f"d{i}"} for i in range(DEFAULT_MAX_BATCH_OPS)
        ]
        _not_validation(
            await ragfs_batch_operations(operations=operations, dry_run=True),
            "operations",
        )

    @pytest.mark.asyncio
    async def test_rejects_oversize_content(self):
        content = "x" * (DEFAULT_MAX_OP_CONTENT_BYTES + 1)
        err = _error(
            await ragfs_batch_operations(
                operations=[{"action": "create", "target": "f.txt", "content": content}],
                dry_run=True,
            )
        )
        assert "content" in err.lower()

    @pytest.mark.asyncio
    async def test_accepts_at_limit_content(self):
        content = "x" * DEFAULT_MAX_OP_CONTENT_BYTES
        _not_validation(
            await ragfs_batch_operations(
                operations=[{"action": "create", "target": "f.txt", "content": content}],
                dry_run=True,
            ),
            "content",
        )


class TestEnvOverrides:
    def test_int_caps_read_env(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_MAX_LIMIT", "7")
        monkeypatch.setenv("RAGFS_MCP_MAX_QUERY_LENGTH", "12")
        monkeypatch.setenv("RAGFS_MCP_MAX_GROUPS", "4")
        monkeypatch.setenv("RAGFS_MCP_MAX_BATCH_OPS", "3")
        monkeypatch.setenv("RAGFS_MCP_MAX_OP_CONTENT_BYTES", "8")
        monkeypatch.setenv("RAGFS_MCP_TIMEOUT_SECONDS", "1.5")
        monkeypatch.setenv("RAGFS_MCP_RATE_LIMIT", "2")
        monkeypatch.setenv("RAGFS_MCP_RATE_WINDOW_SECONDS", "9")
        assert max_limit() == 7
        assert max_query_length() == 12
        assert max_groups() == 4
        assert max_batch_ops() == 3
        assert max_op_content_bytes() == 8
        assert timeout_seconds() == 1.5
        assert rate_limit() == 2
        assert rate_window_seconds() == 9.0

    @pytest.mark.asyncio
    async def test_query_length_override(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_MAX_QUERY_LENGTH", "5")
        err = _error(await ragfs_search(query="abcdef"))
        assert "query" in err.lower()
        _not_validation(await ragfs_search(query="abcde"), "query")

    @pytest.mark.asyncio
    async def test_limit_override(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_MAX_LIMIT", "3")
        err = _error(await ragfs_search(query="auth", limit=4))
        assert "limit" in err.lower()
        _not_validation(await ragfs_search(query="auth", limit=3), "limit")

    @pytest.mark.asyncio
    async def test_max_groups_override(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_MAX_GROUPS", "2")
        err = _error(await ragfs_propose_organization(scope="./", max_groups=3))
        assert "max_groups" in err.lower()
        _not_validation(
            await ragfs_propose_organization(scope="./", max_groups=2),
            "max_groups",
        )

    @pytest.mark.asyncio
    async def test_batch_ops_override(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_MAX_BATCH_OPS", "1")
        err = _error(
            await ragfs_batch_operations(
                operations=[
                    {"action": "mkdir", "target": "a"},
                    {"action": "mkdir", "target": "b"},
                ],
                dry_run=True,
            )
        )
        assert "operations" in err.lower()
        _not_validation(
            await ragfs_batch_operations(
                operations=[{"action": "mkdir", "target": "a"}],
                dry_run=True,
            ),
            "operations",
        )

    @pytest.mark.asyncio
    async def test_content_bytes_override(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_MAX_OP_CONTENT_BYTES", "4")
        err = _error(
            await ragfs_batch_operations(
                operations=[{"action": "create", "target": "f.txt", "content": "abcde"}],
                dry_run=True,
            )
        )
        assert "content" in err.lower()
        _not_validation(
            await ragfs_batch_operations(
                operations=[{"action": "create", "target": "f.txt", "content": "abcd"}],
                dry_run=True,
            ),
            "content",
        )


class TestBatchSchema:
    def test_rejects_unknown_action(self):
        with pytest.raises(ValidationError):
            TypeAdapter(BatchOperation).validate_python(
                {"action": "explode", "target": "x"}
            )

    def test_rejects_missing_target_on_delete(self):
        with pytest.raises(ValidationError):
            TypeAdapter(BatchOperation).validate_python({"action": "delete"})

    def test_rejects_missing_source_on_move(self):
        with pytest.raises(ValidationError):
            TypeAdapter(BatchOperation).validate_python(
                {"action": "move", "target": "dst"}
            )

    def test_accepts_known_actions(self):
        TypeAdapter(BatchOperation).validate_python(
            {"action": "create", "target": "f.txt", "content": "hi"}
        )
        TypeAdapter(BatchOperation).validate_python(
            {"action": "mkdir", "target": "dir"}
        )
        TypeAdapter(BatchOperation).validate_python(
            {"action": "write", "target": "f.txt", "content": "x", "append": True}
        )

    @pytest.mark.asyncio
    async def test_tool_rejects_unknown_action(self):
        err = _error(
            await ragfs_batch_operations(
                operations=[{"action": "invalid_action", "target": "/test/path"}],
                dry_run=True,
            )
        )
        assert "Unknown action" in err

    @pytest.mark.asyncio
    async def test_tool_rejects_missing_fields(self):
        err = _error(
            await ragfs_batch_operations(
                operations=[{"action": "move", "target": "dst"}],
                dry_run=True,
            )
        )
        assert "source" in err.lower() or "missing" in err.lower()


class TestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_triggers_on_slow_call(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_TIMEOUT_SECONDS", "0.05")

        async def slow_call() -> str:
            await asyncio.sleep(2)
            return json.dumps({"ok": True})

        result = json.loads(await run_limited(slow_call()))
        assert "timed out" in result["error"].lower()


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_rate_limit_triggers(self, monkeypatch):
        monkeypatch.setenv("RAGFS_MCP_RATE_LIMIT", "2")
        monkeypatch.setenv("RAGFS_MCP_RATE_WINDOW_SECONDS", "60")
        reset_rate_limiter()

        first = json.loads(await ragfs_list_indices())
        second = json.loads(await ragfs_list_indices())
        third = json.loads(await ragfs_list_indices())
        assert "error" not in first or "rate" not in first.get("error", "").lower()
        assert "error" not in second or "rate" not in second.get("error", "").lower()
        assert "rate" in third["error"].lower()
