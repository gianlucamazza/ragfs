# RAGFS MCP Server

The RAGFS MCP (Model Context Protocol) server exposes semantic filesystem capabilities to AI assistants like Claude.

RAGFS is NOT just a vector database - it's a **FILESYSTEM for AI agents** with:
- **Safety Layer**: Soft delete, audit history, undo support
- **Semantic Operations**: AI-powered file organization, similarity, deduplication
- **Approval Workflow**: Propose-Review-Apply pattern for safe AI agent operations

## Installation

```bash
# ragfs-mcp is not yet published on PyPI. Do not install a package with this
# name from PyPI — the name is unclaimed and could be registered by anyone.
# ragfs is not on PyPI; install ragfs-python first so pip doesn't look for it there.

# From a clone
pip install ./crates/ragfs-python
pip install ./crates/ragfs-mcp
# or editable (ragfs-python first, same command):
pip install -e ./crates/ragfs-python -e ./crates/ragfs-mcp

# Without cloning (ragfs-python first)
pip install 'git+https://github.com/gianlucamazza/ragfs#subdirectory=crates/ragfs-python'
pip install 'git+https://github.com/gianlucamazza/ragfs#subdirectory=crates/ragfs-mcp'
```

## Quick Start

### Running the Server

```bash
# Run directly
python -m ragfs_mcp

# Or use the CLI command
ragfs-mcp
```

### Claude Desktop Configuration

