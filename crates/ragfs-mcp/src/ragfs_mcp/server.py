"""RAGFS MCP Server implementation.

This module provides the MCP server that exposes RAGFS semantic filesystem
capabilities to AI assistants like Claude.

RAGFS is NOT just a vector database - it's a FILESYSTEM for AI agents with:
- Safety Layer: Soft delete, audit history, undo support
- Semantic Operations: AI-powered file organization, similarity, deduplication
- Approval Workflow: Propose-Review-Apply pattern for safe AI agent operations

Tools exposed:

**Search & Discovery:**
- ragfs_search: Semantic search in indexed files
- ragfs_index_status: Get indexing status for a directory
- ragfs_similar: Find files similar to a given file
- ragfs_list_indices: List all available indices

**Safety Layer (Reversible Operations):**
- ragfs_delete_to_trash: Soft delete with undo capability
- ragfs_list_trash: View all files in trash
- ragfs_restore_from_trash: Restore deleted files
- ragfs_get_history: Get operation audit log
- ragfs_undo: Undo any reversible operation

**Semantic Operations (AI-Powered):**
- ragfs_find_duplicates: Find duplicate/near-duplicate files
- ragfs_analyze_cleanup: Analyze files for potential cleanup

**Approval Workflow (Propose-Review-Apply):**
- ragfs_propose_organization: Create organization plan (NOT executed until approved)
- ragfs_propose_cleanup: Create cleanup plan (NOT executed until approved)
- ragfs_list_pending_plans: List pending plans for review
- ragfs_get_plan: Get full plan details
- ragfs_approve_plan: Approve and execute a plan
- ragfs_reject_plan: Reject and discard a plan

**Structured Operations:**
- ragfs_batch_operations: Execute multiple operations atomically
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

import blake3
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, ValidationError

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

# Create the MCP server
mcp = MCPServer(
    "ragfs",
    instructions="Semantic search filesystem for AI assistants. Provides tools for searching, organizing, and managing files with AI-powered features.",
)

# Default paths (Linux XDG; override with RAGFS_DATA_DIR, same as the CLI)
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "ragfs"
DEFAULT_MODEL_PATH = DEFAULT_DATA_DIR / "models"

# 16 hex chars = CLI index id (blake3(canonical_source)[:16])
_INDEX_HASH_RE = re.compile(r"^[0-9a-f]{16}$", re.IGNORECASE)

# Sidecar under ``{indices}/{hex_id}/source`` recording that index's jail root.
INDEX_SOURCE_FILENAME = "source"

INDEX_NOT_ALLOWED_ERROR = "Index is not an allowed root"
FILE_PATH_NOT_ALLOWED_ERROR = "file_path is outside allowed roots"
WRITES_DISABLED_ERROR = (
    "Mutating MCP tools are disabled. Set RAGFS_MCP_ALLOW_WRITES=1 to enable writes."
)

# Caps (env-overridable). Defaults stay conservative and match existing CLI / MCP
# behavior rather than inventing new magnitudes.
DEFAULT_MAX_LIMIT = 100  # CLI `[query].max_limit` in crates/ragfs/src/config.rs
DEFAULT_MAX_QUERY_LENGTH = 2000  # ragfs_similar already embeds the first 2000 chars
DEFAULT_MAX_GROUPS = 10  # FUSE OrganizeRequest default_max_groups
DEFAULT_MAX_BATCH_OPS = 10  # docs/tests use 1–3 ops; 10 is a small agent-turn ceiling
DEFAULT_MAX_OP_CONTENT_BYTES = 1_048_576  # 1 MiB; index max_file_size is 50MB
DEFAULT_TIMEOUT_SECONDS = 30.0  # local gte-small search is seconds, not minutes
DEFAULT_RATE_LIMIT = 30  # stdio, one client; 30 calls / window stops embed loops
DEFAULT_RATE_WINDOW_SECONDS = 60.0


class ErrorCode:
    """Stable MCP tool error codes. Client payloads use these, never host paths."""

    INDEX_NOT_FOUND = "INDEX_NOT_FOUND"
    PATH_OUTSIDE_ROOT = "PATH_OUTSIDE_ROOT"
    WRITES_DISABLED = "WRITES_DISABLED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"
    PACKAGE_NOT_INSTALLED = "PACKAGE_NOT_INSTALLED"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    INVALID_INPUT = "INVALID_INPUT"
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"
    NOT_REVERSIBLE = "NOT_REVERSIBLE"
    EXTRACT_FAILED = "EXTRACT_FAILED"


class IndexNotAllowedError(ValueError):
    """Raised when ``index`` is not an allowlisted root or a known index source."""


class FilePathNotAllowedError(ValueError):
    """Raised when ``file_path`` resolves outside the allowlisted roots."""


LOG = logging.getLogger("ragfs_mcp")

_WRITE_TOOLS = frozenset(
    {
        "ragfs_delete_to_trash",
        "ragfs_restore_from_trash",
        "ragfs_undo",
        "ragfs_approve_plan",
        "ragfs_reject_plan",
        "ragfs_propose_organization",
        "ragfs_propose_cleanup",
        "ragfs_batch_operations",
    }
)
_PATH_ARG_KEYS = frozenset(
    {"path", "file_path", "index", "source", "target", "scope"}
)
_SAFE_ARG_KEYS = frozenset(
    {
        "limit",
        "hybrid",
        "threshold",
        "max_groups",
        "atomic",
        "dry_run",
        "plan_id",
        "undo_id",
        "strategy",
        "similarity_threshold",
        "append",
    }
)
_ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:)?(?:/[\w.+@~-]+)+")


def configure_logging() -> None:
    """Send Python logs to stderr (stdio stdout is the MCP channel)."""
    level_name = os.environ.get("RAGFS_MCP_LOG_LEVEL", "WARNING").upper()
    level = getattr(logging, level_name, logging.WARNING)
    if not LOG.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        LOG.addHandler(handler)
    LOG.setLevel(level)
    LOG.propagate = False


configure_logging()


def audit_log_enabled() -> bool:
    """Structured audit lines are on by default; ``RAGFS_MCP_AUDIT_LOG=0`` disables."""
    return os.environ.get("RAGFS_MCP_AUDIT_LOG", "1") != "0"


def _project_data_dir() -> Path:
    """CLI `ProjectDirs::from("", "", "ragfs").data_dir()` fallback."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ragfs"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        root = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return root / "ragfs" / "data"
    return Path.home() / ".local" / "share" / "ragfs"


def get_data_dir() -> Path:
    """Return the RAGFS data root, matching the CLI `data_dir()` lookup."""
    override = os.environ.get("RAGFS_DATA_DIR")
    if override:
        # CLI `data_dir()` uses PathBuf::from — no ~ expansion.
        return Path(override)
    # directories 5.0.1: XDG_DATA_HOME only on Linux-like OS, and only if absolute.
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg and sys.platform not in ("darwin", "win32") and os.path.isabs(xdg):
        return Path(xdg) / "ragfs"
    return _project_data_dir()


