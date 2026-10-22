# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.1] - 2026-10-21

Image caption indexing, additive schema v3 media columns, a reproducible
benchmark protocol, stale-index reconciliation, and roadmap status updates.

### Upgrade notes

Existing indexes migrate automatically on open (`index`, `query`, `status`,
or `mount`) to schema v3. Missing `modality`, `start_ms`, and `end_ms`
columns are added in place; rows with null `modality` are set to `text`
with no time interval. A reindex is not required to keep using the index.
A v0.3.0 binary still opens a migrated v3 index (`chunks_schema_version >= 2`
is treated as current; extra columns are ignored on read). Run
`ragfs index <path> --force` only if you want existing image-caption rows
classified as `image` instead of `text`.

### Added

- Persist source media locations with schema v3 migration. Existing v1/v2
  indexes migrate additively on open; legacy rows default to text with no
  time interval (#216).
- Index image captions with bounded image decoding (#215).
- Add a reproducible benchmark protocol and validated retrieval adapters
  (#214). The same merge also bumps `rustls-webpki` 0.103.15 → 0.103.16
  and `webpki-roots` / `webpki-root-certs` in `Cargo.lock`.

### Fixed

- Reconcile stale indexes and enable safe MCP plan execution (#213).

### Documentation

- Mark ADR-011 phases 1–2 done in ROADMAP (#218).
- Mark ADR-009 phases shipped via #214 in ROADMAP (#222).

## [0.3.0] - 2026-10-20

### Security and index integrity

- Apply nested `.ragfsignore` rules with root-bounded precedence.
- Reject model-id and dimension mismatches on store open; explicit `--force`
  rebuilds index tables and fingerprints without removing historical receipts.
- Drop chunks below `[chunking].min_alnum_chars` (default 3) before embedding;
  record the applied policy and embedding dimension in query receipts.
- Report traversal errors and propagate excluded-row purge failures.
- Add a default-on `mount` feature and a CI check for CLI builds without FUSE.
- Add a post-insert FTS regression covering both hybrid and lexical queries.


### Breaking / behaviour changes

- **BREAKING**: Safer default exclusions for indexing (0.3.0). Hidden files *and* hidden directories under the index root are skipped; a secret-file denylist (`.env*`, `*.pem` / `*.key`, `id_rsa` / `id_ed25519`, credentials files, `.netrc` / `.npmrc` / `.pypirc`, kube config, and similar) is always on. `--include-hidden` / `index.include_hidden` does not disable that denylist. CLI, mount, MCP (via the CLI-built index), and library `IndexerConfig` share one `ignore`-crate matcher. `.gitignore` / `.ignore` under the index root are honoured by default (no parent walk, no global gitignore); `!` rules cannot re-include secrets. Every `ragfs index` purges store rows for newly excluded paths (not only `--force`). See ADR-010.

### Added

- `ragfs index --include-hidden` and `ragfs mount --include-hidden`, plus `[index]` keys `include_hidden`, `include_secret_files`, `honor_gitignore`, and `purge_excluded`.
- `docs/community-forks.md` crediting sophie4869/ragfs (hidden/secret excludes) and manojtummala/SemPOSIX (scoped search, #60).

### Documentation

- `docs/CONFIGURATION.md` and `docs/USER_GUIDE.md` document the shared defaults, secret denylist, hidden-root exception, and purge-on-reindex.

## [0.2.2] - 2026-10-19

MCP server hardening for the local stdio `ragfs-mcp` package (issue #164, PRs #166–#172), plus accepted ADR-009 (docs-only transparent memory benchmark harness) and smaller Rust fixes (#161, #162).

### Breaking / behaviour changes (MCP)

- **BREAKING**: Mutating MCP tools stay disabled until `RAGFS_MCP_ALLOW_WRITES=1`. Affected: `ragfs_delete_to_trash`, `ragfs_restore_from_trash`, `ragfs_undo`, `ragfs_approve_plan`, `ragfs_reject_plan`, and `ragfs_batch_operations` when `dry_run` is false. Reads and dry-run batches are unchanged (#167).
- **BREAKING**: Jail roots are `RAGFS_SOURCE_PATH` plus optional `RAGFS_ALLOWED_ROOTS` (`os.pathsep`-separated), each resolved with `realpath`. `index` must be an allowlisted root or the recorded source of a known index; hex index ids map to that recorded source and do **not** fall back to `RAGFS_SOURCE_PATH` or cwd. `ragfs_similar` applies the same allowlist to `file_path` (#167, #168).
- **BREAKING**: Batch / delete paths construct the safety manager with the source tree as the jail. If soft-delete cannot complete, the call fails instead of removing the file without a recoverable trash entry (#166).
- Over-limit `limit`, query length, `max_groups`, batch operation count, and per-op `content` size are **rejected** (not clamped). Each cap is overridable via env (table below). Every tool call also has a wall-clock timeout and a per-process rate limit (#169).
- Client-visible errors include a stable `code` and no longer echo absolute host paths or raw exception internals (#171).

### Added
- MCP tool errors include a stable `code` (`INDEX_NOT_FOUND`, `PATH_OUTSIDE_ROOT`, `WRITES_DISABLED`, `LIMIT_EXCEEDED`, `TIMEOUT`, `RATE_LIMITED`, `INTERNAL`, …). Full exception detail is logged at debug on stderr only (issue #164 MCP-05, #171).
- MCP writes one structured JSON audit line per tool call to stderr (`timestamp`, `tool`, redacted `args`, `outcome`, `duration_ms`, `write`). Disable with `RAGFS_MCP_AUDIT_LOG=0`. Python log level is `RAGFS_MCP_LOG_LEVEL` (issue #164 MCP-06, #171).
- MCP `ToolAnnotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`, and a UI `title`) on every `ragfs-mcp` tool (issue #164 MCP-01, #170). Hints are not permissions.
- `RAGFS_ALLOWED_ROOTS` and `RAGFS_MCP_ALLOW_WRITES` environment variables for the MCP server, plus overridable input caps, timeout, rate limit, and audit/log settings (table below).
- Persist query receipts with an index revision id (`ragfs query --save-receipt`) (#162).
- Accepted ADR-009: transparent memory benchmark harness for ragfs and
  emotional-memory (protocol, pinned public datasets, versioned facts,
  strict/lenient metrics). Design only; implementation follows in phased PRs (#165).

### Changed
- **BREAKING**: Mutating MCP tools now need `RAGFS_MCP_ALLOW_WRITES=1` (`ragfs_delete_to_trash`, `ragfs_restore_from_trash`, `ragfs_undo`, `ragfs_approve_plan`, `ragfs_reject_plan`, and `ragfs_batch_operations` when `dry_run` is false). Reads and dry runs are unchanged (#167).
- **BREAKING**: MCP jail roots are allowlisted from `RAGFS_SOURCE_PATH` and optional `RAGFS_ALLOWED_ROOTS` (`os.pathsep`-separated), each resolved with `realpath`. `index` must be an allowlisted root or the recorded source of a known index; hex index ids map to that recorded source and do not fall back to `RAGFS_SOURCE_PATH` or cwd (#167, #168).
- MCP tool error payloads now include a `code` field. Client-visible `error` text no longer includes absolute host paths or raw exception internals (issue #164 MCP-05, #171).
- MCP tools now reject over-limit inputs that previously ran unbounded (`limit`, query length, `max_groups`, batch operation count, and per-op `content` size). Each cap is overridable with a `RAGFS_MCP_*` env var. Every tool call also has a wall-clock timeout and a per-process rate limit (#169).

### Fixed
- **BREAKING**: MCP batch operations construct the safety manager with the source tree as the jail and the index data dir for trash/history, so deletes can be undone. If soft-delete fails, the operation fails instead of removing the file without a recoverable trash entry (#166).
- MCP `ragfs_similar` resolves `file_path` with `realpath` (symlinks included) and rejects paths outside the allowlisted roots (`RAGFS_SOURCE_PATH` plus `RAGFS_ALLOWED_ROOTS`). The error does not echo the resolved absolute path (#168).
- Scoped ignore for transitive RUSTSEC-2024-0449 (`unsafe-libyaml` via lindera) (#161).

### Security
- MCP tool responses no longer echo host paths or exception internals; each error has a stable code, and tool calls are audited on stderr (issue #164 MCP-05 / MCP-06, #171).
- MCP tools advertise accurate `ToolAnnotations` so clients can distinguish read vs write vs destructive operations (issue #164 MCP-01, #170). Hints are not ACLs; writes still require `RAGFS_MCP_ALLOW_WRITES=1` and the root allowlist.
- MCP tools reject unbounded `limit`, query length, `max_groups`, batch size, and per-op content, and apply a per-call timeout plus a per-process rate limit (issue #164 MCP-02 / MCP-07, #169).
- Allowlisted filesystem roots and opt-in write tools for `ragfs-mcp` (#167, #168).

### Documentation
- MCP is stdio-only: drop `ragfs mcp serve`, `:8080`, and “any transport”. `docs/MCP.md` has a Security model section (allowlist, opt-in writes, caps/timeout/rate limit, annotations as hints, error codes, stderr audit log) and documents that `ragfs_approve_plan` fails closed because the Python semantic manager has no `OpsManager` (issue #164 MCP-09 / MCP-10, #172).
- Known limitation: `ragfs_approve_plan` remains **fail-closed**. It is write-gated and path-jailed, but the Python semantic manager has no `OpsManager`, so approve does not execute plans. Propose / list / get / reject continue to work.

### MCP environment variables

Defaults from `crates/ragfs-mcp/src/ragfs_mcp/server.py` (`DEFAULT_*` constants and `os.environ.get` fallbacks). Names match the code.

| Variable | Default | Notes |
|----------|---------|--------|
| `RAGFS_SOURCE_PATH` | *(unset)* | Default source directory to hash (must match `ragfs index <path>`). Also the default allowlisted jail root. |
| `RAGFS_ALLOWED_ROOTS` | *(unset)* | Extra allowlisted jail roots, `os.pathsep`-separated, each resolved with `realpath`. |
| `RAGFS_MCP_ALLOW_WRITES` | *(unset)* | Set to `1` to enable mutating tools. Reads and `dry_run` batch calls work without it. |
| `RAGFS_MCP_MAX_LIMIT` | `100` | Max `limit` for search, similar, and history. Matches CLI `[query].max_limit`. |
| `RAGFS_MCP_MAX_QUERY_LENGTH` | `2000` | Max `ragfs_search` query length (same bound `ragfs_similar` already uses when embedding file text). |
| `RAGFS_MCP_MAX_GROUPS` | `10` | Max `max_groups` for `ragfs_propose_organization`. Matches FUSE `OrganizeRequest` default. |
| `RAGFS_MCP_MAX_BATCH_OPS` | `10` | Max operations in one `ragfs_batch_operations` call. |
| `RAGFS_MCP_MAX_OP_CONTENT_BYTES` | `1048576` | Max UTF-8 bytes of `content` on one batch create/write (1 MiB; index `max_file_size` is 50MB). |
| `RAGFS_MCP_TIMEOUT_SECONDS` | `30` | Wall-clock timeout per tool call (`DEFAULT_TIMEOUT_SECONDS = 30.0`). `0` disables. |
| `RAGFS_MCP_RATE_LIMIT` | `30` | Max tool calls per process in one window. `0` disables. |
| `RAGFS_MCP_RATE_WINDOW_SECONDS` | `60` | Sliding window for `RAGFS_MCP_RATE_LIMIT` (`DEFAULT_RATE_WINDOW_SECONDS = 60.0`). |
| `RAGFS_MCP_AUDIT_LOG` | `1` | One structured JSON audit line per tool call on stderr. Set to `0` to disable. |
| `RAGFS_MCP_LOG_LEVEL` | `WARNING` | Python logging level (`DEBUG` / `INFO` / `WARNING` / `ERROR`); logs on stderr only. |

Related (pre-existing, still documented): `RAGFS_DATA_DIR`, `RAGFS_DB_PATH`, `RAGFS_MODEL_PATH`.

### Upgrade notes

1. Set `RAGFS_SOURCE_PATH` to the same path you indexed with `ragfs index`.
2. Add any extra roots to `RAGFS_ALLOWED_ROOTS` if needed.
3. Set `RAGFS_MCP_ALLOW_WRITES=1` only if the client must mutate the tree.
4. Expect `LIMIT_EXCEEDED` / `PATH_OUTSIDE_ROOT` / `WRITES_DISABLED` codes where previous builds accepted unbounded or out-of-jail inputs.

## [0.2.1] - 2026-10-10

### Security
- Path jail (`resolve_under_root`) now lives in `ragfs-core` and is enforced by `SafetyManager` (`soft_delete` / `restore` / `undo`), so Python `RagfsSafetyManager` and MCP `ragfs_delete_to_trash` cannot escape the source root.
- Documented the advisory-response ladder, `ignore:` ownership, and §1.2 review cadence (next review by 2026-12-31) in `SECURITY.md`.

### Removed
- **BREAKING**: Optional `pdf_oxide` extractor feature. PDF text and images continue to use `PdfExtractor` (`pdf-extract` + `lopdf`). `--features pdf_oxide` is no longer valid.

### Changed
- Agent docs (`CLAUDE.md`, `AGENTS.md`) list all 10 Cargo workspace crates plus `ragfs-mcp`. `docs/PERFORMANCE.md` documents `[embedding].model`, CLI-only `--force`, and `--hybrid` vs `[query].hybrid`.
- Embedding dimension and model id for `LanceStore` come from `Embedder::dimension()` / `model_name()`. Opening an index whose `vector` width differs from the embedder fails with `StoreError::Schema`.
- Split `ragfs-fuse` FUSE handler `filesystem.rs` into `filesystem/` modules by virtual-directory family (query, ops, safety, semantic, passthrough). Issue #52.
- CI: `Swatinem/rust-cache` uses a shared key across Check/Clippy/Test/Docs/Python; pull requests run Python 3.12 only (3.10–3.13 stays on `main`); coverage and Python integration run on `main` only. Dependabot ignores 0.x minor bumps of `criterion`, `notify-debouncer-full`, and `tokenizers`; auto-merge skips Cargo 0.x minors.
- CI cost: deps compile at `opt-level=0` on runners; PRs drop `--all-features` (keep `ragfs/test-backends`); Python jobs skip when Python paths are unchanged; Coverage is weekly; `docs.yml` uses `cargo +nightly` so `rust-toolchain.toml` cannot pin it to stable. A `CI` aggregator treats skipped rust jobs as success on docs-only PRs.
- Project hygiene: MSRV docs 1.91, `Makefile` / `rust-toolchain.toml`, `CODEOWNERS`, GitHub private advisory as the security channel, `contents: read` on CI/coverage, pinned `ruff==0.15.9`.
- `docs/AUDIT.md`: RUSTSEC-2025-0119 (`number_prefix`) is resolved. `hf-hub` 0.5 pulls `indicatif` 0.18, which uses `unit-prefix` (issue #79). Three unmaintained rows remain (`paste` #80, `core2` #77, `ttf-parser` #82). `paste` also stays via `gemm`, `rav1e`, and `lance-bitpacking`, so a `tokenizers` bump alone does not clear it.
- Drop `core2` (RUSTSEC-2026-0105, issue #77): `bitstream-io` 4.10 uses `no_std_io2`. `image` no longer enables `avif` (the unused ravif/rav1e encoder); PNG and JPEG writes are unchanged. `paste` (#80) and `ttf-parser` (#82) stay.

### Added
- CLI integration tests (`assert_cmd`) for config/`--force`/`--hybrid`/`max_file_size` and unsupported models, using `RAGFS_TEST_EMBEDDER=noop`.
- Repo social card (`docs/assets/social.svg` source, `docs/assets/social.png` 1280×640) as the README header. README is a front page (quick start, feature matrix, grouped docs); the CLI manpage stays in `docs/USER_GUIDE.md`.

### Fixed
- Revert Dependabot `lancedb` 0.39.0 (#72): `Error::Http` is `cfg(feature = "remote")` while `job.rs` uses it with default features. Pin stays 0.37.1; cargo Dependabot ignores `lancedb >=0.38` and Arrow 59+.
- MCP `ragfs_batch_operations` serializes a failed atomic batch: `BatchResult.rollback_id` aliases the batch `id` (the previous attribute miss turned a jail reject into `{"error": "... no attribute 'rollback_id'"}`).
- Align `candle-core` and `candle-nn` with `candle-transformers` 0.11 so `ragfs-embed` compiles (one `Tensor` type, not 0.9 + 0.11).
- Pin the MSRV job to rustc 1.91 via `dtolnay/rust-toolchain@stable` + `toolchain: "1.91"` (Dependabot #67 had moved the action tag to 1.120).

## [0.2.0] - 2026-09-25

### Security
- Bump `lopdf` to `0.42` (RUSTSEC-2026-0187 nesting-depth DoS). Already on the 0.42 API in `ragfs-extract`.
- Bump `pyo3` and `pyo3-async-runtimes` to `0.29` (RUSTSEC-2026-0176 / RUSTSEC-2026-0177).
- Replace unmaintained `daemonize` with `nix` (`fork` + `setsid`, stdio redirect, pid file) for `ragfs mount` without `--foreground`. rustix 1.x does not expose `fork` outside its unstable `runtime` feature.

### Changed
- Background `ragfs mount` still writes a PID file to `$XDG_RUNTIME_DIR/ragfs/<hash>.pid` (fallback `~/.cache/ragfs/run/`) and logs to `~/.cache/ragfs/logs/<hash>.log`. Unmount remains `fusermount -u <mountpoint>`.
- Documented actual code chunking (pattern matching) and removed unused `tree-sitter` dependency
- FUSE `.help` now covers `.ops/`, `.safety/`, `.semantic/` and product limits
- FUSE `.config` includes `api_version` and states it is mount wiring, not user TOML

### Added
- Directory-scoped vector search: persist relative `dir_path` on chunks and filter with `ragfs query --scope <dir>` (exact directory or subdirectory; IVF-PQ ANN is unchanged)
- Lance chunks schema v2 migration: existing indexes gain `dir_path` / `dir_depth` / `path_components` on open (sidecar `ragfs-schema.json`); `--force` is not a schema upgrade
- FUSE `mount2` runs on a dedicated OS thread so callbacks can `block_on` without panicking
- Best-effort IVF-PQ ANN index on `vector` when a Lance table has at least 256 rows (cosine-trained; incrementally refreshed after large appends; L2/Dot and failed builds stay exact)
- Office text extraction for `.docx`, `.xlsx`, `.pptx`, and `.odt` (ZIP+XML; not binary `.doc`)
- **Python bindings**: New `ragfs-python` crate with PyO3 bindings
  - `RAGFSIndex` class for indexing and querying
  - `RAGFSStore` for direct vector store access
  - Async support via `pyo3-async-runtimes`
  - Framework adapters for LangChain, LlamaIndex, Haystack
  - Build with `maturin build`
- **FUSE capabilities exposed to Python** (Propose-Review-Apply pattern for AI agents):
  - `RagfsSafetyManager`: Soft delete, trash, history, undo operations
  - `RagfsSemanticManager`: AI-powered file organization, similar/duplicate detection
  - `RagfsOpsManager`: Structured file operations with JSON feedback
  - `OrganizeStrategy`, `OrganizeRequest`, `SemanticPlan`, `PlanAction` types
- **LlamaIndex FUSE-aware integration**:
  - `RagfsSafeVectorStore`: VectorStore with safety layer integration
  - `RagfsOrganizer`: Semantic organizer with Propose-Review-Apply workflow
- **Haystack FUSE-aware integration**:
  - `RagfsSafeDocumentStore`: DocumentStore with soft delete and undo
  - `RagfsOrganizer`: Haystack component for AI-powered file organization
- **MCP Server with complete FUSE capabilities** (18 tools):
  - Safety Layer: `ragfs_delete_to_trash`, `ragfs_list_trash`, `ragfs_restore_from_trash`, `ragfs_get_history`, `ragfs_undo`
  - Semantic Operations: `ragfs_find_duplicates`, `ragfs_analyze_cleanup`
  - Approval Workflow: `ragfs_propose_organization`, `ragfs_propose_cleanup`, `ragfs_list_pending_plans`, `ragfs_get_plan`, `ragfs_approve_plan`, `ragfs_reject_plan`
  - Batch Operations: `ragfs_batch_operations`
- **CI/CD Python support**:
  - Python tests for all integrations (3.10-3.13)
  - Pre-release validation workflow
  - Python release workflow for PyPI publishing
- **Security hardening**:
  - `SECURITY.md` with vulnerability reporting guidelines
  - `deny.toml` for cargo-deny license and advisory checks
- **VectorStore iteration**: New methods for bulk operations
  - `get_all_chunks()`: Returns all chunks in the store
  - `get_all_files()`: Returns all file records in the store
- **BlipCaptioner**: BLIP-based image captioning using Candle ML
  - Auto-download from HuggingFace Hub (`Salesforce/blip-image-captioning-base`)
  - Image preprocessing with CLIP normalization
  - Autoregressive caption generation
  - Requires `vision` feature flag
- **Semantic organization**: AI-powered file management features
  - `find_duplicates()`: Detect similar files using embedding cosine similarity
  - `suggest_organization()`: AI-powered folder structure suggestions
  - Configurable similarity thresholds
- **Daemonization**: `ragfs mount` now properly forks to background when run without `--foreground`
  - PID file stored in `$XDG_RUNTIME_DIR/ragfs/` or `~/.cache/ragfs/run/`
  - Logs written to `~/.cache/ragfs/logs/`
  - Graceful unmount via `fusermount -u <mountpoint>`
- **TOML configuration**: Load settings from `~/.config/ragfs/config.toml`
  - `ragfs config show` - Display current configuration
  - `ragfs config init` - Generate sample config file
  - `ragfs config path` - Show config file location
  - `--config` global flag to specify custom config path
- **PDF image extraction**: Extract embedded images from PDFs using lopdf
  - Supports JPEG (DCTDecode), PNG (FlateDecode), JPEG2000 (JPXDecode)
  - CMYK to RGB conversion
  - Memory limits: 100 images max, 50MB total, 50px minimum dimension
- **Virtual `.ragfs/.help` file**: Usage documentation accessible via FUSE mount
- **NoopEmbedder**: Testing embedder available without Candle dependency
- **MemoryStore**: In-memory vector store available without LanceDB dependency
- **Atomic batch rollback**: Batch operations with `atomic: true` now automatically roll back on failure
  - All successful operations are undone if any operation fails
  - Rollback details included in batch result (`rollback_performed`, `rollback_details`)
- **Mkdir and Symlink operations**: New operation types in OpsManager
  - `mkdir`: Create directories via `.ops/` interface
  - `symlink`: Create symbolic links (Unix-only)
- **Semantic plan persistence**: Plans are saved to disk and survive restarts
  - Plans stored in `~/.local/share/ragfs/plans/{index_hash}/`
  - Automatic cleanup of expired plans (configurable retention)
- **Semantic plan execution**: Approved plans are now executed automatically
  - Actions run sequentially via OpsManager
  - Each action generates an undo_id for manual reversal if needed
  - Plan status reflects execution result (Completed/Failed)

### Changed
- **BREAKING**: Feature flags restructured for optional ML backends
  - `candle` feature (default): Enables `CandleEmbedder` in ragfs-embed
  - `lancedb` feature (default): Enables `LanceStore` in ragfs-store
  - `vision` feature: Enables `BlipCaptioner` for image captioning
  - `full` feature: Enables all optional features
  - Build profiles: `cargo build` (default), `--features full`, `--no-default-features` (minimal)

## [0.1.0] - 2025-01-11

### Added
- Initial release
- Core traits and types for RAG filesystem (`ragfs-core`)
- Content extraction for text files (`ragfs-extract`)
- Fixed-size chunking strategy (`ragfs-chunker`)
- Local embedding generation with Candle/gte-small (`ragfs-embed`)
- LanceDB-based vector storage (`ragfs-store`)
- Indexing pipeline with file watching (`ragfs-index`)
- Query execution with semantic search (`ragfs-query`)
- FUSE filesystem interface (`ragfs-fuse`)
- CLI with `index`, `query`, `mount`, and `status` commands (`ragfs`)
- JSON and text output formats
- Verbose logging support

### Technical Details
- Rust edition 2024, MSRV 1.88
- Async-first design with Tokio
- 384-dimensional embeddings (gte-small model)
- LanceDB for vector storage with ANN search
- Content-addressed storage with blake3 hashing
- Registry pattern for extensible extractors and chunkers

[Unreleased]: https://github.com/gianlucamazza/ragfs/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/gianlucamazza/ragfs/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/gianlucamazza/ragfs/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/gianlucamazza/ragfs/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/gianlucamazza/ragfs/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/gianlucamazza/ragfs/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/gianlucamazza/ragfs/releases/tag/v0.1.0