Add to your Claude Desktop configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ragfs": {
      "command": "ragfs-mcp",
      "env": {
        "RAGFS_SOURCE_PATH": "/path/to/project",
        "RAGFS_ALLOWED_ROOTS": "/path/to/other",
        "RAGFS_MODEL_PATH": "~/.local/share/ragfs/models",
        "RAGFS_MCP_ALLOW_WRITES": "1"
      }
    }
  }
}
```

`RAGFS_SOURCE_PATH` must be the same directory you passed to `ragfs index`. MCP hashes that canonical path with blake3 (first 16 hex chars) and opens:

```
~/.local/share/ragfs/indices/{16hex}/index.lance
```

This is the same layout the CLI uses. Do **not** point `RAGFS_DB_PATH` at `indices/default` — that folder is not created by `ragfs index`. Set `RAGFS_DB_PATH` only to override the resolved LanceDB path explicitly.

Mutating tools (`ragfs_delete_to_trash`, `ragfs_restore_from_trash`, `ragfs_undo`, `ragfs_approve_plan`, `ragfs_reject_plan`, and `ragfs_batch_operations` with `dry_run=false`) stay disabled until `RAGFS_MCP_ALLOW_WRITES=1`. Reads and dry runs do not need that flag.

The jail root for those tools is allowlisted at startup: `RAGFS_SOURCE_PATH` plus optional `RAGFS_ALLOWED_ROOTS` (`os.pathsep`-separated), each resolved with `realpath`. `index` must be one of those roots, or a 16-hex index id whose recorded source is known (the `{indices}/{id}/source` sidecar, or an allowlisted root whose CLI id matches). Any other `index` value is rejected. Hex ids never fall back to `RAGFS_SOURCE_PATH` or the current working directory.

`ragfs_similar` applies the same allowlist to `file_path`: the path is resolved with `realpath` (symlinks included) and must land inside an allowlisted root. Paths outside those roots, `..` traversal that leaves a root, and in-root symlinks that point outside are rejected. The error does not include the resolved absolute path.

Or using Python directly:

```json
{
  "mcpServers": {
    "ragfs": {
      "command": "python",
      "args": ["-m", "ragfs_mcp"]
    }
  }
}
```

---

## Available Tools

Each tool advertises MCP [ToolAnnotations](https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations)
(`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`, and a UI `title`).
These are **hints for client UX**, not permissions. Authorization is enforced by
`RAGFS_MCP_ALLOW_WRITES` and the root allowlist.

| Tool | Title | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
|------|-------|--------------|-----------------|----------------|---------------|
| `ragfs_search` | Semantic Search | true | false | true | false |
| `ragfs_index_status` | Index Status | true | false | true | false |
| `ragfs_similar` | Find Similar Files | true | false | true | false |
| `ragfs_list_indices` | List Indices | true | false | true | false |
| `ragfs_list_trash` | List Trash | true | false | true | false |
| `ragfs_get_history` | Operation History | true | false | true | false |
| `ragfs_find_duplicates` | Find Duplicates | true | false | true | false |
| `ragfs_analyze_cleanup` | Analyze Cleanup | true | false | true | false |
| `ragfs_list_pending_plans` | List Pending Plans | true | false | true | false |
| `ragfs_get_plan` | Get Plan | true | false | true | false |
| `ragfs_propose_organization` | Propose Organization | false | false | false | false |
| `ragfs_propose_cleanup` | Propose Cleanup | false | false | false | false |
| `ragfs_restore_from_trash` | Restore from Trash | false | false | false | false |
| `ragfs_reject_plan` | Reject Plan | false | false | false | false |
| `ragfs_delete_to_trash` | Delete to Trash | false | true | false | false |
| `ragfs_undo` | Undo Operation | false | true | false | false |
| `ragfs_approve_plan` | Approve Plan | false | true | false | false |
| `ragfs_batch_operations` | Batch Operations | false | true | false | false |

`openWorldHint` is false for every tool: they operate on the local index and allowlisted filesystem, not an open network. `ragfs_batch_operations` is annotated for the executing (non-`dry_run`) path; a dry run still does not require `RAGFS_MCP_ALLOW_WRITES`.

### ragfs_search

Perform semantic search in indexed files.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Natural language search query (max `RAGFS_MCP_MAX_QUERY_LENGTH`, default 2000). Longer values are rejected. |
| `index` | string | source path | Source directory (`ragfs index <path>`) or 16-hex id. Default: `RAGFS_SOURCE_PATH` or cwd |
| `limit` | integer | 10 | Maximum results to return (`1`–`RAGFS_MCP_MAX_LIMIT`, default max 100). Out-of-range values are rejected, not clamped. |
| `hybrid` | boolean | true | Enable hybrid search (vector + full-text) |

**Example:**
```
Search for "authentication implementation" in /path/to/project
```

**Response:**
```json
{
  "query": "authentication implementation",
  "index": "/path/to/project",
  "count": 3,
  "results": [
    {
      "file_path": "/path/to/auth.rs",
      "content": "pub fn authenticate(token: &str) -> Result<User>...",
      "score": 0.8542,
      "metadata": { "mime_type": "text/x-rust" }
    }
  ]
}
```

### ragfs_index_status

Get the status of an index.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `index` | string | source path | Source directory or 16-hex id. Default: `RAGFS_SOURCE_PATH` or cwd |

**Response:**
```json
{
  "exists": true,
  "index": "/path/to/project",
  "path": "/home/user/.local/share/ragfs/indices/a1b2c3d4e5f67890/index.lance",
  "has_data": true,
  "size_bytes": 52428800,
  "size_mb": 50.0,
  "last_modified": "2024-01-15T10:30:00"
}
```

### ragfs_similar

Find files similar to a given file.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Path to the source file. Must resolve (`realpath`, including symlinks) inside an allowlisted root (`RAGFS_SOURCE_PATH` or `RAGFS_ALLOWED_ROOTS`). |
| `index` | string | source path | Source directory or 16-hex id. Default: `RAGFS_SOURCE_PATH` or cwd |
| `limit` | integer | 5 | Maximum similar files to return (`1`–`RAGFS_MCP_MAX_LIMIT`, default max 100). Out-of-range values are rejected. |

**Response:**
```json
{
  "source_file": "/path/to/main.rs",
  "similar_files": [
    {
      "file_path": "/path/to/lib.rs",
      "similarity": 0.9234,
      "preview": "pub mod core;..."
    }
  ],
  "count": 1
}
```

### ragfs_list_indices

List all available indices.

**Response:**
```json
{
  "indices_dir": "/home/user/.local/share/ragfs/indices",
  "count": 2,
  "indices": [
    {
      "name": "a1b2c3d4e5f67890",
      "path": "/home/user/.local/share/ragfs/indices/a1b2c3d4e5f67890/index.lance",
      "size_mb": 50.0,
      "last_modified": "2024-01-15T10:30:00"
    },
    {
      "name": "0f1e2d3c4b5a6978",
      "path": "/home/user/.local/share/ragfs/indices/0f1e2d3c4b5a6978/index.lance",
      "size_mb": 25.5,
      "last_modified": "2024-01-14T15:00:00"
    }
  ]
}
```

`name` is the 16-hex blake3 of the canonical source path. Pass that hex id (or the original source directory) as `index` to other tools.

---

## Safety Layer Tools

These tools provide reversible file operations with undo capability.

### ragfs_delete_to_trash

Safely delete a file to trash (can be undone).

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | required | File path to delete |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "success": true,
  "message": "File moved to trash: /path/to/file.txt",
  "undo_id": "trash_abc123",
  "original_path": "/path/to/file.txt",
  "deleted_at": "2024-01-15T10:30:00",
  "hint": "Use ragfs_restore_from_trash with undo_id='trash_abc123' to restore"
}
```

