"""Stable error codes (MCP-05) and stderr audit log (MCP-06)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import pytest

from ragfs_mcp.server import (
    DEFAULT_MAX_LIMIT,
    ErrorCode,
    ragfs_approve_plan,
    ragfs_batch_operations,
    ragfs_delete_to_trash,
    ragfs_list_indices,
    ragfs_list_trash,
    ragfs_restore_from_trash,
    ragfs_search,
    ragfs_similar,
    ragfs_undo,
    reset_rate_limiter,
    run_limited,
)


def _parse_audit_lines(stderr: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in stderr.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if {"timestamp", "tool", "args", "outcome", "duration_ms", "write"} <= set(
            data
        ):
            records.append(data)
    return records


def _assert_no_host_path(payload: Any, root: Path) -> None:
    blob = json.dumps(payload) if not isinstance(payload, str) else payload
    assert str(root) not in blob
    assert str(root.resolve()) not in blob
    assert os_realpath(root) not in blob


def os_realpath(path: Path) -> str:
    import os

    return os.path.realpath(str(path))


async def _error_search_missing_index(root: Path) -> str:
    return await ragfs_search(query="auth", index=str(root))


async def _error_similar_outside(root: Path) -> str:
    secret = root / "outside" / "secret.txt"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("secret")
    return await ragfs_similar(file_path=str(secret))


async def _error_delete_outside_index(root: Path) -> str:
    outsider = root / "outside_root"
    outsider.mkdir(exist_ok=True)
    return await ragfs_delete_to_trash(path="secret.txt", index=str(outsider))


async def _error_delete_writes_disabled(root: Path) -> str:
    return await ragfs_delete_to_trash(path="doc1.txt", index=str(root))


async def _error_batch_escape(root: Path) -> str:
    return await ragfs_batch_operations(
        operations=[
            {"action": "create", "target": "../jailbreak.txt", "content": "nope"}
        ],
        atomic=True,
        dry_run=False,
        index=str(root),
    )


async def _error_batch_outside_index(root: Path) -> str:
    outsider = root / "outside_root"
    outsider.mkdir(exist_ok=True)
    return await ragfs_batch_operations(
        operations=[{"action": "create", "target": "planted.txt", "content": "nope"}],
        dry_run=False,
        index=str(outsider),
    )


async def _error_list_trash_outside(root: Path) -> str:
    outsider = root / "outside_root"
    outsider.mkdir(exist_ok=True)
    return await ragfs_list_trash(index=str(outsider))


async def _error_restore_writes_disabled(root: Path) -> str:
    return await ragfs_restore_from_trash(undo_id="x", index=str(root))


async def _error_undo_writes_disabled(root: Path) -> str:
    return await ragfs_undo(undo_id="x", index=str(root))


async def _error_approve_writes_disabled(root: Path) -> str:
    return await ragfs_approve_plan(plan_id="x", index=str(root))


async def _error_search_limit(root: Path) -> str:
    return await ragfs_search(query="auth", index=str(root), limit=DEFAULT_MAX_LIMIT + 1)


ERROR_TOOL_CASES: list[
    tuple[str, Callable[[Path], Awaitable[str]], str]
] = [
    ("ragfs_search", _error_search_missing_index, ErrorCode.INDEX_NOT_FOUND),
    ("ragfs_similar", _error_similar_outside, ErrorCode.PATH_OUTSIDE_ROOT),
    ("ragfs_delete_to_trash", _error_delete_outside_index, ErrorCode.PATH_OUTSIDE_ROOT),
    ("ragfs_delete_to_trash", _error_delete_writes_disabled, ErrorCode.WRITES_DISABLED),
    ("ragfs_batch_operations", _error_batch_escape, ErrorCode.PATH_OUTSIDE_ROOT),
    (
        "ragfs_batch_operations",
        _error_batch_outside_index,
        ErrorCode.PATH_OUTSIDE_ROOT,
    ),
    ("ragfs_list_trash", _error_list_trash_outside, ErrorCode.PATH_OUTSIDE_ROOT),
    (
        "ragfs_restore_from_trash",
        _error_restore_writes_disabled,
        ErrorCode.WRITES_DISABLED,
    ),
    ("ragfs_undo", _error_undo_writes_disabled, ErrorCode.WRITES_DISABLED),
    ("ragfs_approve_plan", _error_approve_writes_disabled, ErrorCode.WRITES_DISABLED),
    ("ragfs_search", _error_search_limit, ErrorCode.LIMIT_EXCEEDED),
]


class TestErrorCodes:
    def test_codes_are_stable(self):
        assert ErrorCode.INDEX_NOT_FOUND == "INDEX_NOT_FOUND"
        assert ErrorCode.PATH_OUTSIDE_ROOT == "PATH_OUTSIDE_ROOT"
        assert ErrorCode.WRITES_DISABLED == "WRITES_DISABLED"
        assert ErrorCode.LIMIT_EXCEEDED == "LIMIT_EXCEEDED"
        assert ErrorCode.TIMEOUT == "TIMEOUT"
        assert ErrorCode.RATE_LIMITED == "RATE_LIMITED"
        assert ErrorCode.INTERNAL == "INTERNAL"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool_name", "producer", "expected_code"),
        ERROR_TOOL_CASES,
        ids=[
            "search_missing_index",
            "similar_outside_root",
            "delete_outside_index",
            "delete_writes_disabled",
            "batch_escape",
            "batch_outside_index",
            "list_trash_outside_index",
            "restore_writes_disabled",
            "undo_writes_disabled",
            "approve_writes_disabled",
            "search_limit_exceeded",
        ],
    )
    async def test_error_response_has_stable_code_and_no_host_path(
        self,
        tool_name: str,
        producer: Callable[[Path], Awaitable[str]],
        expected_code: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "doc1.txt").write_text("hello")
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(allowed))
        monkeypatch.delenv("RAGFS_ALLOWED_ROOTS", raising=False)
        monkeypatch.delenv("RAGFS_MCP_ALLOW_WRITES", raising=False)
        monkeypatch.setenv("RAGFS_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)

        if expected_code == ErrorCode.PATH_OUTSIDE_ROOT and tool_name in {
            "ragfs_delete_to_trash",
            "ragfs_batch_operations",
        }:
            monkeypatch.setenv("RAGFS_MCP_ALLOW_WRITES", "1")

        result = await producer(allowed if "outside" not in producer.__name__ else tmp_path)
        # Producers that jailbreak use tmp_path as the host root to leak-check.
        data = json.loads(result)
        assert data.get("code") == expected_code, data
        assert "error" in data
        _assert_no_host_path(data, tmp_path)
        _assert_no_host_path(data, allowed)
        assert "Traceback" not in data["error"]

    @pytest.mark.asyncio
    async def test_timeout_code(self, monkeypatch: pytest.MonkeyPatch):
        import asyncio

        monkeypatch.setenv("RAGFS_MCP_TIMEOUT_SECONDS", "0.05")

        async def slow_call() -> str:
            await asyncio.sleep(2)
            return json.dumps({"ok": True})

        data = json.loads(await run_limited(slow_call()))
        assert data["code"] == ErrorCode.TIMEOUT
        assert "timed out" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_rate_limited_code(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("RAGFS_MCP_RATE_LIMIT", "1")
        monkeypatch.setenv("RAGFS_MCP_RATE_WINDOW_SECONDS", "60")
        reset_rate_limiter()
        first = json.loads(await ragfs_list_indices())
        second = json.loads(await ragfs_list_indices())
        assert first.get("code") != ErrorCode.RATE_LIMITED
        assert second["code"] == ErrorCode.RATE_LIMITED
        assert "rate" in second["error"].lower()

    @pytest.mark.asyncio
    async def test_internal_error_strips_exception_and_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        from ragfs_mcp.server import _client_error

        leaked = tmp_path / "secret-dir" / "hidden.txt"
        exc = RuntimeError(f"OSError: failed opening {leaked}")
        data = json.loads(_client_error(exc))
        assert data["code"] == ErrorCode.INTERNAL
        assert str(tmp_path) not in json.dumps(data)
        assert "OSError" not in data["error"]
        assert "failed opening" not in data["error"]


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_audit_line_on_stderr_not_stdout(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.delenv("RAGFS_MCP_AUDIT_LOG", raising=False)
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        monkeypatch.delenv("RAGFS_DB_PATH", raising=False)
        monkeypatch.setenv("RAGFS_DATA_DIR", str(tmp_path / "data"))

        result = await ragfs_search(query="auth-query-text", index=str(tmp_path))
        captured = capsys.readouterr()
        records = _parse_audit_lines(captured.err)
        assert records, captured.err
        record = records[-1]
        assert record["tool"] == "ragfs_search"
        assert record["outcome"] in {"ok", ErrorCode.INDEX_NOT_FOUND}
        assert record["write"] is False
        assert isinstance(record["duration_ms"], int)
        assert "T" in record["timestamp"]
        assert "auth-query-text" not in json.dumps(record)
        assert record["args"]["query_len"] == len("auth-query-text")
        assert captured.out == ""
        assert "auth-query-text" not in captured.out
        data = json.loads(result)
        assert "error" in data or "results" in data

    @pytest.mark.asyncio
    async def test_batch_content_not_logged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.delenv("RAGFS_MCP_AUDIT_LOG", raising=False)
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        monkeypatch.delenv("RAGFS_MCP_ALLOW_WRITES", raising=False)

        marker = "SECRET_MARKER"
        await ragfs_batch_operations(
            operations=[
                {"action": "create", "target": "secret.txt", "content": marker}
            ],
            dry_run=True,
            index=str(tmp_path),
        )
        captured = capsys.readouterr()
        assert marker not in captured.err
        assert marker not in captured.out
        records = _parse_audit_lines(captured.err)
        assert records
        record = records[-1]
        assert record["tool"] == "ragfs_batch_operations"
        dumped = json.dumps(record)
        assert marker not in dumped
        assert "content" not in dumped

    @pytest.mark.asyncio
    async def test_path_logged_relative_to_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.delenv("RAGFS_MCP_AUDIT_LOG", raising=False)
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))
        monkeypatch.setenv("RAGFS_MCP_ALLOW_WRITES", "1")
        (tmp_path / "doc1.txt").write_text("hello")

        await ragfs_delete_to_trash(
            path=str(tmp_path / "doc1.txt"), index=str(tmp_path)
        )
        captured = capsys.readouterr()
        records = _parse_audit_lines(captured.err)
        assert records
        record = records[-1]
        assert record["tool"] == "ragfs_delete_to_trash"
        assert record["write"] is True
        assert record["args"]["path"] == "doc1.txt"
        assert record["args"]["index"] == "."
        assert str(tmp_path) not in json.dumps(record)
        assert os_realpath(tmp_path) not in json.dumps(record)

    @pytest.mark.asyncio
    async def test_outside_path_logged_as_sentinel(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        allowed = tmp_path / "allowed"
        outside = tmp_path / "outside"
        allowed.mkdir()
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("secret")
        monkeypatch.delenv("RAGFS_MCP_AUDIT_LOG", raising=False)
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(allowed))
        monkeypatch.delenv("RAGFS_ALLOWED_ROOTS", raising=False)

        await ragfs_similar(file_path=str(secret))
        captured = capsys.readouterr()
        records = _parse_audit_lines(captured.err)
        assert records
        record = records[-1]
        assert record["args"]["file_path"] == "<outside-root>"
        assert str(secret) not in json.dumps(record)
        assert os_realpath(tmp_path) not in json.dumps(record)

    @pytest.mark.asyncio
    async def test_audit_disabled_via_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.setenv("RAGFS_MCP_AUDIT_LOG", "0")
        monkeypatch.setenv("RAGFS_SOURCE_PATH", str(tmp_path))

        await ragfs_search(query="auth", index=str(tmp_path))
        captured = capsys.readouterr()
        assert _parse_audit_lines(captured.err) == []
        assert captured.out == ""