def get_indices_dir() -> Path:
    """Return the directory that holds per-source index folders."""
    return get_data_dir() / "indices"


def canonical_source(source: str) -> str:
    """Absolute, symlink-resolved path string (CLI `Path::canonicalize`)."""
    return str(Path(source).expanduser().resolve())


def index_id_for_source(source: str) -> str:
    """First 16 hex chars of blake3(canonical source path), same as the CLI.

    CLI (`crates/ragfs/src/main.rs` `get_db_path`):
        hash = blake3(source.to_string_lossy().as_bytes()); indices/{hash[:16]}/index.lance
    """
    digest = blake3.blake3(canonical_source(source).encode()).hexdigest()
    return digest[:16]


def get_db_path(index: str = "default") -> str:
    """Return the LanceDB path for an index, matching the CLI scheme.

    Layout: ``{data_dir}/indices/{blake3(canonical_source)[:16]}/index.lance``

    ``index`` may be:
    - a source directory (the same path passed to ``ragfs index``)
    - a 16-character hex id from ``ragfs_list_indices``
    - ``"default"`` / omitted: ``RAGFS_SOURCE_PATH`` or the current directory

    ``RAGFS_DB_PATH`` overrides this resolution entirely.
    """
    override = os.environ.get("RAGFS_DB_PATH")
    if override:
        return override

    if index and index != "default":
        expanded = Path(index).expanduser()
        if expanded.exists() or not _INDEX_HASH_RE.fullmatch(index):
            index_id = index_id_for_source(str(expanded))
        else:
            index_id = index.lower()
    else:
        source = os.environ.get("RAGFS_SOURCE_PATH") or os.getcwd()
        index_id = index_id_for_source(source)

    return str(get_indices_dir() / index_id / "index.lance")


def get_model_path() -> str:
    """Get the model path."""
    return os.environ.get("RAGFS_MODEL_PATH", str(DEFAULT_MODEL_PATH))


def _realpath(path: str) -> str:
    """Resolve ``path`` with ``os.path.realpath`` (expand ``~`` first)."""
    return os.path.realpath(os.path.expanduser(path))


def build_allowed_roots() -> frozenset[str]:
    """Build the allowlist of jail roots from process environment.

    Roots are ``RAGFS_SOURCE_PATH`` plus optional ``RAGFS_ALLOWED_ROOTS``
    (``os.pathsep``-separated). Each entry is resolved with ``realpath``.
    """
    roots: list[str] = []
    source = os.environ.get("RAGFS_SOURCE_PATH")
    if source and source.strip():
        roots.append(_realpath(source))
    extra = os.environ.get("RAGFS_ALLOWED_ROOTS", "")
    if extra:
        for part in extra.split(os.pathsep):
            part = part.strip()
            if part:
                roots.append(_realpath(part))
    return frozenset(roots)


def _is_under_root(resolved: str, root: str) -> bool:
    """Return True if ``resolved`` is ``root`` or a descendant."""
    return Path(resolved).is_relative_to(root)


def resolve_file_under_allowed_roots(file_path: str) -> str:
    """Resolve ``file_path`` with ``realpath`` and require an allowlisted root.

    Uses :func:`build_allowed_roots` (``RAGFS_SOURCE_PATH`` plus
    ``RAGFS_ALLOWED_ROOTS``). Symlinks are followed. The raised error
    does not include the resolved absolute path.
    """
    resolved = _realpath(file_path)
    for root in build_allowed_roots():
        if _is_under_root(resolved, root):
            return resolved
    raise FilePathNotAllowedError(FILE_PATH_NOT_ALLOWED_ERROR)


def writes_allowed() -> bool:
    """Mutating tools run only when ``RAGFS_MCP_ALLOW_WRITES`` is ``1``."""
    return os.environ.get("RAGFS_MCP_ALLOW_WRITES") == "1"


def recorded_source_for_index_id(index_id: str) -> str | None:
    """Return the recorded jail root for a 16-hex index id, if any.

    Looks up ``{indices}/{id}/source``, then allowlisted roots whose CLI
    index id matches. Does not fall back to ``RAGFS_SOURCE_PATH`` or cwd
    unless that path is the recorded/hashed source for this id.
    """
    index_id = index_id.lower()
    sidecar = get_indices_dir() / index_id / INDEX_SOURCE_FILENAME
    if sidecar.is_file():
        text = sidecar.read_text(encoding="utf-8").strip()
        if text:
            return _realpath(text)
    for root in build_allowed_roots():
        if index_id_for_source(root) == index_id:
            return root
    return None


def _recorded_source_paths() -> set[str]:
    """Realpaths recorded in index source sidecars."""
    paths: set[str] = set()
    indices_dir = get_indices_dir()
    if not indices_dir.is_dir():
        return paths
    for item in indices_dir.iterdir():
        if not item.is_dir() or not _INDEX_HASH_RE.fullmatch(item.name):
            continue
        sidecar = item / INDEX_SOURCE_FILENAME
        if sidecar.is_file():
            text = sidecar.read_text(encoding="utf-8").strip()
            if text:
                paths.add(_realpath(text))
    return paths