### ragfs_list_trash

List all files in trash that can be restored.

**Response:**
```json
{
  "count": 2,
  "entries": [
    {
      "undo_id": "trash_abc123",
      "original_path": "/path/to/file1.txt",
      "deleted_at": "2024-01-15T10:30:00",
      "size_bytes": 1024
    }
  ],
  "hint": "Use ragfs_restore_from_trash to restore any file"
}
```

### ragfs_restore_from_trash

Restore a file from trash using its undo_id.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `undo_id` | string | required | The undo_id from delete |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "success": true,
  "message": "File restored successfully",
  "undo_id": "trash_abc123",
  "restored_path": "/path/to/file.txt"
}
```

### ragfs_get_history

Get operation history for audit trail.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 50 | Maximum entries to return (`1`–`RAGFS_MCP_MAX_LIMIT`, default max 100). Out-of-range values are rejected. |
| `path` | string | null | Filter by file path |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "count": 10,
  "entries": [
    {
      "id": "op_abc123",
      "timestamp": "2024-01-15T10:30:00",
      "operation_type": "delete",
      "path": "/path/to/file.txt",
      "reversible": true
    }
  ],
  "hint": "Use ragfs_undo with the entry id to undo reversible operations"
}
```

### ragfs_undo

Undo a previous operation by its ID.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `undo_id` | string | required | Operation ID from history |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "success": true,
  "undo_id": "op_abc123",
  "message": "Operation undone: delete -> restore",
  "original_operation": "delete",
  "undo_action": "restore",
  "affected_path": "/path/to/file.txt"
}
```

**Error Response (operation not undoable):**
```json
{
  "success": false,
  "error": "Operation is not reversible",
  "undo_id": "op_xyz789",
  "hint": "Only delete, move, copy, and create operations can be undone"
}
```

---

## Semantic Operations Tools

AI-powered file analysis and organization.

### ragfs_find_duplicates

Find duplicate or near-duplicate files using semantic embeddings.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `threshold` | float | 0.95 | Similarity threshold (`0.0`–`1.0`). Values outside the range are rejected. |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "threshold": 0.95,
  "group_count": 2,
  "groups": [
    {
      "files": ["/path/file1.txt", "/path/file1_copy.txt"],
      "similarity": 0.9823,
      "size_bytes": 2048
    }
  ],
  "total_potential_savings_bytes": 1024,
  "hint": "Use ragfs_propose_cleanup to create a plan for handling duplicates"
}
```

### ragfs_analyze_cleanup

Analyze files for potential cleanup (duplicates, stale, temp files).

**Response:**
```json
{
  "total_files_analyzed": 150,
  "cleanup_candidates": [...],
  "categories": {
    "duplicates": 5,
    "stale": 10,
    "temporary": 3,
    "generated": 8,
    "empty": 2
  },
  "potential_savings_bytes": 5242880,
  "potential_savings_mb": 5.0,
  "hint": "Use ragfs_propose_cleanup to create a cleanup plan for review"
}
```

