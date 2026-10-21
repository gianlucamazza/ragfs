# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] - 2026-10-21


### Added

- **index**: Index image captions with bounded image decoding ([#215](https://github.com/gianlucamazza/ragfs/pull/215))
- **store**: Persist source media locations with schema v3 migration ([#216](https://github.com/gianlucamazza/ragfs/pull/216))
- **bench**: Add reproducible protocol and validated retrieval adapters ([#214](https://github.com/gianlucamazza/ragfs/pull/214))
[0.3.1]: https://github.com/gianlucamazza/ragfs/compare/v0.3.0...v0.3.1


## [0.3.0] - 2026-10-20

- Align workspace release with ADR-010 index integrity changes. See the root
  changelog and upgrade guide for breaking indexing defaults and migration.

## [0.2.2] - 2026-10-19


### Added

- Persist query receipts with an index revision id ([#162](https://github.com/gianlucamazza/ragfs/pull/162))

### Fixed

- Ignore transitive RUSTSEC-2024-0449 from lindera ([#161](https://github.com/gianlucamazza/ragfs/pull/161))
[0.2.2]: https://github.com/gianlucamazza/ragfs/compare/v0.2.1...v0.2.2


## [0.2.1] - 2026-10-17


### Documentation

- Align crate list and config docs with the tree ([#89](https://github.com/gianlucamazza/ragfs/pull/89))
- Point repo metadata and links at gianlucamazza/ragfs ([#145](https://github.com/gianlucamazza/ragfs/pull/145))

### Fixed

- **core**: Share path jail across fuse, python and mcp ([#90](https://github.com/gianlucamazza/ragfs/pull/90))
- **store**: Derive embedding dim from the embedder ([#92](https://github.com/gianlucamazza/ragfs/pull/92))

### Testing

- **cli**: Assert_cmd coverage for config, force, hybrid ([#93](https://github.com/gianlucamazza/ragfs/pull/93))

### Deps

- Bump fuser from 0.16.0 to 0.18.0 ([#144](https://github.com/gianlucamazza/ragfs/pull/144))
[0.2.1]: https://github.com/gianlucamazza/ragfs/compare/v0.2.0...v0.2.1


## [0.2.0] - 2026-01-12

### Added

- Initial commit - RAGFS v0.2.0
- Add config loading, PDF image extraction, vision infrastructure, and .help file
- Add release automation with release-plz

### Fixed

- Resolve all clippy warnings and update toml to 0.9

