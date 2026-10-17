# Vendored `candle-core` 0.11.0

Published `candle-core` 0.11.0 depends on `zip ^8.6.0`. That line is
vulnerable to RUSTSEC-2026-0367, RUSTSEC-2026-0368, and RUSTSEC-2026-0369
(patched in zip 9.0.1). Hugging Face has not yet released a crates.io
build that takes zip 9 (`huggingface/candle#4041`).

This directory is the 0.11.0 crate **library sources only** (tests,
benches, and examples omitted) plus the zip 9 API adjustments:

- `Cargo.toml`: `zip` 8.6.0 → 9.0.1; rust/clippy lints allowed so CI
  `RUSTFLAGS=-Dwarnings` does not fail on unmodified upstream 0.11.0
- `src/npy.rs`: `ZipFile::name()` now returns `ZipResult<Cow<str>>`
- `src/pickle.rs`: `ZipArchive::file_names()` now yields `ZipResult`
- `src/cpu/erf.rs`: drop `use std::f64` so `f64::INFINITY` is the
  associated constant (unblocks `-D deprecated`)

Remove the `[patch.crates-io]` entry in the workspace `Cargo.toml` and
this directory when a crates.io candle-core release depends on zip ≥ 9.0.1.
