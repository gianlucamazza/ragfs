# Vendored `lance-encoding` 10.0.0

Published `lance-encoding` 10.0.0 depends on `zstd ^0.13` (default
feature). That line is vulnerable to RUSTSEC-2026-0391, and it pulls
`zstd-safe` 7.2.4 (RUSTSEC-2026-0398, RUSTSEC-2026-0403). Patched zstd
is `>=0.14.3`; patched zstd-safe is `>=8.2.0`. There is no 0.13.x /
7.2.x release.

`lance-encoding` 13.0.0 still pins `zstd ^0.13`. 14.0.2 is the first
line that takes `zstd ^0.14`, and that requires `lancedb` 0.41 /
Lance 14. The workspace pin stays on `lancedb` 0.37.1 (0.38.0 does not
build with default features; see workspace `Cargo.toml`).

This directory is the 10.0.0 crate **library sources** (src, protos,
build.rs; benches omitted) plus:

- `Cargo.toml`: `zstd` 0.13 → 0.14.3; rust/clippy lints allowed so CI
  `RUSTFLAGS=-Dwarnings` does not fail on unmodified upstream 10.0.0
- `LICENSE`: Apache-2.0 text from lance-format/lance tag `v10.0.0` (the
  published crate tarball does not ship it). That tag has no NOTICE file.

Remove the `[patch.crates-io]` entry in the workspace `Cargo.toml` and
this directory when the workspace `lancedb` pin moves to a generation
that depends on lance-encoding ≥ 14.0.2.
