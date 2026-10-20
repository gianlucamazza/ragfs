# Transparent memory benchmark

ADR-009 phases 1–4: executable protocol/pin validation, frozen original synthetic
facts and the eight-step scenario. Python 3.11+ standard library only: there are
no third-party Python dependencies to resolve. The interpreter version and
repository commit must be recorded for any later scored run.

```bash
PYTHONPATH=benchmarks python -m ragfs_bench run --protocol benchmarks/protocol.toml --dry-run
PYTHONPATH=benchmarks python -m unittest discover -s benchmarks/tests -v
```

Dry-run verifies protocol fields, immutable pins and byte hashes, linear revision
chains, non-overlapping half-open intervals, and query/scenario references. A
failure exits nonzero. It does not measure retrieval quality or emit scores.
Fixture cardinality: one fact chain, two revisions, four queries, eight scenario
steps. These counts describe the frozen fixture, not experimental results.

`pins.toml` uses a content-addressed revision for original local fixtures; remote
sources must use their full Git/Hub revision. Fixture updates require a dedicated
PR with the new SHA-256 hashes in its commit message. Do not vendor public data.

`facts.answer` chooses the current revision from retrieved records only. Looking
up its explicit predecessor in the frozen corpus is allowed by ADR-009; selecting
the current revision from the whole corpus would leak the answer and is forbidden.

BM25/vector/ragfs adapters are implemented below. Emotional-memory (#198) and
public datasets (#199–#201) remain separate phases. No performance or retrieval
result is claimed by the implementation itself. The optional LLM judge is rejected by the validator.

See `schemas/` for interchange schemas. The executable validator additionally
checks cross-record invariants and content hashes that JSON Schema cannot express.

## Run the synthetic adapters

Build both binaries from the same clean checkout:

```bash
cargo build --locked -p ragfs --bin ragfs --example benchmark_snapshot
PYTHONPATH=benchmarks python -m ragfs_bench run \
  --protocol benchmarks/protocol.toml \
  --binary target/debug/ragfs --snapshot target/debug/examples/benchmark_snapshot \
  --model-manifest /path/to/gte-small-pin.json --output /path/to/new-run
```

The model manifest contains `model: "thenlper/gte-small"`, a full 40-hex Hub
`revision`, and `files` mapping each of `config.json`, `tokenizer.json`, and
`model.safetensors` to `{path, sha256}`. Paths are relative to the manifest.
Obtain all three from that revision, inspect and record hashes, and commit the
manifest in a dedicated pin PR before publishing results. No floating model
revision or invented hash is accepted. Files are copied into an isolated Hub
cache; the runner uses CPU, offline mode and a fresh index. Test embedders are
rejected. This command does not fetch public datasets or use API credentials.

`benchmark_snapshot` exports actual product chunks. Reference BM25 v1 uses
exactly those boundaries with k1=1.5, b=.75, positive Robertson IDF and Unicode
word tokenization, deterministic path/chunk-order tie breaks. Dense-only search
uses the same gte-small product index with hybrid disabled. Ragfs uses hybrid
and stores query receipts. These retrieval modes share corpus and queries.

The runner executes two ingestion phases and four queries; it verifies writes
advance revisions and reads leave them unchanged. Answers choose current facts
from retrieved records; only the explicit predecessor is looked up in the frozen
corpus. Every raw prediction and receipt is retained. Synthetic outputs are
per-case booleans/diagnostics, with no overall score or leaderboard.

Latency scopes differ: CLI adapters include startup, revision checks and receipt
I/O; BM25 runs in-process. These latencies must **not** be used to claim a speed
advantage. A separate persistent-process performance protocol would be required.
A local real-model smoke run completed on 2026-10-20: all 12 structured
answer checks passed (four queries across three systems). See
`validation/versioned-facts-2026-10-20.json` for the source commit, protocol hash
and observed write revisions. This tiny synthetic fixture is a functional
regression, not a retrieval-quality benchmark. No aggregate score is published.

`models/gte-small.json` records the exact Hub revision and downloaded file hashes.
Copy that manifest beside files fetched from
`https://huggingface.co/thenlper/gte-small/resolve/17e1f347d17fe144873b1201da91788898c639cd/`
(`config.json`, `tokenizer.json`, `model.safetensors`), then pass the copied
manifest to the command above. Weights are not vendored.