def _sanitize_client_text(text: str) -> str:
    """Strip absolute host paths from a client-facing error message."""
    if not text:
        return text
    for root in sorted(build_allowed_roots(), key=len, reverse=True):
        if root:
            text = text.replace(root, "<root>")
    home = str(Path.home())
    if home:
        text = text.replace(home, "<home>")
    text = _ABS_PATH_RE.sub("<path>", text)
    text = re.sub(r":\s*(<path>|<root>|<home>)\s*$", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _json_error(code: str, message: str, **extra: Any) -> str:
    payload: dict[str, Any] = {
        "error": _sanitize_client_text(message),
        "code": code,
    }
    payload.update(extra)
    return json.dumps(payload)


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an exception to a stable code and a path-free short message."""
    if isinstance(exc, FilePathNotAllowedError):
        return ErrorCode.PATH_OUTSIDE_ROOT, FILE_PATH_NOT_ALLOWED_ERROR
    if isinstance(exc, IndexNotAllowedError):
        return ErrorCode.PATH_OUTSIDE_ROOT, INDEX_NOT_ALLOWED_ERROR
    if isinstance(exc, ImportError):
        return ErrorCode.PACKAGE_NOT_INSTALLED, "ragfs package not installed"
    message = str(exc)
    lowered = message.lower()
    if "escapes" in lowered:
        return ErrorCode.PATH_OUTSIDE_ROOT, "Path escapes source root"
    if "not an allowed root" in lowered:
        return ErrorCode.PATH_OUTSIDE_ROOT, INDEX_NOT_ALLOWED_ERROR
    if "outside allowed" in lowered:
        return ErrorCode.PATH_OUTSIDE_ROOT, FILE_PATH_NOT_ALLOWED_ERROR
    return ErrorCode.INTERNAL, "Internal error"


def _client_error(exc: BaseException) -> str:
    """JSON error for the client; full detail goes to stderr at debug only."""
    code, message = classify_exception(exc)
    LOG.debug("MCP tool error %s: %s", code, exc, exc_info=True)
    return _json_error(code, message)


def _package_missing_error(message: str | None = None) -> str:
    return _json_error(
        ErrorCode.PACKAGE_NOT_INSTALLED,
        message or "ragfs package not installed",
    )


def redact_path(value: str | None) -> str | None:
    """Log a path relative to an allowlisted root, or ``<outside-root>``."""
    if value is None:
        return None
    if value in ("", "default") or _INDEX_HASH_RE.fullmatch(value):
        return value
    candidates = [value]
    if not os.path.isabs(os.path.expanduser(value)):
        for root in build_allowed_roots():
            candidates.append(os.path.join(root, value))
    for candidate in candidates:
        try:
            resolved = _realpath(candidate)
        except OSError:
            continue
        for root in build_allowed_roots():
            if _is_under_root(resolved, root):
                rel = os.path.relpath(resolved, root)
                return "." if rel == "." else rel.replace(os.sep, "/")
    return "<outside-root>"


def _redact_operation(op: Any) -> dict[str, Any]:
    if hasattr(op, "model_dump"):
        data = op.model_dump()
    elif isinstance(op, dict):
        data = op
    else:
        return {"action": "<unknown>"}
    redacted: dict[str, Any] = {"action": data.get("action")}
    for key in ("source", "target"):
        if key in data and data[key] is not None:
            redacted[key] = redact_path(str(data[key]))
    return redacted


def redact_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Summarize tool args: no contents, query text, env, or absolute paths."""
    out: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in {"content", "self", "cls"}:
            continue
        if key == "query":
            out["query_len"] = len(value) if isinstance(value, str) else 0
            continue
        if key == "operations" and isinstance(value, list):
            out["operations"] = [_redact_operation(op) for op in value]
            out["op_count"] = len(value)
            continue
        if key in _PATH_ARG_KEYS and isinstance(value, str):
            out[key] = redact_path(value)
            continue
        if key in _SAFE_ARG_KEYS:
            out[key] = value
    return out


def _bound_tool_args(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except TypeError:
        return dict(kwargs)


def _is_write_call(tool: str, kwargs: dict[str, Any]) -> bool:
    if tool == "ragfs_batch_operations" and kwargs.get("dry_run"):
        return False
    return tool in _WRITE_TOOLS


def _outcome_from_result(result: str) -> str:
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return ErrorCode.INTERNAL
    if isinstance(data, dict) and "error" in data and data.get("success") is not True:
        code = data.get("code")
        if isinstance(code, str) and code:
            return code
        return ErrorCode.INTERNAL
    return "ok"


def emit_audit_log(
    *,
    tool: str,
    args: dict[str, Any],
    outcome: str,
    duration_ms: int,
    write: bool,
) -> None:
    """One JSON line on stderr. Never write to stdout (MCP stdio)."""
    if not audit_log_enabled():
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tool": tool,
        "args": redact_args(args),
        "outcome": outcome,
        "duration_ms": duration_ms,
        "write": write,
    }
    print(json.dumps(record), file=sys.stderr, flush=True)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw, 10)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


def max_limit() -> int:
    return _env_int("RAGFS_MCP_MAX_LIMIT", DEFAULT_MAX_LIMIT)


def max_query_length() -> int:
    return _env_int("RAGFS_MCP_MAX_QUERY_LENGTH", DEFAULT_MAX_QUERY_LENGTH)


def max_groups() -> int:
    return _env_int("RAGFS_MCP_MAX_GROUPS", DEFAULT_MAX_GROUPS)


def max_batch_ops() -> int:
    return _env_int("RAGFS_MCP_MAX_BATCH_OPS", DEFAULT_MAX_BATCH_OPS)


def max_op_content_bytes() -> int:
    return _env_int("RAGFS_MCP_MAX_OP_CONTENT_BYTES", DEFAULT_MAX_OP_CONTENT_BYTES)