---

## Approval Workflow Tools

These tools implement the **Propose-Review-Apply** pattern for safe AI agent operations.

### ragfs_propose_organization

Create an organization plan (NOT executed until approved).

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `scope` | string | required | Directory scope to organize |
| `strategy` | string | "by_topic" | Strategy: "by_topic", "by_type", "by_project" |
| `max_groups` | integer | 10 | Maximum groups to create (`1`–`RAGFS_MCP_MAX_GROUPS`, default max 10). Out-of-range values are rejected. |
| `similarity_threshold` | float | 0.7 | Minimum similarity for grouping (`0.0`–`1.0`). Values outside the range are rejected. |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "plan_id": "plan_abc123",
  "status": "pending",
  "description": "Organize files by topic",
  "action_count": 5,
  "actions": [
    {
      "action_type": "move",
      "source": "/docs/readme.md",
      "target": "/docs/project/readme.md",
      "reason": "Group with related project files",
      "confidence": 0.85
    }
  ],
  "created_at": "2024-01-15T10:30:00",
  "hint": "Review the actions above. Use ragfs_approve_plan(plan_id='plan_abc123') to execute."
}
```

### ragfs_propose_cleanup

Create a cleanup plan for redundant/stale files (NOT executed until approved).

The tool takes only `index`. It always analyzes the source root (`scope="./"`) and does not accept `scope`, `include_duplicates`, `include_stale`, or `stale_days`.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `index` | string | source path | Source directory or 16-hex id. Default: `RAGFS_SOURCE_PATH` or cwd |

**Response:**
```json
{
  "plan_id": "plan_cleanup_xyz",
  "status": "pending",
  "description": "Cleanup: remove 5 duplicates, 3 stale files",
  "action_count": 8,
  "actions": [
    {
      "action_type": "delete",
      "target": "/path/to/file_copy.txt",
      "reason": "Duplicate of /path/to/file.txt (similarity: 0.99)",
      "confidence": 0.95
    },
    {
      "action_type": "delete",
      "target": "/old/unused.log",
      "reason": "Stale file: not modified in 180 days",
      "confidence": 0.80
    }
  ],
  "potential_savings_bytes": 5242880,
  "potential_savings_mb": 5.0,
  "created_at": "2024-01-15T10:30:00",
  "hint": "Review carefully. Use ragfs_approve_plan(plan_id='plan_cleanup_xyz') to execute."
}
```

### ragfs_list_pending_plans

List all pending plans awaiting approval.

**Response:**
```json
{
  "count": 2,
  "pending_plans": [
    {
      "plan_id": "plan_abc123",
      "status": "pending",
      "description": "Organize files by topic",
      "action_count": 5,
      "created_at": "2024-01-15T10:30:00"
    }
  ],
  "hint": "Use ragfs_get_plan to see full details, ragfs_approve_plan to execute"
}
```

### ragfs_get_plan

Get full details of a plan including all proposed actions.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plan_id` | string | required | The plan ID |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "plan_id": "plan_abc123",
  "status": "pending",
  "description": "Organize files by topic into 3 groups",
  "created_at": "2024-01-15T10:30:00",
  "action_count": 5,
  "actions": [
    {
      "action_type": "mkdir",
      "target": "/docs/api/",
      "reason": "Create directory for API documentation",
      "confidence": 1.0
    },
    {
      "action_type": "move",
      "source": "/docs/endpoints.md",
      "target": "/docs/api/endpoints.md",
      "reason": "Group with related API documentation",
      "confidence": 0.87
    },
    {
      "action_type": "move",
      "source": "/docs/authentication.md",
      "target": "/docs/api/authentication.md",
      "reason": "Group with related API documentation",
      "confidence": 0.82
    }
  ],
  "impact_summary": {
    "files_affected": 4,
    "directories_created": 1,
    "moves": 3,
    "deletes": 0
  }
}
```

**Error Response (plan not found):**
```json
{
  "success": false,
  "error": "Plan not found",
  "plan_id": "plan_invalid",
  "hint": "Use ragfs_list_pending_plans to see available plans"
}
```

### ragfs_approve_plan

Approve and execute a plan. All actions become reversible.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plan_id` | string | required | The plan ID to approve |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "success": true,
  "plan_id": "plan_abc123",
  "status": "completed",
  "message": "Plan executed successfully",
  "action_count": 5,
  "hint": "All actions are reversible. Use ragfs_get_history to see undo IDs."
}
```

### ragfs_reject_plan

Reject and discard a plan (no changes made).

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plan_id` | string | required | The plan ID to reject |
| `index` | string | source path | Source directory or 16-hex id |

