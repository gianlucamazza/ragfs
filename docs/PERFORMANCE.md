# RAGFS performance and measurement

## Evidence status

No reproducible end-to-end performance report is published for v0.3.0 yet.
Earlier throughput, query latency, RAM and GPU speedup ranges in this document
were not linked to pinned runs and have been removed. They are not guarantees.
ADR-009 defines the comparison protocol; correctness CI is not a retrieval
quality benchmark. Do not infer retrieval accuracy from passing unit tests.

## Implemented behavior

- The default text model is `thenlper/gte-small`, with 384-dimensional vectors.
- Float32 vector payload alone is 384 × 4 = 1536 bytes per chunk. This excludes
  text, metadata, Lance storage/version overhead and search indexes.
- Cosine search can use best-effort IVF-PQ at 256 or more chunks. Failure falls
  back to exact search; L2/Dot remain exact. Measure actual recall as well as speed.
- Hybrid search combines text and vector retrieval. `[query].hybrid` defaults
  to true; CLI `--hybrid` forces it on. Disable it through configuration for a
  vector-only comparison.
- First use can download model files. Report download, cold model load, warm
  retrieval, and full CLI process latency separately.
- `ragfs index --force` rebuilds derived tables and the model fingerprint.
  It preserves source files and previous receipts. `force` is not a TOML key.

## Reproducible measurements

Record the ragfs commit, Cargo.lock hash, model revision and hashes, hardware,
OS, configuration, corpus hash, file/chunk counts, index revision, and whether
caches are warm. Run on a dedicated disposable index, not a production index.
Record failures and excluded files rather than silently dropping them.

```bash
ragfs --version
/usr/bin/time -v ragfs index /path/to/fixture --force
ragfs status /path/to/fixture --format json
/usr/bin/time -v ragfs query /path/to/fixture 'fixed query' --format json --save-receipt
```

CLI wall time includes process startup and model/store opening. It must not be
reported as warm in-process retrieval latency. Keep raw outputs and receipts;
report query count, mean, p50 and p95, together with retrieval recall and the
exact protocol. A shell loop starting new CLI processes does not pre-warm a
persistent model. Use `cargo bench -p ragfs` for the existing microbenchmarks;
these are distinct from ADR-009 end-to-end comparisons.

## Tuning

Use SSD storage and exclude generated content. Smaller chunks improve location
granularity but increase chunk count; overlap duplicates text. Larger embedding
batches trade memory for throughput. Measure these tradeoffs on the same corpus.
Do not assume a configured GPU preference proves that the built binary contains
a GPU backend or that a particular device is supported.

See [configuration](CONFIGURATION.md) for supported options,
[the roadmap](ROADMAP.md) for benchmark implementation status and
[ADR-009](ARCHITECTURE_DECISIONS.md#adr-009-transparent-memory-benchmark-harness)
for scoring and publication rules.
