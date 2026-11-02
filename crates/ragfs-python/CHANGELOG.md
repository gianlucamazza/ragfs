# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file tracks `ragfs-python` workspace versions. The crate is listed in
`release-plz.toml` (`publish = false`, `git_only = true`). Bindings are not
on PyPI yet. Git tag `v0.2.0` is dated 2026-09-25 (the crate heading below
keeps the earlier workspace date).

## [0.3.2] - 2026-10-31


### Miscellaneous

- Updated the following local packages: ragfs-core, ragfs-chunker, ragfs-embed, ragfs-extract, ragfs-store, ragfs-index, ragfs-query, ragfs-fuse
[0.3.2]: https://github.com/gianlucamazza/ragfs/compare/v0.3.1...v0.3.2


## [0.3.1] - 2026-10-21


### Added

- **store**: Persist source media locations with schema v3 migration ([#216](https://github.com/gianlucamazza/ragfs/pull/216))

### Fixed

- Reconcile stale indexes and enable safe MCP plan execution ([#213](https://github.com/gianlucamazza/ragfs/pull/213))
[0.3.1]: https://github.com/gianlucamazza/ragfs/compare/v0.3.0...v0.3.1


## [0.3.0] - 2026-10-20

- Align workspace release with ADR-010 index integrity changes. See the root
  changelog and upgrade guide for breaking indexing defaults and migration.

## [0.2.2] - 2026-10-19


### Fixed

- **mcp**: Batch operations use the source root for safety; no hard-delete fallback ([#166](https://github.com/gianlucamazza/ragfs/pull/166))
[0.2.2]: https://github.com/gianlucamazza/ragfs/compare/v0.2.1...v0.2.2


## [0.2.1] - 2026-10-17


### Documentation

- Prepare 0.2.1 changelog, metadata, and source installs ([#139](https://github.com/gianlucamazza/ragfs/pull/139))
- Point repo metadata and links at gianlucamazza/ragfs ([#145](https://github.com/gianlucamazza/ragfs/pull/145))

### Fixed

- **core**: Share path jail across fuse, python and mcp ([#90](https://github.com/gianlucamazza/ragfs/pull/90))
- **store**: Derive embedding dim from the embedder ([#92](https://github.com/gianlucamazza/ragfs/pull/92))

### Deps

- **python**: Update langchain-anthropic requirement ([#34](https://github.com/gianlucamazza/ragfs/pull/34))
- **python**: Update langchain-openai requirement ([#31](https://github.com/gianlucamazza/ragfs/pull/31))
- **python**: Update langchain-ollama requirement ([#32](https://github.com/gianlucamazza/ragfs/pull/32))
- **python**: Update haystack-ai requirement in /crates/ragfs-python ([#33](https://github.com/gianlucamazza/ragfs/pull/33))
- **python**: Update pytest-asyncio requirement in /crates/ragfs-python ([#35](https://github.com/gianlucamazza/ragfs/pull/35))
[0.2.1]: https://github.com/gianlucamazza/ragfs/compare/v0.2.0...v0.2.1


## [0.2.0] - workspace (unpublished)

First changelog for the Python bindings at workspace `0.2.0`. Entries below
were collected from git history; they do not imply a registry or GitHub
release.

### Added

- **python**: Add PyO3 bindings for RAGFS
- **python**: Extend bindings with safety, semantic, and ops modules
- **examples**: Add LlamaIndex and Haystack RAG pipeline examples
- **extract**: Extract text from Office OOXML and ODT ([#55](https://github.com/gianlucamazza/ragfs/pull/55))
- Directory-scoped search and dedicated FUSE mount thread ([#60](https://github.com/gianlucamazza/ragfs/pull/60))

### CI/CD

- Unblock inherited rustc, cargo-deny, and maturin failures ([#42](https://github.com/gianlucamazza/ragfs/pull/42))

### Changed

- Fix formatting and clippy warnings

### Fixed

- **python**: Correct import names in __init__.py
- **deps**: Update fuser 0.16 and pyo3 0.27 for security fixes
- Resolve CI failures while the workspace version was 0.2.0
- Align docs and FUSE help with real behavior
- **security**: Clear P0 direct-dep advisories for #44 ([#62](https://github.com/gianlucamazza/ragfs/pull/62))

### Miscellaneous

- Improve project configuration
- Unify project descriptions and metadata across packages