def timeout_seconds() -> float:
    return _env_float("RAGFS_MCP_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)


def rate_limit() -> int:
    return _env_int("RAGFS_MCP_RATE_LIMIT", DEFAULT_RATE_LIMIT, minimum=0)


def rate_window_seconds() -> float:
    return _env_float("RAGFS_MCP_RATE_WINDOW_SECONDS", DEFAULT_RATE_WINDOW_SECONDS)


class _RateLimiter:
    def __init__(self) -> None:
        self._calls: list[float] = []

    def reset(self) -> None:
        self._calls.clear()

    def check(self) -> str | None:
        allowed = rate_limit()
        if allowed <= 0:
            return None
        window = rate_window_seconds()
        now = time.monotonic()
        self._calls = [t for t in self._calls if now - t < window]
        if len(self._calls) >= allowed:
            return _json_error(
                ErrorCode.RATE_LIMITED,
                f"Rate limit exceeded: {allowed} calls per {window:g} seconds",
            )
        self._calls.append(now)
        return None


_RATE_LIMITER = _RateLimiter()


def reset_rate_limiter() -> None:
    """Clear the per-process tool-call window (tests)."""
    _RATE_LIMITER.reset()


async def _await_with_timeout(coro: Awaitable[str]) -> str:
    timeout = timeout_seconds()
    try:
        if timeout <= 0:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return _json_error(
            ErrorCode.TIMEOUT, f"Tool call timed out after {timeout} seconds"
        )


async def run_limited(coro: Awaitable[str]) -> str:
    """Apply the per-process rate limit and wall-clock timeout to one call."""
    limited = _RATE_LIMITER.check()
    if limited:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return limited
    return await _await_with_timeout(coro)


def with_limits(func: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """Wrap a tool so every invocation is rate-limited, timed, and audited."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        started = time.perf_counter()
        outcome = ErrorCode.INTERNAL
        bound_args = _bound_tool_args(func, args, kwargs)
        try:
            limited = _RATE_LIMITER.check()
            if limited:
                result = limited
            else:
                result = await _await_with_timeout(func(*args, **kwargs))
            outcome = _outcome_from_result(result)
            return result
        finally:
            emit_audit_log(
                tool=func.__name__,
                args=bound_args,
                outcome=outcome,
                duration_ms=int(round((time.perf_counter() - started) * 1000)),
                write=_is_write_call(func.__name__, bound_args),
            )

    return wrapper


def _validate_limit(limit: int) -> str | None:
    if limit < 1:
        return _json_error(ErrorCode.LIMIT_EXCEEDED, "limit must be >= 1")
    cap = max_limit()
    if limit > cap:
        return _json_error(
            ErrorCode.LIMIT_EXCEEDED, f"limit {limit} exceeds maximum of {cap}"
        )
    return None


def _validate_query(query: str) -> str | None:
    cap = max_query_length()
    if len(query) > cap:
        return _json_error(
            ErrorCode.LIMIT_EXCEEDED, f"query exceeds maximum length of {cap}"
        )
    return None


def _validate_max_groups(value: int) -> str | None:
    if value < 1:
        return _json_error(ErrorCode.LIMIT_EXCEEDED, "max_groups must be >= 1")
    cap = max_groups()
    if value > cap:
        return _json_error(
            ErrorCode.LIMIT_EXCEEDED, f"max_groups {value} exceeds maximum of {cap}"
        )
    return None


def _validate_threshold(name: str, value: float) -> str | None:
    if value < 0.0 or value > 1.0:
        return _json_error(ErrorCode.INVALID_INPUT, f"{name} must be between 0 and 1")
    return None


class _OpBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateOp(_OpBase):
    action: Literal["create"]
    target: str
    content: str = ""


class WriteOp(_OpBase):
    action: Literal["write"]
    target: str
    content: str = ""
    append: bool = False


class MoveOp(_OpBase):
    action: Literal["move"]
    source: str
    target: str


class CopyOp(_OpBase):
    action: Literal["copy"]
    source: str
    target: str


class DeleteOp(_OpBase):
    action: Literal["delete"]
    target: str


class MkdirOp(_OpBase):
    action: Literal["mkdir"]
    target: str


class SymlinkOp(_OpBase):
    action: Literal["symlink"]
    source: str
    target: str


BatchOperation = Annotated[
    CreateOp | MoveOp | CopyOp | DeleteOp | MkdirOp | WriteOp | SymlinkOp,
    Field(discriminator="action"),
]

_ACTION_MODELS: dict[str, type[_OpBase]] = {
    "create": CreateOp,
    "move": MoveOp,
    "copy": CopyOp,
    "delete": DeleteOp,
    "mkdir": MkdirOp,
    "write": WriteOp,
    "symlink": SymlinkOp,
}


def _batch_validation_message(action: str, exc: ValidationError) -> str:
    for err in exc.errors():
        loc = err.get("loc") or ()
        if err.get("type") == "missing":
            field = loc[-1] if loc else "field"
            return f"missing required field: {field}"
    return f"Invalid {action} operation: {exc}"


def parse_batch_operations(
    operations: list[Any],
) -> tuple[list[BatchOperation] | None, str | None]:
    cap = max_batch_ops()
    if len(operations) > cap:
        return None, _json_error(
            ErrorCode.LIMIT_EXCEEDED, f"batch exceeds maximum of {cap} operations"
        )
    content_cap = max_op_content_bytes()
    parsed: list[BatchOperation] = []
    for i, op in enumerate(operations):
        if isinstance(op, _OpBase):
            data = op.model_dump()
        elif isinstance(op, dict):
            data = op
        else:
            return None, _json_error(
                ErrorCode.INVALID_INPUT, f"operations[{i}] must be an object"
            )
        action = data.get("action", "")
        model_cls = _ACTION_MODELS.get(action)
        if model_cls is None:
            return None, _json_error(
                ErrorCode.INVALID_INPUT, f"Unknown action: {action}"
            )
        try:
            model = model_cls.model_validate(data)
        except ValidationError as exc:
            return None, _json_error(
                ErrorCode.INVALID_INPUT, _batch_validation_message(action, exc)
            )
        content = getattr(model, "content", None)
        if isinstance(content, str):
            size = len(content.encode("utf-8"))
            if size > content_cap:
                return None, _json_error(
                    ErrorCode.LIMIT_EXCEEDED,
                    f"operation content exceeds maximum of {content_cap} bytes",
                )
        parsed.append(model)
    return parsed, None


def _tool_annotations(
    *,
    title: str,
    read_only_hint: bool,
    destructive_hint: bool,
    idempotent_hint: bool,
    open_world_hint: bool = False,
) -> ToolAnnotations:
    """Build MCP ToolAnnotations (2025-11-25 schema#toolannotations).

    These values are client UX hints only — not permissions. Authorization is
    enforced by the RAGFS_MCP_ALLOW_WRITES gate and the root allowlist.
    """
    return ToolAnnotations(
        title=title,
        readOnlyHint=read_only_hint,
        destructiveHint=destructive_hint,
        idempotentHint=idempotent_hint,
        openWorldHint=open_world_hint,
    )


@mcp.tool(
    annotations=_tool_annotations(
        title="Semantic Search",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_search(
    query: str,
    index: str = "default",
    limit: int = 10,
    hybrid: bool = True,
) -> str:
    """Search for documents using semantic search.

    Performs vector similarity search combined with full-text search (hybrid)
    to find relevant content in indexed files.

    Args:
        query: The search query (natural language).
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.
        limit: Maximum number of results to return (default: 10).
            Values outside 1..RAGFS_MCP_MAX_LIMIT are rejected (not clamped).
        hybrid: Enable hybrid search combining vector and full-text (default: True).

    Returns:
        JSON string with search results including file paths, content snippets, and scores.
    """
    invalid = _validate_query(query) or _validate_limit(limit)
    if invalid:
        return invalid

    import json

    db_path = get_db_path(index)

    if not Path(db_path).exists():
        return _json_error(
            ErrorCode.INDEX_NOT_FOUND,
            "Index not found",
            hint="Index a directory first using the ragfs CLI: ragfs index /path/to/dir",
        )

    try:
        from ragfs import RagfsRetriever
    except ImportError:
        return _package_missing_error(
            "ragfs package not installed. Install from source (not PyPI): pip install ./crates/ragfs-python"
        )

    try:
        retriever = RagfsRetriever(
            db_path=db_path,
            model_path=get_model_path(),
            hybrid=hybrid,
            k=limit,
        )
        await retriever.init()

        results = await retriever.search(query, hybrid=hybrid, k=limit)

        output = []
        for result in results:
            output.append({
                "file_path": result.document.metadata.get("file_path", "unknown"),
                "content": result.document.page_content[:500],  # Truncate for readability
                "score": round(result.score, 4),
                "modality": result.document.metadata.get("modality", "text"),
                "start_ms": int(result.document.metadata["start_ms"]) if "start_ms" in result.document.metadata else None,
                "end_ms": int(result.document.metadata["end_ms"]) if "end_ms" in result.document.metadata else None,
                "metadata": result.document.metadata,
            })

        return json.dumps({
            "query": query,
            "index": index,
            "count": len(output),
            "results": output,
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Index Status",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_index_status(index: str = "default") -> str:
    """Get the status of an index.

    Returns information about the indexed files, chunk count, and last update time.

    Args:
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON string with index statistics.
    """
    import json

    db_path = Path(get_db_path(index))

    if not db_path.exists():
        return json.dumps({
            "exists": False,
            "index": index,
            "path": str(db_path),
            "hint": "Index a directory using: ragfs index /path/to/dir",
        })

    # db_path is the Lance dataset (.../indices/{16hex}/index.lance)
    dataset = db_path if db_path.is_dir() else db_path.parent
    lance_files = list(dataset.glob("*.lance")) + list(dataset.glob("**/data/*.lance"))
    manifest_file = dataset / "_latest.manifest"
    has_dataset_files = any(dataset.iterdir()) if dataset.is_dir() else False

    status = {
        "exists": True,
        "index": index,
        "path": str(db_path),
        "has_data": db_path.exists() and (has_dataset_files or len(lance_files) > 0 or manifest_file.exists()),
    }

    if dataset.is_dir():
        total_size = sum(f.stat().st_size for f in dataset.rglob("*") if f.is_file())
        status["size_bytes"] = total_size
        status["size_mb"] = round(total_size / (1024 * 1024), 2)

        files = [f for f in dataset.rglob("*") if f.is_file()]
        if files:
            latest = max(f.stat().st_mtime for f in files)
            status["last_modified"] = datetime.fromtimestamp(
                latest, tz=timezone.utc
            ).isoformat()

    return json.dumps(status, indent=2)


@mcp.tool(
    annotations=_tool_annotations(
        title="Find Similar Files",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_similar(
    file_path: str,
    index: str = "default",
    limit: int = 5,
) -> str:
    """Find files similar to a given file.

    Uses the indexed embeddings to find semantically similar files.

    Args:
        file_path: Path to the source file to find similar files for.
            Must resolve (realpath, including symlinks) inside an
            allowlisted root (RAGFS_SOURCE_PATH or RAGFS_ALLOWED_ROOTS).
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.
        limit: Maximum number of similar files to return (default: 5).
            Values outside 1..RAGFS_MCP_MAX_LIMIT are rejected (not clamped).

    Returns:
        JSON string with similar files and their similarity scores.
    """
    import json

    invalid = _validate_limit(limit)
    if invalid:
        return invalid

    try:
        source_resolved = resolve_file_under_allowed_roots(file_path)
    except FilePathNotAllowedError:
        return _json_error(ErrorCode.PATH_OUTSIDE_ROOT, FILE_PATH_NOT_ALLOWED_ERROR)

    source = Path(source_resolved)
    if not source.exists():
        return _json_error(ErrorCode.FILE_NOT_FOUND, "File not found")

    try:
        from ragfs import RagfsDocumentLoader, RagfsRetriever
    except ImportError:
        return _package_missing_error()

    db_path = get_db_path(index)

    if not Path(db_path).exists():
        return _json_error(ErrorCode.INDEX_NOT_FOUND, "Index not found")

    try:
        # Load and extract content from the source file
        loader = RagfsDocumentLoader()
        await loader.init()
        docs = await loader.load(str(source))

        if not docs:
            return _json_error(
                ErrorCode.EXTRACT_FAILED, "Could not extract content from file"
            )

        # Use the content as query
        content = docs[0].page_content[:2000]  # Limit query size

        # Search for similar
        retriever = RagfsRetriever(
            db_path=db_path,
            model_path=get_model_path(),
            hybrid=False,  # Pure vector search for similarity
            k=limit + 1,  # +1 to exclude self
        )
        await retriever.init()

        results = await retriever.search(content, hybrid=False, k=limit + 1)

        # Filter out the source file and format results
        similar = []
        source_abs = source.resolve()
        for result in results:
            result_path = result.document.metadata.get("file_path", "")
            if Path(result_path).resolve() != source_abs:
                similar.append({
                    "file_path": result_path,
                    "similarity": round(result.score, 4),
                    "preview": result.document.page_content[:200],
                })
            if len(similar) >= limit:
                break

        return json.dumps({
            "source_file": str(source),
            "similar_files": similar,
            "count": len(similar),
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="List Indices",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_list_indices() -> str:
    """List all available RAGFS indices.

    Scans the default indices directory for available indices.

    Returns:
        JSON string with list of available indices.
    """
    indices_dir = get_indices_dir()

    if not indices_dir.exists():
        return json.dumps({
            "indices": [],
            "hint": "No indices found. Create one with: ragfs index /path/to/dir",
        })

    indices = []
    for item in indices_dir.iterdir():
        if item.is_dir():
            dataset = item / "index.lance"
            scan_root = dataset if dataset.exists() else item
            lance_files = list(item.glob("*.lance")) + list(item.glob("**/data/*.lance"))
            if dataset.exists() or lance_files or (item / "_latest.manifest").exists():
                total_size = sum(f.stat().st_size for f in scan_root.rglob("*") if f.is_file())
                latest_mtime = max(
                    (f.stat().st_mtime for f in scan_root.rglob("*") if f.is_file()),
                    default=0,
                )
                indices.append({
                    "name": item.name,
                    "path": str(dataset if dataset.exists() else item),
                    "size_mb": round(total_size / (1024 * 1024), 2),
                    "last_modified": datetime.fromtimestamp(
                        latest_mtime, tz=timezone.utc
                    ).isoformat() if latest_mtime else None,
                })

    return json.dumps({
        "indices_dir": str(indices_dir),
        "count": len(indices),
        "indices": indices,
    }, indent=2)


# =============================================================================
# SAFETY LAYER TOOLS - Reversible Operations
# =============================================================================


def get_source_path(index: str = "default") -> str:
    """Return the jail root for safety/semantic operations.

    The root must be in the allowlist (``RAGFS_SOURCE_PATH`` plus
    ``RAGFS_ALLOWED_ROOTS``) or the recorded source of a known index.
    Hex index ids map to that recorded source and never fall back to
    ``RAGFS_SOURCE_PATH`` or the current working directory.
    """
    allowed = build_allowed_roots()
    recorded_paths = _recorded_source_paths()

    if index and index != "default":
        if _INDEX_HASH_RE.fullmatch(index):
            source = recorded_source_for_index_id(index)
            if source is None:
                raise IndexNotAllowedError(f"{INDEX_NOT_ALLOWED_ERROR}: {index}")
            return source
        resolved = _realpath(index)
        if resolved in allowed or resolved in recorded_paths:
            return resolved
        raise IndexNotAllowedError(f"{INDEX_NOT_ALLOWED_ERROR}: {index}")

    source = os.environ.get("RAGFS_SOURCE_PATH")
    if source and source.strip():
        resolved = _realpath(source)
        if resolved in allowed:
            return resolved
    raise IndexNotAllowedError(f"{INDEX_NOT_ALLOWED_ERROR}: {index}")


def _resolve_source(index: str) -> str | None:
    """Return a JSON error payload if ``index`` is not an allowed root."""
    try:
        get_source_path(index)
    except IndexNotAllowedError as exc:
        LOG.debug("index not allowed: %s", exc)
        return _json_error(ErrorCode.PATH_OUTSIDE_ROOT, INDEX_NOT_ALLOWED_ERROR)
    return None


def _deny_writes() -> str | None:
    if writes_allowed():
        return None
    return _json_error(ErrorCode.WRITES_DISABLED, WRITES_DISABLED_ERROR)


def _resolve_user_path(source_root: str, user_path: str) -> str:
    """Resolve ``user_path`` the same way the FUSE jail does (relative to source)."""
    expanded = os.path.expanduser(user_path)
    if os.path.isabs(expanded):
        return _realpath(expanded)
    return _realpath(os.path.join(source_root, expanded))


def _ensure_under_source(source_root: str, user_path: str) -> str | None:
    """Reject a user path that escapes the jail root (no host path in the reply)."""
    resolved = _resolve_user_path(source_root, user_path)
    if _is_under_root(resolved, source_root):
        return None
    LOG.debug("path escapes source root: %s (root=%s)", resolved, source_root)
    return _json_error(
        ErrorCode.PATH_OUTSIDE_ROOT,
        "Path escapes source root",
        success=False,
    )


@mcp.tool(
    annotations=_tool_annotations(
        title="Delete to Trash",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_delete_to_trash(
    path: str,
    index: str = "default",
) -> str:
    """Safely delete a file to trash (can be undone).

    Unlike permanent deletion, this moves the file to RAGFS trash
    and returns an undo_id that can be used to restore it.

    This is a core RAGFS safety feature for AI agent operations.

    Args:
        path: File path to delete (absolute or relative to source).
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with undo_id for restoration, or error message.
    """
    err = _resolve_source(index)
    if err:
        return err
    denied = _deny_writes()
    if denied:
        return denied

    source_path = get_source_path(index)
    escaped = _ensure_under_source(source_path, path)
    if escaped:
        return escaped

    try:
        from ragfs import RagfsSafetyManager
    except ImportError:
        return _package_missing_error()

    db_path = get_db_path(index)

    try:
        safety = RagfsSafetyManager(source_path, db_path)
        trash_entry = await safety.delete_to_trash(path)

        return json.dumps({
            "success": True,
            "message": f"File moved to trash: {path}",
            "undo_id": trash_entry.id,
            "original_path": trash_entry.original_path,
            "deleted_at": trash_entry.deleted_at,
            "hint": f"Use ragfs_restore_from_trash with undo_id='{trash_entry.id}' to restore",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="List Trash",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_list_trash(index: str = "default") -> str:
    """List all files in trash that can be restored.

    Shows all soft-deleted files with their undo IDs.

    Args:
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with list of trash entries.
    """
    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import RagfsSafetyManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        safety = RagfsSafetyManager(source_path, db_path)
        entries = await safety.list_trash()

        trash_list = []
        for entry in entries:
            trash_list.append({
                "undo_id": entry.id,
                "original_path": entry.original_path,
                "deleted_at": entry.deleted_at,
                "size_bytes": entry.size_bytes,
            })

        return json.dumps({
            "count": len(trash_list),
            "entries": trash_list,
            "hint": "Use ragfs_restore_from_trash to restore any file",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Restore from Trash",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_restore_from_trash(
    undo_id: str,
    index: str = "default",
) -> str:
    """Restore a file from trash using its undo_id.

    Undoes a previous ragfs_delete_to_trash operation.

    Args:
        undo_id: The undo_id returned by ragfs_delete_to_trash.
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with restored file path, or error message.
    """
    err = _resolve_source(index)
    if err:
        return err
    denied = _deny_writes()
    if denied:
        return denied

    try:
        from ragfs import RagfsSafetyManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        safety = RagfsSafetyManager(source_path, db_path)
        restored_path = await safety.restore_from_trash(undo_id)

        return json.dumps({
            "success": True,
            "message": "File restored from trash",
            "restored_path": restored_path,
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Operation History",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_get_history(
    limit: int = 50,
    path: str | None = None,
    index: str = "default",
) -> str:
    """Get operation history for audit trail.

    Shows all tracked operations with their undo IDs (if reversible).

    Args:
        limit: Maximum number of entries to return (default: 50).
            Values outside 1..RAGFS_MCP_MAX_LIMIT are rejected (not clamped).
        path: Optional filter by file path.
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with operation history entries.
    """
    invalid = _validate_limit(limit)
    if invalid:
        return invalid

    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import RagfsSafetyManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        safety = RagfsSafetyManager(source_path, db_path)

        if path:
            entries = await safety.get_file_history(path)
        else:
            entries = safety.get_history(limit=limit)

        history_list = []
        for entry in entries:
            history_list.append({
                "id": entry.id,
                "timestamp": entry.timestamp,
                "operation_type": entry.operation.operation_type,
                "path": entry.operation.path,
                "reversible": entry.reversible,
            })

        return json.dumps({
            "count": len(history_list),
            "entries": history_list,
            "hint": "Use ragfs_undo with the entry id to undo reversible operations",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Undo Operation",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_undo(
    undo_id: str,
    index: str = "default",
) -> str:
    """Undo a previous operation by its ID.

    Works for any reversible operation tracked in history.

    Args:
        undo_id: The operation ID from history.
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with undo result, or error message.
    """
    err = _resolve_source(index)
    if err:
        return err
    denied = _deny_writes()
    if denied:
        return denied

    try:
        from ragfs import RagfsSafetyManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        safety = RagfsSafetyManager(source_path, db_path)

        # Check if operation can be undone
        if not safety.can_undo(undo_id):
            return _json_error(
                ErrorCode.NOT_REVERSIBLE,
                "Operation cannot be undone (not reversible or already undone)",
                success=False,
            )

        result = await safety.undo(undo_id)

        return json.dumps({
            "success": True,
            "message": result,
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


# =============================================================================
# SEMANTIC OPERATIONS TOOLS - AI-Powered Analysis
# =============================================================================


@mcp.tool(
    annotations=_tool_annotations(
        title="Find Duplicates",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_find_duplicates(
    threshold: float = 0.95,
    index: str = "default",
) -> str:
    """Find duplicate or near-duplicate files.

    Uses semantic embeddings to identify files with very similar content,
    even if they have different names or minor text differences.

    Args:
        threshold: Similarity threshold (0.0-1.0). Default 0.95 for near-exact duplicates.
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with duplicate groups and potential savings.
    """
    invalid = _validate_threshold("threshold", threshold)
    if invalid:
        return invalid

    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
            duplicate_threshold=threshold,
        )
        await semantic.init()

        duplicates = await semantic.find_duplicates()

        groups = []
        for group in duplicates.groups:
            groups.append({
                "files": group.files,
                "similarity": round(group.similarity, 4),
                "size_bytes": group.size_bytes,
            })

        return json.dumps({
            "threshold": threshold,
            "group_count": len(groups),
            "groups": groups,
            "total_potential_savings_bytes": duplicates.total_potential_savings,
            "hint": "Use ragfs_propose_cleanup to create a plan for handling duplicates",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Analyze Cleanup",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_analyze_cleanup(index: str = "default") -> str:
    """Analyze files for potential cleanup.

    Identifies:
    - Duplicate files
    - Stale/unused files
    - Temporary files
    - Generated files that can be regenerated
    - Empty files

    Args:
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with cleanup candidates and potential savings.
    """
    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
        )
        await semantic.init()

        analysis = await semantic.analyze_cleanup()

        return json.dumps({
            "total_files_analyzed": analysis.total_files,
            "cleanup_candidates": analysis.candidates,
            "categories": {
                "duplicates": analysis.duplicate_count,
                "stale": analysis.stale_count,
                "temporary": analysis.temporary_count,
                "generated": analysis.generated_count,
                "empty": analysis.empty_count,
            },
            "potential_savings_bytes": analysis.potential_savings,
            "potential_savings_mb": round(analysis.potential_savings / (1024 * 1024), 2),
            "hint": "Use ragfs_propose_cleanup to create a cleanup plan for review",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


# =============================================================================
# APPROVAL WORKFLOW TOOLS - Propose-Review-Apply Pattern
# =============================================================================


@mcp.tool(
    annotations=_tool_annotations(
        title="Propose Organization",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_propose_organization(
    scope: str,
    strategy: str = "by_topic",
    max_groups: int = 10,
    similarity_threshold: float = 0.7,
    index: str = "default",
) -> str:
    """Create an organization plan (NOT executed until approved).

    This is the "Propose" phase of the Propose-Review-Apply pattern.
    The plan shows what WOULD happen, but no files are moved until approved.

    Strategies:
    - "by_topic": Group files by semantic similarity (topics)
    - "by_type": Group by file type/extension
    - "by_project": Group by detected project structure

    Args:
        scope: Directory scope to organize (relative to source root).
        strategy: Organization strategy (default: "by_topic").
        max_groups: Maximum number of groups to create (default: 10).
            Values above RAGFS_MCP_MAX_GROUPS are rejected.
        similarity_threshold: Minimum similarity for grouping (0.0-1.0).
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with plan_id and proposed actions for review.
    """
    invalid = _validate_max_groups(max_groups) or _validate_threshold(
        "similarity_threshold", similarity_threshold
    )
    if invalid:
        return invalid

    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import OrganizeRequest, OrganizeStrategy, RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
        )
        await semantic.init()

        # Map strategy string to OrganizeStrategy
        if strategy == "by_topic":
            strat = OrganizeStrategy.by_topic()
        elif strategy == "by_type":
            strat = OrganizeStrategy.by_type()
        elif strategy == "by_project":
            strat = OrganizeStrategy.by_project()
        else:
            strat = OrganizeStrategy.by_topic()

        request = OrganizeRequest(
            scope=scope,
            strategy=strat,
            max_groups=max_groups,
            similarity_threshold=similarity_threshold,
        )

        plan = await semantic.create_organize_plan(request)

        actions = []
        for action in plan.actions:
            actions.append({
                "action_type": action.action.action_type,
                "source": action.action.source,
                "target": action.action.target,
                "reason": action.reason,
                "confidence": round(action.confidence, 2),
            })

        return json.dumps({
            "plan_id": plan.id,
            "status": plan.status,
            "description": plan.description,
            "action_count": len(actions),
            "actions": actions,
            "created_at": plan.created_at,
            "hint": f"Review the actions above. Use ragfs_approve_plan(plan_id='{plan.id}') to execute, or ragfs_reject_plan to discard.",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Propose Cleanup",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_propose_cleanup(index: str = "default") -> str:
    """Create a cleanup plan for redundant/stale files (NOT executed until approved).

    Analyzes the indexed files and proposes cleanup actions like:
    - Removing duplicates (keeping one copy)
    - Deleting temporary files
    - Archiving stale files

    Args:
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with plan_id and proposed cleanup actions.
    """
    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import OrganizeRequest, OrganizeStrategy, RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
        )
        await semantic.init()

        # Create a cleanup-focused plan
        request = OrganizeRequest(
            scope="./",
            strategy=OrganizeStrategy.by_topic(),
            max_groups=1,
            similarity_threshold=0.0,
        )

        plan = await semantic.create_organize_plan(request)

        actions = []
        for action in plan.actions:
            actions.append({
                "action_type": action.action.action_type,
                "source": action.action.source,
                "target": action.action.target,
                "reason": action.reason,
                "confidence": round(action.confidence, 2),
            })

        return json.dumps({
            "plan_id": plan.id,
            "status": plan.status,
            "description": "Cleanup plan for redundant and stale files",
            "action_count": len(actions),
            "actions": actions,
            "hint": f"Review the actions. Use ragfs_approve_plan(plan_id='{plan.id}') to execute.",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="List Pending Plans",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_list_pending_plans(index: str = "default") -> str:
    """List all pending plans awaiting approval.

    Shows all proposed plans that haven't been approved or rejected yet.

    Args:
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with list of pending plans.
    """
    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
        )
        await semantic.init()

        plans = await semantic.list_pending_plans()

        pending = []
        for plan in plans:
            pending.append({
                "plan_id": plan.id,
                "status": plan.status,
                "description": plan.description,
                "action_count": len(plan.actions),
                "created_at": plan.created_at,
            })

        return json.dumps({
            "count": len(pending),
            "pending_plans": pending,
            "hint": "Use ragfs_get_plan to see full details, ragfs_approve_plan to execute, or ragfs_reject_plan to discard",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Get Plan",
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
    )
)
@with_limits
async def ragfs_get_plan(
    plan_id: str,
    index: str = "default",
) -> str:
    """Get full details of a plan including all proposed actions.

    Args:
        plan_id: The plan ID.
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with complete plan details.
    """
    err = _resolve_source(index)
    if err:
        return err

    try:
        from ragfs import RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
        )
        await semantic.init()

        plan = await semantic.get_plan(plan_id)

        if plan is None:
            return _json_error(ErrorCode.PLAN_NOT_FOUND, "Plan not found")

        actions = []
        for action in plan.actions:
            actions.append({
                "action_type": action.action.action_type,
                "source": action.action.source,
                "target": action.action.target,
                "reason": action.reason,
                "confidence": round(action.confidence, 2),
            })

        return json.dumps({
            "plan_id": plan.id,
            "status": plan.status,
            "description": plan.description,
            "action_count": len(actions),
            "actions": actions,
            "created_at": plan.created_at,
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Approve Plan",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_approve_plan(
    plan_id: str,
    index: str = "default",
) -> str:
    """Approve and execute a plan.

    This is the "Apply" phase of the Propose-Review-Apply pattern.
    All proposed actions are executed and become reversible via
    the safety layer (each action gets an undo_id).

    Args:
        plan_id: The plan ID to approve.
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with execution result and undo information.
    """
    err = _resolve_source(index)
    if err:
        return err
    denied = _deny_writes()
    if denied:
        return denied

    try:
        from ragfs import RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
        )
        await semantic.init()

        result = await semantic.approve_plan(plan_id)

        return json.dumps({
            "success": True,
            "plan_id": result.id,
            "status": result.status,
            "message": "Plan executed successfully",
            "action_count": len(result.actions),
            "hint": "All actions are reversible. Use ragfs_get_history to see undo IDs.",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


@mcp.tool(
    annotations=_tool_annotations(
        title="Reject Plan",
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_reject_plan(
    plan_id: str,
    index: str = "default",
) -> str:
    """Reject and discard a plan (no changes made).

    The plan is marked as rejected and no actions are executed.

    Args:
        plan_id: The plan ID to reject.
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON confirming rejection.
    """
    err = _resolve_source(index)
    if err:
        return err
    denied = _deny_writes()
    if denied:
        return denied

    try:
        from ragfs import RagfsSemanticManager
    except ImportError:
        return _package_missing_error()

    source_path = get_source_path(index)
    db_path = get_db_path(index)

    try:
        semantic = RagfsSemanticManager(
            source_path=source_path,
            db_path=db_path,
            model_path=get_model_path(),
        )
        await semantic.init()

        result = await semantic.reject_plan(plan_id)

        return json.dumps({
            "success": True,
            "plan_id": result.id,
            "status": result.status,
            "message": "Plan rejected and discarded",
        }, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


# =============================================================================
# STRUCTURED OPERATIONS TOOLS - Batch with Rollback
# =============================================================================


@mcp.tool(
    annotations=_tool_annotations(
        title="Batch Operations",
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
    )
)
@with_limits
async def ragfs_batch_operations(
    operations: list[BatchOperation],
    atomic: bool = True,
    dry_run: bool = False,
    index: str = "default",
) -> str:
    """Execute multiple file operations atomically.

    All operations succeed or all fail (atomic mode).
    Each operation returns an undo_id for individual rollback.

    Operations format:
    [
        {"action": "create", "target": "/path/file.txt", "content": "..."},
        {"action": "move", "source": "/old/path", "target": "/new/path"},
        {"action": "copy", "source": "/src", "target": "/dst"},
        {"action": "delete", "target": "/path/to/delete"},
        {"action": "mkdir", "target": "/new/directory"},
    ]

    Args:
        operations: List of typed operation objects (create/move/copy/delete/mkdir/write/symlink).
            Count is capped by RAGFS_MCP_MAX_BATCH_OPS; per-op content by
            RAGFS_MCP_MAX_OP_CONTENT_BYTES. Over-limit values are rejected.
        atomic: If True, rollback all on any failure (default: True).
        dry_run: If True, validate without executing (default: False).
        index: Source directory (same path as `ragfs index`) or 16-hex index id.
            Defaults to RAGFS_SOURCE_PATH or the current working directory.

    Returns:
        JSON with batch result and undo IDs.
    """
    parsed, parse_err = parse_batch_operations(operations)
    if parse_err:
        return parse_err
    assert parsed is not None

    err = _resolve_source(index)
    if err:
        return err
    if not dry_run:
        denied = _deny_writes()
        if denied:
            return denied

    source_path = get_source_path(index)
    for op in parsed:
        for attr in ("source", "target"):
            value = getattr(op, attr, None)
            if isinstance(value, str) and value:
                escaped = _ensure_under_source(source_path, value)
                if escaped:
                    return escaped

    try:
        from ragfs import Operation, RagfsOpsManager
    except ImportError:
        return _package_missing_error()

    db_path = get_db_path(index)

    try:
        ops = RagfsOpsManager(source_path, db_path)

        op_list = []
        for op in parsed:
            if isinstance(op, CreateOp):
                op_obj = Operation.create(op.target, op.content)
            elif isinstance(op, MoveOp):
                op_obj = Operation.move(op.source, op.target)
            elif isinstance(op, CopyOp):
                op_obj = Operation.copy(op.source, op.target)
            elif isinstance(op, DeleteOp):
                op_obj = Operation.delete(op.target)
            elif isinstance(op, MkdirOp):
                op_obj = Operation.mkdir(op.target)
            elif isinstance(op, WriteOp):
                op_obj = Operation.write(op.target, op.content, op.append)
            elif isinstance(op, SymlinkOp):
                op_obj = Operation.symlink(op.source, op.target)
            else:
                return _json_error(
                    ErrorCode.INVALID_INPUT,
                    f"Unknown action: {getattr(op, 'action', '')}",
                )

            op_list.append(op_obj)

        if dry_run:
            validation = await ops.dry_run(op_list)
            return json.dumps({
                "dry_run": True,
                "valid": validation.is_valid,
                "errors": [_sanitize_client_text(e) for e in validation.errors],
                "warnings": [_sanitize_client_text(w) for w in validation.warnings],
            }, indent=2)

        result = await ops.batch(op_list, atomic=atomic)

        results = []
        top_code: str | None = None
        top_error: str | None = None
        for r in result.results:
            err = r.error
            if err:
                code, message = classify_exception(RuntimeError(err))
                if code != ErrorCode.INTERNAL:
                    err = message
                    top_code = top_code or code
                    top_error = top_error or message
                else:
                    err = _sanitize_client_text(err)
            results.append({
                "success": r.success,
                "operation": r.operation,
                "path": r.path,
                "undo_id": r.undo_id,
                "error": err,
            })

        batch_id = getattr(result, "rollback_id", None) or result.id
        payload: dict[str, Any] = {
            "success": result.success,
            "atomic": atomic,
            "total_operations": len(results),
            "successful": sum(1 for r in results if r["success"]),
            "failed": sum(1 for r in results if not r["success"]),
            "results": results,
            "rollback_id": batch_id,
            "hint": "Use ragfs_undo with rollback_id to undo the entire batch, or individual undo_ids for specific operations",
        }
        if not result.success and top_code:
            payload["code"] = top_code
            payload["error"] = top_error
        return json.dumps(payload, indent=2)

    except Exception as e:  # noqa: BLE001
        return _client_error(e)


def create_server() -> MCPServer:
    """Create and return the MCP server instance.

    This is the entry point used by MCP clients.
    """
    configure_logging()
    build_allowed_roots()
    return mcp


async def main() -> None:
    """Run the MCP server using stdio transport.

    This is used when running the server directly:
        python -m ragfs_mcp
    """
    configure_logging()
    build_allowed_roots()
    await mcp.run_stdio_async()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
