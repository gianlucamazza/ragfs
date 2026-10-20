# Transparent memory benchmark

ADR-009 phases 1–2: executable protocol/pin validation, frozen original synthetic
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

Scored BM25/vector/ragfs adapters (#196–#197), emotional-memory (#198), and public
datasets (#199–#201) remain separate phases. No performance or retrieval result
is claimed here. The optional LLM judge is rejected by the validator.

See `schemas/` for interchange schemas. The executable validator additionally
checks cross-record invariants and content hashes that JSON Schema cannot express.