**Response:**
```json
{
  "success": true,
  "plan_id": "plan_abc123",
  "status": "rejected",
  "message": "Plan rejected and discarded",
  "action_count": 5,
  "hint": "No changes were made to the filesystem"
}
```

---

## Batch Operations Tools

### ragfs_batch_operations

Execute multiple file operations atomically.

**Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operations` | array | required | Typed operations (`create` / `move` / `copy` / `delete` / `mkdir` / `write` / `symlink`). Max `RAGFS_MCP_MAX_BATCH_OPS` (default 10). Per-op `content` max `RAGFS_MCP_MAX_OP_CONTENT_BYTES` (default 1 MiB). Over-limit input is rejected. Unknown actions and missing required fields are rejected. |
| `atomic` | boolean | true | Rollback all on failure |
| `dry_run` | boolean | false | Validate without executing |
| `index` | string | source path | Source directory or 16-hex id |

**Operations format:**
```json
[
  {"action": "create", "target": "/path/file.txt", "content": "..."},
  {"action": "move", "source": "/old/path", "target": "/new/path"},
  {"action": "copy", "source": "/src", "target": "/dst"},
  {"action": "delete", "target": "/path/to/delete"},
  {"action": "mkdir", "target": "/new/directory"}
]
```

**Response:**
```json
{
  "success": true,
  "atomic": true,
  "total_operations": 3,
  "successful": 3,
  "failed": 0,
  "results": [...],
  "rollback_id": "batch_abc123",
  "hint": "Use ragfs_undo with rollback_id to undo the entire batch"
}
```

---

## Index locations

The CLI and MCP share one scheme:

```
{data_dir}/indices/{blake3(canonical_source_path)[:16]}/index.lance
```

- `data_dir` is `RAGFS_DATA_DIR`, else `$XDG_DATA_HOME/ragfs` on Linux-like OS when that value is absolute, else the CLI `ProjectDirs` path (`~/.local/share/ragfs` on Linux, `~/Library/Application Support/ragfs` on macOS, `%APPDATA%\\ragfs\\data` on Windows)
- `canonical_source_path` is the symlink-resolved absolute path (same as Rust `Path::canonicalize`)
- the folder name is the first 16 hex characters of blake3 over those path bytes

Example (same as the CLI):

```bash
# After: ragfs index /home/user/project
python - <<'PY'
from ragfs_mcp.server import get_db_path
print(get_db_path("/home/user/project"))
# /home/user/.local/share/ragfs/indices/<16hex>/index.lance
PY
```

Pass the **source directory** (or the 16-hex id from `ragfs_list_indices`) as `index`. A named folder such as `indices/default` is not created by `ragfs index`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAGFS_SOURCE_PATH` | *(unset)* | Default source directory to hash (must match `ragfs index <path>`). Also the default allowlisted jail root. |
| `RAGFS_ALLOWED_ROOTS` | *(unset)* | Extra allowlisted jail roots, `os.pathsep`-separated, each resolved with `realpath`. |
| `RAGFS_MCP_ALLOW_WRITES` | *(unset)* | Set to `1` to enable mutating tools. Reads and `dry_run` batch calls work without it. |
| `RAGFS_MCP_MAX_LIMIT` | `100` | Max `limit` for search, similar, and history. Matches CLI `[query].max_limit`. Over-limit values are rejected. |
| `RAGFS_MCP_MAX_QUERY_LENGTH` | `2000` | Max `ragfs_search` query length. Same bound `ragfs_similar` already uses when embedding file text. |
| `RAGFS_MCP_MAX_GROUPS` | `10` | Max `max_groups` for `ragfs_propose_organization`. Matches the FUSE `OrganizeRequest` default. |
| `RAGFS_MCP_MAX_BATCH_OPS` | `10` | Max operations in one `ragfs_batch_operations` call. Docs/tests use 1–3; 10 is a conservative agent-turn ceiling. |
| `RAGFS_MCP_MAX_OP_CONTENT_BYTES` | `1048576` | Max UTF-8 bytes of `content` on one batch create/write. Conservative vs index `max_file_size` (50MB). |
| `RAGFS_MCP_TIMEOUT_SECONDS` | `30` | Wall-clock timeout per tool call. Local gte-small search is seconds; raise this for a cold model download. `0` disables. |
| `RAGFS_MCP_RATE_LIMIT` | `30` | Max tool calls per process in one window. Stdio has one client per process. `0` disables. |
| `RAGFS_MCP_RATE_WINDOW_SECONDS` | `60` | Sliding window for `RAGFS_MCP_RATE_LIMIT`. |
| `RAGFS_DATA_DIR` | CLI `ProjectDirs` path (Linux: `$XDG_DATA_HOME/ragfs` if absolute) | Data root; indices are stored under `indices/{16hex}/` |
| `RAGFS_DB_PATH` | *(unset)* | Optional explicit LanceDB path; skips hashing when set |
| `RAGFS_MODEL_PATH` | `~/.local/share/ragfs/models` | Path to embedding model |

