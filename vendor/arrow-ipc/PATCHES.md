# Vendored `arrow-ipc` 58.4.0

Published `arrow-ipc` 58.4.0 and 58.4.1 depend on `zstd ^0.13.0`. That
line is vulnerable to RUSTSEC-2026-0391, and it pulls `zstd-safe` 7.2.4
(RUSTSEC-2026-0398, RUSTSEC-2026-0403). Patched zstd is `>=0.14.3`;
patched zstd-safe is `>=8.2.0`. There is no 0.13.x / 7.2.x release.

`arrow-ipc` 60.1.0 takes `zstd ^0.14.0`, but `lancedb` 0.37.1 (and
0.41.0) still depend on `arrow-ipc ^58`. A lockfile-only
`cargo update -p zstd` cannot move 0.13.3 onto 0.14.3.

This directory is the 58.4.0 crate **library sources only** (benches
omitted) plus:

- `Cargo.toml`: `zstd` 0.13.0 → 0.14.3; rust/clippy lints allowed so CI
  `RUSTFLAGS=-Dwarnings` does not fail on unmodified upstream 58.4.0

Remove the `[patch.crates-io]` entry in the workspace `Cargo.toml` and
this directory when a crates.io arrow-ipc 58.x release depends on
zstd ≥ 0.14.3.