---

## Usage Examples

### With Claude Desktop

Once configured, you can ask Claude to:

- "Search my codebase for authentication handling"
- "Find files similar to src/main.rs"
- "What indexes are available?"
- "Show the status of the index for /path/to/project"

### Programmatic Usage

```python
from ragfs_mcp import create_server

# Create server instance
server = create_server()

# The server can be run with any MCP-compatible transport
await server.run_stdio_async()
```

---

## Indexing Files

Before using the MCP server, you need to index your files using the RAGFS CLI:

```bash
# Index a directory (creates indices/{blake3(canonical path)[:16]}/index.lance)
ragfs index /path/to/project

# Then point MCP at the same directory
export RAGFS_SOURCE_PATH=/path/to/project

# Mount (uses the same hashed index path)
ragfs mount /path/to/project /mnt/ragfs --foreground
```

---

## Troubleshooting

### "Index not found" Error

MCP looks up the index the same way as the CLI: blake3 of the **canonical** source path. Make sure you indexed that directory and pass the same path (or set `RAGFS_SOURCE_PATH` to it):

```bash
ragfs index /path/to/project
export RAGFS_SOURCE_PATH=/path/to/project
```

A relative path and an absolute path to the same directory resolve to the same index. Symlinks are resolved before hashing. `RAGFS_DB_PATH=~/.local/share/ragfs/indices/default` will not find a CLI-built index.

### Model Download Issues

The embedding model (~100MB) is downloaded on first use. Ensure you have internet connectivity and sufficient disk space.

### Connection Issues

Check that:
1. The MCP server is running
2. Claude Desktop configuration is correct
3. The `ragfs-mcp` command is in your PATH

### Debugging

Enable verbose logging:

```bash
RUST_LOG=debug ragfs-mcp
```

---

## API Reference

### create_server()

Creates and returns the MCP server instance.

```python
from ragfs_mcp import create_server

server = create_server()  # MCPServer on mcp 2.x, FastMCP on mcp 1.x
```

### main()

Async entry point for running the server.

```python
from ragfs_mcp import main
import asyncio

asyncio.run(main())
```

### run()

Synchronous entry point (used by CLI).

```python
from ragfs_mcp import run

run()  # Blocks until server stops
```
