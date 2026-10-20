# Architecture Decision Records

This document captures key architectural decisions made in RAGFS and the rationale behind them.

## Table of Contents

- [ADR-001: Local-First Embeddings with Candle](#adr-001-local-first-embeddings-with-candle)
- [ADR-002: LanceDB for Vector Storage](#adr-002-lancedb-for-vector-storage)
- [ADR-003: Propose-Review-Apply Pattern](#adr-003-propose-review-apply-pattern)
- [ADR-004: FUSE-Based Interface](#adr-004-fuse-based-interface)
- [ADR-005: Registry Pattern for Extractors and Chunkers](#adr-005-registry-pattern-for-extractors-and-chunkers)
- [ADR-006: Content-Addressed Storage with Blake3](#adr-006-content-addressed-storage-with-blake3)
- [ADR-007: Async-First Design with Tokio](#adr-007-async-first-design-with-tokio)
- [ADR-008: Index Revision Sidecar and Local Query Receipts](#adr-008-index-revision-sidecar-and-local-query-receipts)
- [ADR-009: Transparent Memory Benchmark Harness](#adr-009-transparent-memory-benchmark-harness)
- [ADR-010: Index Exclusion, Secret Handling, and Store Integrity](#adr-010-index-exclusion-secret-handling-and-store-integrity) (Accepted)
- [ADR-011: Multimodal Indexing (Images, Audio, Video)](#adr-011-multimodal-indexing-images-audio-video) (Accepted)
- [ADR-012: Native Block-Device Filesystem vs Semantic Volume](adr/012-native-filesystem-vs-semantic-volume.md) (Accepted)

---

## ADR-001: Local-First Embeddings with Candle

### Status
Accepted

### Context
RAGFS needs to generate vector embeddings for semantic search. Options considered:
1. **External API** (OpenAI, Cohere, etc.)
2. **Python ML framework** (sentence-transformers, etc.)
3. **Rust ML framework** (Candle, Burn, ONNX Runtime)

### Decision
Use **Candle** with the **gte-small** model for local embedding generation.

### Rationale

**Privacy:**
- All data stays on the user's machine
- No network requests after initial model download
- Suitable for sensitive codebases and documents

**Offline capability:**
- Works without internet after first run
- No dependency on external service availability
- Consistent performance regardless of network

**Cost:**
- No API fees or rate limits
- Predictable resource usage
- No per-query costs

**Candle specifically:**
- Pure Rust implementation
- Good performance on CPU
- Optional GPU acceleration
- Active development by Hugging Face
- Smaller binary than Python alternatives

### Trade-offs

**Pros:**
- Complete privacy
- No ongoing costs
- Works offline
- Fast local inference

**Cons:**
- Larger binary size (~100MB model)
- CPU-bound without GPU
- Model quality limited to local options
- Initial download required

### Alternatives Considered

| Alternative | Rejected Because |
|-------------|------------------|
| OpenAI API | Privacy concerns, ongoing costs, network dependency |
| sentence-transformers | Python dependency, larger runtime overhead |
| ONNX Runtime | More complex setup, less Rust-native |
| Burn | Less mature ecosystem at decision time |

---

## ADR-002: LanceDB for Vector Storage

### Status
Accepted

### Context
RAGFS needs efficient storage and retrieval of vector embeddings. Options considered:
1. **In-memory store** (simple Vec<f32>)
2. **SQLite with vector extension** (sqlite-vss)
3. **Dedicated vector database** (Qdrant, Milvus, Weaviate)
4. **Embedded vector database** (LanceDB, Chroma)

### Decision
Use **LanceDB** as the vector storage backend.

### Rationale

**Embedded:**
- No separate server process required
- Single binary deployment
- Simpler operational model

**Performance:**
- Fast ANN (Approximate Nearest Neighbor) search
- Built-in cosine IVF-PQ ANN indexing when the table is large enough (L2/Dot stay exact)
- Efficient for medium-scale datasets (1M+ vectors)

**Features:**
- Hybrid search (vector + full-text) built-in
- Columnar storage (Lance format)
- Good Rust bindings

**Reliability:**
- ACID transactions
- Crash recovery
- Consistent state

### Trade-offs

**Pros:**
- No external dependencies
- Fast similarity search
- Built-in hybrid search
- Good Rust integration

**Cons:**
- Larger dependency tree
- Less flexible than raw SQL
- Learning curve for Lance format

### Alternatives Considered

| Alternative | Rejected Because |
|-------------|------------------|
| In-memory | No persistence, memory limits |
| SQLite + vss | Less efficient for large vector sets |
| Qdrant | Requires separate server |
| Chroma | Python-first, less mature Rust bindings |

---

## ADR-003: Propose-Review-Apply Pattern

### Status
Accepted

### Context
RAGFS enables AI agents to perform file operations. We need a safety mechanism to prevent unintended changes.

### Decision
Implement a **Propose-Review-Apply** pattern for destructive semantic operations:
1. Agent proposes a plan (e.g., file organization)
2. User reviews the proposed actions
3. User explicitly approves or rejects
4. Only approved plans are executed

### Rationale

**Safety:**
- No automatic execution of destructive operations
- User retains final control
- Clear audit trail of proposed vs executed actions

**Reversibility:**
- All executed operations are reversible
- Undo support via operation IDs
- Trash-based soft delete

**Transparency:**
- Actions show reasoning and confidence scores
- Impact summary before execution
- Full visibility into what will change

### Implementation

```
Agent → create_plan() → Plan(pending)
                              ↓
User reviews .pending/<plan_id>
                              ↓
         approve() ──────────→ Execute with undo support
              │
              └── reject() ──→ Discard, no changes
```

### Trade-offs

**Pros:**
- Safe for autonomous agents
- User control preserved
- Auditable decisions

**Cons:**
- Extra step for simple operations
- Plans can expire or become stale
- Requires user interaction

---

## ADR-004: FUSE-Based Interface

### Status
Accepted

### Context
RAGFS needs an interface for users and agents to interact with semantic search and file operations.

Options:
1. CLI only
2. REST API server
3. FUSE filesystem
4. Library-only (SDK)

### Decision
Use **FUSE** (Filesystem in Userspace) as the primary advanced interface, with CLI for simple operations.

### Rationale

**Universal compatibility:**
- Works with any tool that reads/writes files
- No special SDK required
- Shell scripts, editors, agents all work

**Intuitive operations:**
- `cat .query/authentication` for search
- `echo "path" > .ops/.delete` for operations
- Standard Unix file operations

**Agent-friendly:**
- Agents can use standard file I/O
- JSON responses in files
- No HTTP client needed

### Implementation

```
/mountpoint/
├── real_files/           # Passthrough
└── .ragfs/               # Virtual control interface
    ├── .query/<text>     # Read: search results
    ├── .ops/             # Write: operations
    └── .result           # Read: operation results
```

### Trade-offs

**Pros:**
- Universal interface
- No new protocols
- Works with existing tools

**Cons:**
- Linux only (FUSE)
- Slight performance overhead
- Debugging more complex

### Alternatives Considered

| Alternative | Rejected Because |
|-------------|------------------|
| REST API | Requires HTTP client, port management |
| CLI only | Not suitable for agent integration |
| Library only | Limits language accessibility |

---

## ADR-005: Registry Pattern for Extractors and Chunkers

### Status
Accepted

### Context
RAGFS needs to support multiple file formats and chunking strategies. The system should be extensible.

### Decision
Use a **Registry Pattern** for both extractors and chunkers:
- `ExtractorRegistry` maps MIME types to extractors
- `ChunkerRegistry` maps content types to chunkers

### Rationale

**Extensibility:**
- New formats added without modifying core code
- Custom extractors can be registered
- Plugin-like architecture

**Separation of concerns:**
- Each extractor handles one format
- Chunkers are independent of extractors
- Clear responsibilities

**Testability:**
- Individual components testable in isolation
- Mock implementations for testing
- Easy to swap implementations

### Implementation

```rust
// Register extractors
registry.register("text", TextExtractor::new());
registry.register("pdf", PdfExtractor::new());

// Extract based on MIME type
let content = registry.extract(path, "application/pdf")?;
```

### Trade-offs

**Pros:**
- Easy to extend
- Clean architecture
- Good testability

**Cons:**
- Runtime dispatch overhead
- Registration required
- More complex than direct calls

---

## ADR-006: Content-Addressed Storage with Blake3

### Status
Accepted

### Context
RAGFS needs to track file changes to avoid redundant processing and maintain consistent state.

### Decision
Use **Blake3** hashing for content-addressed identification of files.

### Rationale

**Efficiency:**
- Only re-process files that actually changed
- Hash comparison faster than content comparison
- Incremental indexing support

**Blake3 specifically:**
- Extremely fast (~3 GB/s on modern CPUs)
- Cryptographically secure
- Parallel-friendly
- Pure Rust implementation

**Consistency:**
- Deterministic file identification
- Reproducible across restarts
- Stable references for undo/trash

### Implementation

```rust
let hash = blake3::hash(content);
let file_id = format!("{:x}", hash)[..16]; // First 16 chars
```

### Trade-offs

**Pros:**
- Very fast hashing
- Reliable change detection
- Cryptographic security

**Cons:**
- Full file read required for hash
- Storage for hash values
- Hash collisions (extremely rare)

---

## ADR-007: Async-First Design with Tokio

### Status
Accepted

### Context
RAGFS performs many I/O operations: file reading, database queries, network (for model download), filesystem events.

### Decision
Use **Tokio** async runtime with async-first API design.

### Rationale

**Concurrency:**
- Parallel file processing
- Non-blocking I/O
- Efficient resource utilization

**Tokio specifically:**
- Mature, well-tested runtime
- Excellent ecosystem support
- Good performance characteristics
- Multi-threaded executor

**API design:**
- All public APIs are async
- Consistent async/await usage
- Natural integration with async ecosystem

### Implementation

```rust
#[async_trait]
pub trait VectorStore: Send + Sync {
    async fn search(&self, query: SearchQuery) -> Result<Vec<SearchResult>>;
}
```

### Trade-offs

**Pros:**
- Efficient I/O handling
- Good concurrency model
- Modern Rust idioms

**Cons:**
- Async complexity
- Runtime overhead
- Learning curve

---

## ADR-008: Index Revision Sidecar and Local Query Receipts

### Status
Accepted

### Context
Issue #152 (idea from @Nomad-link-id / Igor Eduardo) needs a stable id for the
retrieval corpus and an optional local record of what a query returned. Open
choices: where to persist the id, its type, whether to bump
`CHUNKS_SCHEMA_VERSION`, receipt location, and whether to add list/show or FUSE
surfaces.

### Decision
1. **Revision is a `u64` counter** stored as `index_revision` on the existing
   `ragfs-schema.json` sidecar (next to `index.lance`). It is **not** a Lance
   column and **`CHUNKS_SCHEMA_VERSION` stays at 2**.
2. **Old indexes stay readable.** A sidecar without the field deserializes as
   `0`. `init` persists `1` without rewriting tables or forcing a reindex.
   Subsequent queries see the same value until an index write.
3. **Bump on content writes only:** `upsert_chunks` (non-empty),
   `delete_by_file_path`, and `update_file_path` (once). Reads (`search`,
   `hybrid_search`, `stats`, `get_*`, `init`) do not increment.
4. **Query JSON is additive.** Existing `query` / `results[]` fields are
   unchanged. New fields: `index_revision`, `ragfs_version`, `embedding_model`,
   and `receipt_path` only when a receipt is saved.
5. **Receipts are opt-in and local.** `ragfs query --save-receipt [PATH]` writes
   JSON under `<index-dir>/receipts/` by default
   (`~/.local/share/ragfs/indices/<hash>/receipts/`). No network, no telemetry,
   no config key, no list/show CLI, no FUSE virtual file — the issue did not
   ask for those.

### Rationale
- Sidecar metadata avoids a schema migration and a Lance rewrite.
- A counter is enough to detect “same index vs after a write” and is easy to
  test. A UUID would change identity without adding meaning.
- Default receipt path lives in the index directory so deleting the index
  deletes the receipts (“kept for as long as the index, and removed with it”).

### Alternatives considered

| Alternative | Rejected because |
|-------------|------------------|
| Bump `CHUNKS_SCHEMA_VERSION` to 3 | Not a table-schema change; would imply a Lance migration |
| UUID / content hash as revision | Harder to reason about; hash would need a full scan |
| Always write receipts | Issue asked for opt-in |
| FUSE `.revision` / receipt list CLI | Out of issue scope |

---

## ADR-009: Transparent Memory Benchmark Harness

### Status
Accepted (2026-10-19, owner)

### Context
Public discussion of agent-memory systems often treats a single headline
score as a ranking. The same benchmark can be reported with different
judges, prompts, seeds, dataset snapshots, and “strict” versus “lenient”
rules, so those scores are not comparable. ragfs and the sibling project
[emotional-memory](https://github.com/gianlucamazza/emotional-memory) can
distinguish themselves by **transparency of measurement**: a declared
protocol, pinned datasets, pinned (or absent) judge, and raw artefacts
anyone can re-run.

This ADR is design only. It does **not** implement a harness, run a
benchmark, or claim a result. Every measured quantity in a future run is
recorded as `TBD (to be measured)` until that run exists. No
implementation PR is opened until the owner accepts this ADR.

Sibling work already covers some corpora and must not be duplicated here.
emotional-memory documents its fidelity suite, comparative protocol,
LoCoMo addenda, and ES-MemEval / EvoEmo addendum in
[`docs/benchmarks.md`](https://github.com/gianlucamazza/emotional-memory/blob/main/docs/benchmarks.md)
and [`benchmarks/README.md`](https://github.com/gianlucamazza/emotional-memory/blob/main/benchmarks/README.md).
This harness **references those documents** for those studies and only
adds a shared, protocol-first runner for ragfs, shared baselines, and a
small synthetic *versioned facts* set that neither project owns today.

### Decision
Build a **transparent memory benchmark harness** (after this ADR is
accepted) that evaluates ragfs and emotional-memory against the same
pinned protocol. The product is a reproducible measurement record, not a
leaderboard entry.

### Goals and non-goals

**Goals**

1. Declare, in one machine-readable protocol file, the datasets, splits,
   seeds, versions, adapters, metrics, and (if any) judge used for a run.
2. Pin every third-party artefact by exact version **and** content hash;
   refuse to score on a mismatch.
3. Report lexical metrics (exact-match, token F1) and retrieval
   recall@k, plus wall-clock latency and declared cost per query, for
   every system under test.
4. Split **strict** and **lenient** scoring on every QA item (defined
   below). If an LLM judge is ever used, pin the model id and the prompt
   bytes, and always also report the non-judged scores.
5. Prove a *current value + what it replaced + source* answer on a small
   synthetic versioned-facts set, mapped onto ragfs
   (`index_revision` and opt-in receipts from ADR-008) and onto
   emotional-memory `Memory.metadata`.
6. Define baselines so a third party can re-run them from the protocol
   file with a single command.

**Non-goals**

- Ranking ragfs or emotional-memory against commercial memory products.
- Claiming “#1”, SOTA, or any unpublished number.
- Replacing emotional-memory’s pre-registered addenda (LoCoMo, ES-MemEval,
  MADial-Bench, fidelity). Those remain canonical in that repo.
- Changing ragfs retrieval, indexing, FUSE, or schema in this ADR.
- Shipping an LLM judge as a required dependency. A judge is optional and
  off by default.
- Redistributing third-party datasets inside this repository (especially
  LoCoMo, which is non-commercial). Fetch at run time, pin, do not vendor.
- Evaluating BEAM’s 10M-token split in the first accepted phases. That
  split is listed as a candidate only.

### Datasets

Candidate **public** benchmarks, verified against the paper and the
official repository or Hub record. Official sizes below are dataset
cardinality from those sources, not evaluation scores. Content hashes of
large Hub files are `TBD (to be measured)` until the first accepted
implementation PR records `sha256` at download time and refuses mismatch.

| Benchmark | Primary sources | Licence (verified) | Official size | Abilities tested | Pin |
|-----------|-----------------|--------------------|---------------|------------------|-----|
| **LongMemEval** (cleaned Hub snapshot) | Wu et al., ICLR 2025, [arXiv:2410.10813](https://arxiv.org/abs/2410.10813); code [xiaowu0162/LongMemEval](https://github.com/xiaowu0162/LongMemEval) (`main` @ `9e0b455f`); data [xiaowu0162/longmemeval-cleaned](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned) | Code MIT (repo `LICENSE`); dataset card `license: mit` | 500 questions; five abilities. Files: `longmemeval_oracle.json`, `longmemeval_s_cleaned.json` (~40 history sessions / ~115k tokens per the paper’s S setting), `longmemeval_m_cleaned.json` (~500 sessions) | Information extraction; multi-session reasoning; knowledge updates; temporal reasoning; abstention | Hub repo + file names above; `sha256` per JSON `TBD (to be measured)`. Prefer the **cleaned** Hub files (dataset card, 2025-09), not the original noisy histories. Official eval script: `src/evaluation/evaluate_qa.py` (LLM labeler documented there as `gpt-4o`; this harness does not inherit that judge unless a later phase pins it). |
| **BEAM** | Tavakoli et al., ICLR 2026, [arXiv:2510.27246](https://arxiv.org/abs/2510.27246); code [mohammadtavakoli78/BEAM](https://github.com/mohammadtavakoli78/BEAM) (`main` @ `b2da22ea`); data [Mohammadta/BEAM](https://huggingface.co/datasets/Mohammadta/BEAM) and [Mohammadta/BEAM-10M](https://huggingface.co/datasets/Mohammadta/BEAM-10M) | Code MIT (`LICENSE`); **benchmark data CC BY-SA 4.0** (repo README + Hub tags) | 100 conversations and 2000 validated probing questions. Split: 20 × 128K, 35 × 500K, 35 × 1M, 10 × 10M tokens | Ten abilities: abstention; contradiction resolution; event ordering; information extraction; instruction following; knowledge update; multi-session reasoning; preference following; summarization; temporal reasoning | Hub revision + per-split artefact `sha256` `TBD (to be measured)`. First scored split after acceptance: **128K only**. 10M is out of the first phases. Upstream eval uses an LLM judge (`src/evaluation/run_evaluation`); this harness reports lexical + retrieval metrics first. |
| **LoCoMo** | Maharana et al., ACL 2024, [doi:10.18653/v1/2024.acl-long.747](https://doi.org/10.18653/v1/2024.acl-long.747); [snap-research/locomo](https://github.com/snap-research/locomo) (`main` @ `3eb6f2c5`); released file `data/locomo10.json` (git blob `d95b872480b413d935821fdc3c84f8a8f5f29e73`) | **CC BY-NC 4.0** (`LICENSE.txt`) | Official release: **10 conversations** in `locomo10.json` (a subset of an earlier 50-conversation preprint dump). Paper: very long-term dialogues, QA + event summarization + multimodal dialog; QA types: single-hop, multi-hop, temporal, open-domain/commonsense, adversarial | Long-term conversational QA; event summarization (out of harness v1 unless a later phase opts in); evidence-linked retrieval | Fetch `locomo10.json` from the official repo at the commit above; `sha256` `TBD (to be measured)`. **Do not vendor** in ragfs (non-commercial licence). For emotional-memory’s existing LoCoMo studies, cite [`benchmarks/README.md`](https://github.com/gianlucamazza/emotional-memory/blob/main/benchmarks/README.md) addenda S1 / J / L rather than re-running a second unpublished protocol. |
| **ES-MemEval / EvoEmo** (reference only) | Chen et al., WWW 2026, [arXiv:2602.01885](https://arxiv.org/abs/2602.01885), [doi:10.1145/3774904.3792143](https://doi.org/10.1145/3774904.3792143); [slptongji/ES-MemEval](https://github.com/slptongji/ES-MemEval) `v1.0.0` tree `69262420`; Zenodo [10.5281/zenodo.18338564](https://doi.org/10.5281/zenodo.18338564) | **CC BY-4.0** (Zenodo record, as recorded in emotional-memory `benchmarks/datasets/esmemeval/ATTRIBUTION.md`) | Official artefact (hash-pinned in emotional-memory): 18 seekers, 401 sessions, 1427 QA items in `evo_emo.json`. The paper’s reported QA count differs from the released file; the sibling project treats the **hash-pinned artefact** as ground truth. | Information extraction; temporal reasoning; conflict detection; abstention; user modeling (QA, summarization, dialogue generation) | **Do not duplicate.** Pin and protocol live in emotional-memory: `EVO_EMO_SHA256 = f30698e87fddaeff51270a666c654da604f487a3456ec60d2b6ae08a6fecd420` in `benchmarks/esmemeval/dataset.py`, pre-registration `benchmarks/preregistration_addendum_x2_esmemeval_third_party.md`. This ragfs ADR only *points at* those files. |
| **Versioned facts (synthetic, this ADR)** | Owned by ragfs; created in a later PR after acceptance | **CC BY-4.0**, original text, no third-party dialogue | Small by design. Exact chain and query counts are `TBD (to be measured)` at dataset freeze. Coverage required: current, superseded, unknown, and time-travel queries. Not a leaderboard set. | Current value; superseded value; source/provenance; `valid_from` / `valid_to`; abstention when no current fact | Frozen JSONL in-tree at first implementation PR; `sha256` recorded in the protocol pin file. |

MADial-Bench (He et al., NAACL 2025, [arXiv:2409.15240](https://arxiv.org/abs/2409.15240); MIT; already vendored and hash-pinned in emotional-memory Addendum X) is **not** a first-wave target for this harness. Point at
[`benchmarks/comparative/protocol.md`](https://github.com/gianlucamazza/emotional-memory/blob/main/benchmarks/comparative/protocol.md)
and the X addendum instead of copying that study.

**Pinning method (all datasets).** A `pins.toml` (name illustrative) lists:
`name`, `uri`, `git_commit` or Hub revision, `path`, `sha256`, and
`license`. The runner computes `sha256` of the bytes on disk and **exits
non-zero** on mismatch, matching emotional-memory’s ES-MemEval loader.
Pins are updated only in a dedicated PR with the new hash in the commit
message. No floating `latest` tags.

### Versioned facts

Public long-term memory suites test knowledge *updates* (LongMemEval
`knowledge-update`, BEAM `Knowledge Update`) but do not require the
system to return **current value + what it replaced + source** as a
structured triple. That query is the gap this synthetic set fills.

#### Data model

Each record is one *fact revision*:

```text
FactRevision
  fact_id        stable key (e.g. "user.employer")
  revision_id    unique id for this version
  value          string | null
                 (null is the deletion sentinel; otherwise the payload)
  supersedes     revision_id of the previous version, or null
  valid_from     RFC 3339 UTC
  valid_to       RFC 3339 UTC or null (open interval)
  source         { uri: string, kind: string, recorded_at: RFC 3339 UTC }
                   kind ∈ {user-utterance, document, system}
  provenance     free-form citation of the ingest artefact
                 (path, session id, turn id)
```

Chains are linear: at most one successor per `revision_id`. Overlapping
`valid_from`/`valid_to` on the same `fact_id` is a dataset error; the
loader rejects it. A deleted fact is a revision whose `value` is `null`
and whose `valid_to` is set.

#### Query semantics

For a query time `t` (default: now) and `fact_id`:

1. **Current** — the unique revision where
   `valid_from ≤ t` and (`valid_to` is null or `t < valid_to`).
2. **Replaced** — that revision’s superseded `value`, or `null` if
   `supersedes` is null.
3. **Source** — the current revision’s `source` object (`uri` and `kind`).

The required answer shape (every adapter, every item):

```json
{
  "current": "string or null",
  "replaced": "string or null",
  "source": { "uri": "string or null", "kind": "string or null" }
}
```

`current` and `replaced` are `string | null`. `source` is always an
object with `uri` and `kind` (`string | null` each). On **abstention**
(no revision valid at `t`, or unknown `fact_id`):
`current`, `replaced`, `source.uri`, and `source.kind` are all `null`.
The system must not invent a value.

Gold comparison uses the **Metrics** normalizers below. `current` and
`replaced` use `norm_strict` / `norm_lenient` **without** English-article
stripping (fact values may contain words like “The”). `source.uri` and
`source.kind` are identity matches after JSON parse (no case-fold, no
article stripping). The Metrics table is canonical; this section does
not define a second lenient rule.

#### Mapping onto ragfs (ADR-008)

Each `FactRevision` is a small UTF-8 file under the indexed tree, e.g.
`facts/{fact_id}/{revision_id}.md`, with YAML front matter carrying the
fields above and a body that states the value in prose (so embedding and
FTS have text). Ingest is ordinary `ragfs index`.

- **`index_revision`.** Every ingest or delete that writes chunks must
  bump the sidecar counter from ADR-008. The harness records
  `index_revision` before and after each versioned write and fails the
  case if the counter did not increase on a content write, or *did*
  increase on a read-only query.
- **Receipts.** Each versioned-facts query runs
  `ragfs query --format json --save-receipt`. The receipt (query, UTC
  timestamp, `index_revision`, `ragfs_version`, `embedding_model`,
  `results[]`) is copied into the run’s `raw/` directory. The test
  asserts that the **current** revision’s file appears among `results`
  for in-scope current-value queries (retrieval gold). History-only
  queries (explicit “what did it replace?”) must retrieve either the
  current file (if it embeds `supersedes`) or the superseded file.
- ragfs has no first-class `supersedes` column today. The harness must
  **not** pretend otherwise: structured current/history answers are
  assembled by the ragfs *adapter* from retrieved files’ front matter,
  not by a new Lance schema. A later ADR may propose store-level
  versioning; that is out of scope here.

#### Mapping onto emotional-memory

emotional-memory stores a `Memory` with `content`, `tag` (affective
fingerprint, including `timestamp`), and a free-form `metadata` dict
(`src/emotional_memory/models.py`). There is no first-class
`supersedes` / `valid_from` field. The harness adapter:

- `encode()`s one `Memory` per `FactRevision`, with `content` holding
  the prose value and `metadata` holding `fact_id`, `revision_id`,
  `supersedes`, `valid_from`, `valid_to`, `source`.
- Selects **current** by filtering `metadata` on `[valid_from, valid_to)`
  at query time `t`, then `retrieve()`s among that subset (or retrieves
  then filters — the adapter must declare which, in the protocol).
- Walks `metadata["supersedes"]` for the replaced value and copies
  `metadata["source"]`.

Affective scoring is **not** part of the versioned-facts gold. The
comparative affect protocol stays in emotional-memory
[`benchmarks/comparative/protocol.md`](https://github.com/gianlucamazza/emotional-memory/blob/main/benchmarks/comparative/protocol.md).

#### Test design that proves “current + history”

A single frozen scenario (illustrative ids; not a measured result):

1. Ingest `employer@r1` = `"Globex"` at `t0`, source `{uri: "s1", kind: "user-utterance"}`.
2. Query at `t0+`: gold
   `{current: "Globex", replaced: null, source: {uri: "s1", kind: "user-utterance"}}`.
3. Ingest `employer@r2` superseding `r1`, value `"Acme"`, `valid_from = t1`,
   source `{uri: "s2", kind: "user-utterance"}`.
4. Query at `t1+`: gold
   `{current: "Acme", replaced: "Globex", source: {uri: "s2", kind: "user-utterance"}}`.
   Retrieval gold is `r2` only (step 8). `replaced: "Globex"` is filled by
   following `r2.supersedes` to `r1` in the adapter’s store or in the
   frozen dataset — a lookup, not a second retrieval hit.
5. Time-travel query at `t` with `t0 ≤ t < t1`: gold
   `{current: "Globex", replaced: null, source: {uri: "s1", kind: "user-utterance"}}`.
6. Unknown `fact_id`: gold
   `{current: null, replaced: null, source: {uri: null, kind: null}}`.
   Retrieval gold is empty; the item is **excluded** from recall@k
   aggregates (see Metrics), not scored as zero.
7. For ragfs: assert `index_revision` monotonicity on steps 1 and 3, and
   persist receipts for steps 2, 4, 5, 6.
8. For both adapters: retrieval gold for step 4 includes the `r2`
   artefact; step 5 includes the `r1` artefact.

Pass/fail is boolean per case. No aggregate “score” is published for
this set beyond case counts `TBD (to be measured)` after a run exists.

### Metrics

Reported **per system, per dataset split, per ability tag**. Values in
any published artefact are `TBD (to be measured)` until a run is
committed.

Two named normalizers are shared by every split. There is no per-section
override except the two exclusions listed after the table.

- `norm_strict`: Unicode NFKC, then trim. Case-fold off.
- `norm_lenient`: `norm_strict`, then Unicode case-fold, then collapse
  internal whitespace to a single space. For **free-text QA only**
  (LongMemEval, BEAM, LoCoMo), also strip leading English articles
  `a` / `an` / `the`. Versioned-facts `current` / `replaced` use
  `norm_lenient` **without** article stripping. `source.uri` /
  `source.kind` never use a normalizer (identity after JSON parse).

| Metric | Definition | Notes |
|--------|------------|-------|
| **Exact-match (strict)** | 1 iff `norm_strict(prediction) == norm_strict(gold)` | Primary lexical metric. Null equals null. |
| **Exact-match (lenient)** | 1 iff `norm_lenient(prediction) == norm_lenient(gold)` | Never substitute for strict. Always publish both. |
| **Token F1 (strict / lenient)** | Bag-of-tokens precision/recall/F1 against gold; tokenize on whitespace after the same named normalizer as the EM variant | Aligns with LoCoMo’s `task_eval/evaluation.py` F1 path; do not copy unpublished scores. |
| **Retrieval recall@k** | See the gold-id and aggregation rules below. Values `TBD (to be measured)` | `k` is pinned in the protocol (default `k=5` unless a dataset’s official script fixes another k; then **that** k is used and named). |
| **Latency per query** | Wall-clock seconds: ingest excluded; per-query retrieve+answer included. Report mean / p50 / p95 as `TBD (to be measured)` | Measured on the declared hardware in `environment`. |
| **Cost per query** | Sum of declared API/tool charges for that query in USD, or `0` for fully local runs. If unknown, `null` and a reason string | Local ragfs embeddings after model download are `0`. An LLM judge, if enabled, **must** be included. |

**Gold evidence ids (per dataset).** Declared in the protocol; defaults:

- LongMemEval: session ids in `answer_session_ids`. Optional turn-level
  gold (turns with `has_answer: true`) is a named protocol variant, not
  the default.
- LoCoMo: dialog ids in `qa[].evidence`.
- Versioned facts: file path or memory id of each gold `FactRevision`.
- BEAM: the probing-question evidence pointers shipped with that split,
  named in the pin file when the split is added.

**Empty gold.** Items with an empty evidence list are **excluded** from
every retrieval aggregate (not scored as 0). They remain in EM/F1.
This covers LoCoMo `qa[].evidence: []`, LongMemEval abstention items
(`question_id` suffix `_abs`; the official README also skips them for
retrieval), and versioned-facts abstention (unknown `fact_id` / no
revision valid at `t`).

**Multi-evidence.** Let `G` be the gold id set and `R_k` the retrieved
ids in rank `1..k`. Report three columns, all `TBD (to be measured)`
until a run exists:

- `recall@k_any`: 1 iff `G ∩ R_k` is non-empty.
- `recall@k_all`: 1 iff `G ⊆ R_k`.
- `recall@k_frac`: `|G ∩ R_k| / |G|`.

The **primary published retrieval metric** is `recall@k_all` when
`|G| > 1`, and `recall@k_any` when `|G| = 1` (the two coincide).
`recall@k_frac` is always reported alongside. A single “at least one
id” number is not sufficient for multi-evidence items.

**Strict versus lenient** applies to EM and F1 only. Ability-tagged
macro-averages are unweighted across items that are **in** that metric’s
denominator; micro-averages use the same denominator rule. Neither is a
leaderboard rank.

**LLM judge (optional, off by default).** If a future accepted phase
enables a judge:

1. Pin `provider`, `model` id, `temperature`, and the **full prompt
   template** (hash of the prompt file in `pins.toml`).
2. Store the raw judge verdict per item under `raw/`.
3. Publish **judged** accuracy **and** the non-judged EM/F1/recall@k on
   the same predictions. Never publish judged scores alone.
4. LongMemEval’s upstream `evaluate_qa.py` and BEAM’s
   `src/evaluation/run_evaluation` are cited as *their* protocols, not
   adopted until pinned as in (1)–(3).

No “expected” accuracy, no estimated latency, no estimated cost.

### Baselines

Each baseline is an **adapter**: ingest a document/session stream, answer
a query, emit `{prediction, retrieved_ids, latency_s, cost_usd}`. Anyone
can re-run by implementing the same interface. Default adapters after
acceptance:

| Adapter id | What it is | How to re-run |
|------------|------------|---------------|
| `bm25` | Lexical only. Reference: BM25 over the same chunking as the ragfs adapter (chunker settings copied from the protocol). Implementation may use LanceDB FTS or a pinned `rank-bm25` version; the protocol names the crate/wheel and version. **No vectors.** | Protocol `systems.bm25`; no GPU. |
| `vector` | Dense cosine only, **same embedder** as ragfs default (`gte-small`, 384-d, local Candle) unless the protocol names another pinned model. **No FTS, no hybrid.** | Protocol `systems.vector`; model files pinned by Hub revision + `sha256`. |
| `ragfs` | Product path: `ragfs index` + `ragfs query --format json` with protocol `[query].hybrid` (default hybrid on, matching current docs). Receipts on for versioned-facts. | Pinned ragfs git SHA in the results file. |
| `emotional-memory` | Product path: `EmotionalMemory.encode` / `retrieve` as in the sibling README, with the adapter’s declared embedder (must match the protocol). Affect weights follow that repo’s shipped defaults unless the protocol overrides them. | Pinned emotional-memory git SHA. For LoCoMo / ES-MemEval / MADial-Bench, **prefer citing** that repo’s addenda rather than a second protocol. |

Optional later adapters (not in phase 1): recency-only, ragfs vector-only
via `--hybrid` off, emotional-memory `retrieve_query_gated()`. Each new
adapter is its own PR.

Fairness rules: shared seed, shared chunk boundaries where the system
consumes files (ragfs, bm25, vector), shared query text. Conversational
memory (emotional-memory) may ingest turns rather than files; the
protocol records that difference as a threat to validity, not as a hidden
advantage.

### Reproducibility

- **Single command** (name fixed at implementation, illustrative):
  `python -m ragfs_bench run --protocol protocol.toml`. One process, one
  exit code. A `--dry-run` loads pins and adapters without scoring.
- **Seeds.** Protocol `seed` (integer) is passed to every RNG the
  harness owns. Dataset order is shuffled only if the protocol says so
  (default: official order).
- **Pinned dependencies.** A lockfile (Python) and the ragfs
  `Cargo.lock` git SHA. The results file records both. No unpinned
  `pip install` in the published command.
- **Raw outputs.** Every prediction, receipt, and judge payload (if any)
  is written under `raw/{system}/{dataset}/{item_id}.json` and is not
  deleted by the summary step.
- **Results file.** JSON, schema version 1. Metrics are **not** a flat
  object: each row is one `(system, dataset, split, ability)` cell.
  There is no top-level overall score.

```json
{
  "schema_version": 1,
  "protocol_id": "ragfs-memory-bench-v1",
  "protocol_sha256": "TBD (to be measured)",
  "git_sha": "TBD (to be measured)",
  "git_dirty": false,
  "timestamp_utc": "TBD (to be measured)",
  "environment": {
    "os": "TBD (to be measured)",
    "arch": "TBD (to be measured)",
    "cpu_model": "TBD (to be measured)",
    "python": "TBD (to be measured)",
    "ragfs_version": "TBD (to be measured)",
    "emotional_memory_git_sha": "TBD (to be measured)"
  },
  "pins": [],
  "systems": ["bm25", "vector", "ragfs", "emotional-memory"],
  "judge": null,
  "metrics": [
    {
      "system": "ragfs",
      "dataset": "longmemeval-cleaned",
      "split": "oracle",
      "ability": "knowledge-update",
      "n_items": "TBD (to be measured)",
      "n_items_retrieval": "TBD (to be measured)",
      "exact_match_strict": "TBD (to be measured)",
      "exact_match_lenient": "TBD (to be measured)",
      "token_f1_strict": "TBD (to be measured)",
      "token_f1_lenient": "TBD (to be measured)",
      "recall_at_k_any": "TBD (to be measured)",
      "recall_at_k_all": "TBD (to be measured)",
      "recall_at_k_frac": "TBD (to be measured)",
      "latency_s_per_query": "TBD (to be measured)",
      "cost_usd_per_query": "TBD (to be measured)"
    }
  ]
}
```

`git_sha` is the harness repo commit that produced the file.
`git_dirty` must be `false` for any published artefact. `judge` is
`null` when the judge is off; otherwise it names the pinned model and
prompt hash **and** each metrics row also has a sibling
`*_without_judge` field for EM/F1 (never judged scores alone).
`n_items_retrieval` may be lower than `n_items` because empty-gold
items are excluded from recall@k. Ability `"__all__"` is the
micro-average over items in that system/dataset/split; it is not a
rank.

### Threats to validity and publication

**Threats**

- **Adapter mismatch.** ragfs is file RAG; emotional-memory is turn-level
  affective memory. Cross-system deltas mix architecture with ingest
  format. Mitigate: publish per-system numbers only; never a single
  “winner”.
- **Judge variance.** LLM judges are not stable across models or prompts.
  Mitigate: judge off by default; dual reporting if enabled.
- **Dataset licence.** LoCoMo is CC BY-NC 4.0: evaluation is
  non-commercial; do not redistribute `locomo10.json`. BEAM data is
  CC BY-SA 4.0: derivatives share-alike. LongMemEval-cleaned is MIT per
  the Hub card. ES-MemEval is CC BY-4.0 via Zenodo.
- **Snapshot drift.** LongMemEval has an original and a cleaned Hub
  dump; LoCoMo dropped 40 of 50 conversations between preprint and
  ACL release. Mitigate: pins, not “LongMemEval” as a bare name.
- **Contamination / fillers.** LongMemEval filler sessions include
  ShareGPT and UltraChat material (upstream README). Treat as a
  documented limitation, not a score adjustment.
- **English-only.** All first-wave public sets are English. Do not
  generalize.
- **Synthetic gold.** Versioned-facts gold is author-written. It tests
  the data model, not real-user memory.
- **Cost opacity.** Local runs have zero API cost but non-zero energy;
  the schema records API USD only, and says so.
- **BEAM generation.** Conversations are LLM-generated then
  human-validated (paper). Residual generation artefacts are possible.

**Publication**

- Publish the protocol file, `pins.toml`, the results JSON, and a
  pointer to `raw/` (or a tarball hash). No leaderboard table, no
  ranking language, no comparison charts that imply a winner.
- Human-readable notes may quote the protocol and the
  `TBD (to be measured)` placeholders until a run exists. After a run,
  quote only numbers that appear in the committed results file.
- Cross-link emotional-memory addenda instead of restating their
  verdicts. Do not import those verdicts into ragfs docs as ragfs
  results.
- A run that cannot reproduce from the single command is not
  publishable.

### Phased plan

Each phase is a **small PR**. No phase after this one starts until the
owner **accepts this ADR** (status → Accepted). No phase publishes a
metric value that was not produced by that phase’s command.

| Phase | PR (after acceptance) | Scope |
|-------|------------------------|--------|
| **0** | This PR | ADR only. Status Accepted. No code, no config, no CI. |
| **1** | Protocol + pin schema | Add `protocol.toml` / `pins.toml` schemas and the results JSON schema as docs (or a schema-only crate/module). Dry-run that checks schema, not scores. |
| **2** | Synthetic versioned-facts v0 | Freeze the JSONL, `sha256`, and the eight-step test design as fixtures. No public datasets. |
| **3** | `bm25` + `vector` adapters | Ingest the synthetic set only. Report EM/F1/recall@k/latency/cost as `TBD (to be measured)` until the command is run in CI or a documented local log. |
| **4** | `ragfs` adapter | Wire `index` / `query --save-receipt`; assert `index_revision` behaviour from ADR-008. Synthetic set only. |
| **5** | `emotional-memory` adapter | Synthetic set only. Document the `metadata` mapping. Do not re-run sibling addenda. |
| **6** | LongMemEval-cleaned oracle split | Fetch + pin `longmemeval_oracle.json`; score with EM/F1/recall@k; judge still off. |
| **7** | LoCoMo fetch (no vendor) | Fetch `locomo10.json` under the CC BY-NC 4.0 terms; pin sha256; lexical metrics only. Point at emotional-memory LoCoMo addenda for that project’s own protocol. |
| **8** | BEAM 128K | Fetch + pin the 128K split (CC BY-SA 4.0); same lexical + retrieval metrics. |
| **9** | Optional judge | Only if a separate ADR or an explicit owner request pins model + prompt. Dual reporting required. |

Phases 6–8 may be reordered or dropped by the owner; they must not be
merged without recorded pins. A BEAM 10M phase is **not** scheduled.

### Rationale
A protocol-first harness is the smallest change that makes a future
number interpretable. Pinning datasets and judges is cheaper than
arguing about someone else’s screenshot of a benchmark. Keeping
emotional-memory’s ES-MemEval / LoCoMo work as citations avoids two
conflicting “official” numbers for the same sibling project. A synthetic
versioned-facts set is the only way to test current+history+source
without pretending LongMemEval or BEAM already require that triple.

### Trade-offs

**Pros**

- Re-runnable by third parties.
- Strict/lenient split makes “we used a judge” visible.
- ADR-008 receipts become part of the measurement, not a side channel.
- Licence constraints are explicit (especially LoCoMo NC).

**Cons**

- First-wave public sets are conversational; ragfs is a filesystem RAG.
  Cross-system comparison stays qualified.
- No headline ranking; some readers will call that incomplete.
- Hash pins go stale when upstream rewrites Hub files; updates need PRs.

### Alternatives considered

| Alternative | Rejected because |
|-------------|------------------|
| Publish a leaderboard on LongMemEval / BEAM | The motivating failure mode is incomparable scores, not missing ranks |
| Treat emotional-memory addenda as this harness’s results | Different protocol, seeds, and research questions; would mix claims |
| Vendor all datasets in ragfs | LoCoMo is CC BY-NC 4.0; BEAM is CC BY-SA 4.0; unnecessary copies |
| Require an LLM judge from day one | Judge identity is the usual hidden variable; lexical metrics first |
| Schema-level `supersedes` in Lance / Memory | Out of scope; would be a separate accepted ADR per project |
| Implement the harness in this PR | Owner has not accepted the design |

### Sources verified (primary only)

Checked against the official paper, repository, Hub card, or Zenodo
record while writing this ADR (dates in those records, not this file’s
clock):

- Wu et al., *LongMemEval*, ICLR 2025, arXiv:2410.10813; GitHub
  xiaowu0162/LongMemEval (`LICENSE` MIT; `main` `9e0b455f`); Hub
  `xiaowu0162/longmemeval-cleaned` (`license: mit`).
- Tavakoli et al., *Beyond a Million Tokens* (BEAM), ICLR 2026,
  arXiv:2510.27246; GitHub mohammadtavakoli78/BEAM (code MIT, data
  CC BY-SA 4.0; `main` `b2da22ea`); Hub `Mohammadta/BEAM`,
  `Mohammadta/BEAM-10M`.
- Maharana et al., *Evaluating Very Long-Term Conversational Memory of
  LLM Agents*, ACL 2024, doi:10.18653/v1/2024.acl-long.747; GitHub
  snap-research/locomo (`LICENSE.txt` CC BY-NC 4.0; `main` `3eb6f2c5`;
  `data/locomo10.json` blob `d95b8724`).
- Chen et al., *ES-MemEval*, WWW 2026, arXiv:2602.01885,
  doi:10.1145/3774904.3792143; GitHub slptongji/ES-MemEval `v1.0.0`
  `69262420`; Zenodo 10.5281/zenodo.18338564; sibling pin
  `EVO_EMO_SHA256` in gianlucamazza/emotional-memory
  `benchmarks/esmemeval/dataset.py`.
- He et al., *MADial-Bench*, NAACL 2025, arXiv:2409.15240 — cited only
  as already covered by emotional-memory Addendum X, not as a first-wave
  harness target.
- ragfs ADR-008 (`index_revision`, opt-in receipts) in this file.
- emotional-memory `docs/benchmarks.md`, `benchmarks/README.md`,
  `benchmarks/comparative/protocol.md`, `benchmarks/datasets/README.md`,
  `src/emotional_memory/models.py` (`Memory.metadata`).

Social posts are not sources.

---

## ADR-010: Index Exclusion, Secret Handling, and Store Integrity

### Status
Accepted (2026-10-20, owner)

### Context
A read-only review of the community forks
[sophie4869/ragfs](https://github.com/sophie4869/ragfs) and
[manojtummala/SemPOSIX](https://github.com/manojtummala/SemPOSIX) against
`gianlucamazza/ragfs` `main` @ `bcb1611` (v0.2.2) found that the default
index walk can ingest secret files, that two exclude lists disagree, and
that the store records an embedding model id without comparing it on
open. SemPOSIX scoped search is already on `main` (#60); this ADR does
not re-port that work. The fork is a source of *ideas*, not a patch to
apply wholesale. The design below starts from current `main`, prior art,
and a threat model, then sequences small PRs.

This ADR does not implement code, change defaults, or publish an
advisory. Implementation follows in the sequenced PRs below. It does
not invent benchmark or performance numbers.

#### Verified on `main` @ `bcb1611`

**Two disagreeing default exclude lists.** The CLI / FUSE / documented
config path uses `crates/ragfs/src/config.rs` `default_exclude()`
(lines 231–241): `**/node_modules/**`, `**/.git/**`, `**/target/**`,
`**/__pycache__/**`, `**/*.pyc`, `**/.venv/**`, `**/venv/**`, `**/.env`.
There is **no** `**/.*`. `Config::to_indexer_config` copies
`self.index.exclude` into `IndexerConfig` (`config.rs` 133–142). Both
`ragfs index` and `ragfs mount` call that converter (`main.rs` 475,
589). `docs/CONFIGURATION.md` (lines 100–112) documents this weaker
list.

`IndexerConfig::default()` (`crates/ragfs-index/src/indexer.rs` 48–66)
is a different list: `**/.*`, `**/.git/**`, `**/node_modules/**`,
`**/target/**`, `**/__pycache__/**`, `**/*.lock`.
`docs/USER_GUIDE.md` (lines 137–145) documents *this* list. Library
callers that do not go through `Config` get the stronger list; the
product CLI does not.

**`**/.*` matches hidden basenames only.**
`path_matches_pattern` special-cases `**/.*` and `.*` to the last path
component (`indexer.rs` 107–112). The unit test
`test_path_matches_exclude_and_include_patterns` asserts that
`/tmp/.tmpABC/file.txt` is *not* excluded (`indexer.rs` 1514–1517).
Consequence:

- `ragfs index ~` (CLI list, no `**/.*`): `.ssh/id_rsa`,
  `.aws/credentials`, `.netrc`, `.npmrc`, `.obsidian/*` are eligible.
- `IndexerConfig::default()`: a *child* hidden directory such as
  `proj/.ssh` is skipped in `scan_directory` because its own basename
  matches; but a hidden *index root* (for example `~/.notes`) is not
  itself filtered by `visit_dir`, so `~/.notes/todo.md` and
  `~/.ssh/id_rsa` (if that directory is the root) are indexed.
- The watcher (`crates/ragfs-index/src/watcher.rs` 106–111) drops
  events whose *basename* starts with `.`, independently of exclude
  lists. `.aws/credentials` still generates events.

**Secrets become searchable.** Chunks store file text. `ragfs query`
returns `ResultItem.content` (`crates/ragfs/src/receipt.rs` 15–21).
FUSE `.query/<text>` returns truncated content
(`crates/ragfs-fuse/src/filesystem/mod.rs` 297–300). MCP
`ragfs_search` returns `page_content[:500]`
(`crates/ragfs-mcp/src/ragfs_mcp/server.py` 887–889). MCP does not
walk the tree; it opens the Lance index the CLI wrote
(`docs/MCP.md`). The on-disk index under
`~/.local/share/ragfs/indices/` is plaintext.

**No secret-file denylist beyond `**/.env`.** No `.ragfsignore`.
Reindex does not purge newly excluded paths (`process_file` returns
early without `delete_by_file_path` when `should_process_path` is
false; `indexer.rs` 671–674). Oversized files *are* deleted
(`indexer.rs` 676–684).

**Embedding model is recorded, not compared.**
`SchemaSidecar.embedding_model` is written when missing
(`crates/ragfs-store/src/schema.rs` 26–28;
`lancedb.rs` `sidecar_with_revision` 369–371). `init` compares
**dimension only** (`ensure_embedding_dim_matches`, `lancedb.rs`
103–111, called from `ensure_chunks_schema_v2` 508). There is a dim
mismatch test (`lancedb.rs` 1903–1921) and no model-id mismatch test.
Two 384-d models therefore mix silently. ADR-009 pins and ADR-008
receipts already name `embedding_model` as a string; a mixed index
makes those pins meaningless.

**FTS is created once on an empty table.** `LanceStore::init` builds
the FTS index when the chunks table is first created (`lancedb.rs`
838–852). `upsert_chunks_inner` refreshes the **ANN** index only
(453–455). Whether Lance hybrid search sees rows inserted after that
empty FTS create is **unverified** on `main`. Hybrid is on by default
(`config.rs` `default_hybrid` / `[query].hybrid`).

**Unreadable directory entries are dropped.** `scan_directory` uses
`entries.flatten()` (`indexer.rs` 604). A failed `read_dir` on the
directory itself is warned (596–600); a failed *entry* is silent.

**No chunk quality floor.** `ChunkConfig` (`crates/ragfs-core/src/types.rs`
362–385) has size/overlap/hierarchy only. Frontmatter fences and lone
headers can be embedded.

**FUSE is a hard CLI dependency.** `crates/ragfs/Cargo.toml` always
depends on `ragfs-fuse` and `fuser` (lines 47, 64). Default features
are `candle` + `lancedb` (23). A CLI-only build still needs FUSE
headers. ADR-004 keeps FUSE as the advanced interface; it does not
require it at compile time on every host.

**No `docs/adr/` directory.** ADRs live in this file. The TOC above
is the index. There is no `docs/community-forks.md` yet.

### Decision
Adopt one shared, configurable exclusion and integrity model for CLI,
FUSE, MCP, and library callers. Implement it in the sequenced PRs
below. Defaults are portable (no host-specific paths). Users can opt
in to hidden or secret files. Owner resolutions that bind the
sequence are in **Resolved decisions**.

### 1. Ignore / exclusion model

#### Prior art (cited)

| Source | Hidden default | Ignore files | Bound | Notes |
|--------|----------------|--------------|-------|-------|
| ripgrep / Rust [`ignore`](https://docs.rs/ignore/latest/ignore/) [`WalkBuilder`](https://docs.rs/ignore/latest/ignore/struct.WalkBuilder.html) | Hidden skipped (`hidden()` on) | `.ignore` > `.gitignore` > `.git/info/exclude` > global gitignore; `add_custom_ignore_filename` is highest | `parents()` reads ancestors; git rules are repo-scoped | Overrides win first. Standard filters are on by default. |
| [`gitignore`](https://git-scm.com/docs/gitignore) / [`git check-ignore`](https://git-scm.com/docs/git-check-ignore) | N/A (git tracks hidden files) | Nested `.gitignore`; repo root; `core.excludesFile` | Stops at the repository, not `/` | `!` negation cannot re-include a file under an excluded directory. |
| [Sourcegraph ignore](https://sourcegraph.com/docs/admin/search) / [zoekt](https://github.com/sourcegraph/zoekt) | Not a hidden-dot default | Repo-root `.sourcegraph/ignore` globs, commit-tied | Repository root | zoekt-index also skips `.git,.hg,.svn` via `--ignore_dirs`. |
| [Cursor `.cursorignore`](https://cursor.com/docs/reference/ignore-file) | `.env`, `.git/`, lockfiles ignored by default; [respects `.gitignore`](https://cursor.com/help/customization/ignore-files) | Project-root `.cursorignore`; optional hierarchical parent search | Project / opt-in parents | Agent/Tab/@ only; terminal and MCP can still read ignored files. |
| [Continue `ignore.ts`](https://github.com/continuedev/continue/blob/main/core/indexing/ignore.ts) | Security denylist always on | `.continueignore` | Project | `id_rsa` / `*.pem` / `.aws/` / `.ssh/` plus many secret dirs. |
| [Aider `.aiderignore`](https://aider.chat/docs/faq.html) | Uses gitignore | `.aiderignore` at **git root** ([`--aiderignore`](https://aider.chat/docs/config/options.html)) | Git root, not `/` | Same syntax as gitignore. |
| [LlamaIndex `SimpleDirectoryReader`](https://developers.llamaindex.ai/python/framework-api-reference/readers/simple_directory_reader/) | `exclude_hidden=True` | `exclude` globs | Input directory | Hidden off by default. |
| [LangChain `DirectoryLoader`](https://reference.langchain.com/python/langchain-community/document_loaders/directory/DirectoryLoader) | `glob="**/[!.]*"`, `load_hidden=False` | `exclude` globs | Input directory | Hidden off by default. |
| [Gitleaks default config](https://github.com/gitleaks/gitleaks/blob/master/config/gitleaks.toml) | Content rules + path allowlists | N/A (scanner) | Repo | Filename blocking is a common overlay (see also [caulking denylist](https://github.com/cloud-gov/caulking): `*.pem`, `id_rsa`, `.env`, `.netrc`, `.aws/credentials`). |
| [TruffleHog](https://github.com/trufflesecurity/trufflehog/blob/master/README.md) | Pattern + Shannon entropy on base64/hex blobs | Path include/exclude regex files | Configured paths | Content scan, not a walker default. |

Consensus: **exclude hidden paths by default**, keep a **secret-file
denylist**, use **gitignore syntax** for user ignore files, and **do
not walk to `/`**. Cursor, Continue, and Aider add a named ignore file
*on top of* gitignore. LlamaIndex and LangChain loaders exclude hidden
files when they walk a directory.

#### Decision (exclusion)

1. **One source of truth.** A single Rust module (name fixed at
   implementation; illustrative `ragfs_index::exclude`) owns the
   default pattern lists and the matcher. `IndexerConfig::default()`,
   `config.rs` `default_exclude()`, FUSE mount indexing, and
   `docs/CONFIGURATION.md` / `docs/USER_GUIDE.md` all consume that
   module. MCP does not walk files; it must be tested against the
   same index. Python directory loaders are caller-owned; document
   that they should apply the same defaults if they ingest a tree.

2. **Use the `ignore` crate** (`WalkBuilder` +
   `add_custom_ignore_filename(".ragfsignore")` + `OverrideBuilder`
   for built-in defaults). Do not extend the hand-rolled glob in
   `path_matches_pattern` except as a compatibility shim during
   migration. This is the modern matcher (gitignore semantics, `!`
   negation, directory trailing `/`). Licence: MIT / Unlicense, same
   as the fork's `globset` choice.

3. **Hidden files *and* hidden directories are excluded by default.**
   Match any path *component under the index root* that starts with
   `.`. The index root itself may be hidden (`~/.notes`); do not
   exclude the root, only descendants. This replaces the basename-only
   `**/.*` special case and the CLI list that omitted it. The watcher
   uses the same matcher (drop the basename-only shortcut).

4. **Secret-file denylist** (always applied unless the user sets
   `index.include_secret_files = true`). Patterns are
   case-insensitive on macOS/Windows and case-sensitive on Linux
   (documented). Built-in list, not host-specific:

   - `**/.env`, `**/.env.*`, `**/*.env`
   - `**/.netrc`, `**/.npmrc`, `**/.pypirc`, `**/.git-credentials`
   - `**/*.key`, `**/*.pem`, `**/*.p12`, `**/*.pfx`, `**/*.kdbx`
   - `**/*.jks`, `**/*.keystore`, `**/*.ppk`
   - `**/id_rsa`, `**/id_dsa`, `**/id_ecdsa`, `**/id_ed25519` (and
     the same names with a `.pub` *not* excluded — public keys are
     not secrets; keep `id_*.pub` eligible)
   - `**/secrets.*`, `**/credentials.*`
   - `**/.aws/credentials`, `**/.kube/config`

   Do **not** use a bare `id_*` (false positive on `id_mapping.md`).
   Users may add or subtract via config / `.ragfsignore`.

5. **`.ragfsignore`.** gitignore syntax. Nested files **inside the
   index tree** are honoured (same rationale as nested `.gitignore`:
   a subproject can tighten rules). **Never walk above the index
   root** looking for `.ragfsignore` — the fork's walk to `/` is
   rejected (surprising `/` or `$HOME` files, host-specific, and
   unlike git which stops at the repo). A user-global overlay at
   `$RAGFS_CONFIG_DIR/ignore` is **deferred** (not in PR 2; needs
   its own later PR if wanted).

6. **`.gitignore` / `.ignore`.** Honour them *under the index root*
   when `index.honor_gitignore = true` (default **true**, matching
   ripgrep and Cursor). `WalkBuilder::parents(false)` and
   `git_global` **off**: a `.gitignore` in `/` or `$HOME`, and the
   user's global gitignore, are not applied. There is no
   `honor_gitignore_parents` switch in this sequence.

7. **Explicit opt-in for hidden paths.** `index.include_hidden`
   (default `false`) and CLI `--include-hidden`. Hidden opt-in does
   **not** disable the secret denylist. Secret opt-in is a separate
   flag. Config / CLI can still exclude via `.ragfsignore`.

8. **Precedence.** Built-in **secret** and **hidden** rules are
   fail-closed: `.gitignore` / `.ignore` / `.ragfsignore` may add
   excludes, but they must **not** re-include a secret or hidden path
   unless the matching opt-in flag is set. (A repo that commits
   `!.env` for git must not become searchable.) Implementation:
   secret + hidden (and the noise list) are `OverrideBuilder` ignore
   globs, which the `ignore` crate documents as winning first
   ([WalkBuilder ignore rules](https://docs.rs/ignore/latest/ignore/struct.WalkBuilder.html)).
   Then, among ignore files, custom `.ragfsignore` > `.ignore` >
   `.gitignore` (all under the index root). CLI `--include-hidden` /
   `include_secret_files` disable the matching override; `--exclude`
   and `[index].exclude` always add excludes. `$RAGFS_CONFIG_DIR/ignore`
   is out of this sequence.

9. **Purge on reindex.** Every `ragfs index` / mount initial scan
   (not only `--force`) deletes store rows whose `file_path` is now
   excluded. Reuse `delete_by_file_path`. Upgrading without a purge
   would leave leaked chunks searchable. `--force` still means
   “rewrite eligible files”; purge of ineligible files is
   independent and default-on (`index.purge_excluded = true`).

### 2. Content-level secret scanning

**Options.** (a) Skip the whole file on a hit. (b) Redact the matching
span and embed the rest. (c) Defer / opt-in.

**Trade-offs.** Skip is simple and safest, but drops surrounding
prose (README with an example key). Redact keeps the document but
needs a stable redaction token so embeddings do not encode the
secret; it is more code and still fails closed only if the detector
fires. Both have **false positives**: UUIDs, checksums, base64
images, documented example tokens. TruffleHog's entropy rule (high
Shannon entropy on base64/hex blobs longer than 20 characters) is
the usual extra signal and the usual FP source.

**Cost.** Per-file CPU on the extract path. **No measured figure is
claimed here**; treat any later number as `TBD (to be measured)`.

**Decision: off / deferred to a later ADR and PR.** Do **not** add
`index.secret_scan` (or any extract-time scanner) in this sequence.
Ship path exclusion first. A later ADR must choose skip vs redact,
add fixtures (known keys vs example keys), and only then introduce
config. Path denylist plus hidden exclusion covers the high-value
files named in the review (`.ssh/id_rsa`, `.aws/credentials`,
`.netrc`, `.npmrc`).

### 3. Store integrity (model / dimension)

On `LanceStore::init` / open, if the sidecar has `embedding_model`,
compare it to the resolved model id (`SUPPORTED_EMBEDDING_MODEL` /
`resolve_supported_model`). On mismatch: **error**, message names
both ids and says to rerun `ragfs index --force` (or set
`index.on_model_mismatch = "reindex"`). Dimension mismatch already
errors; keep that check.

**Fingerprint** stored on the sidecar (additive JSON, old sidecars
stay readable):

```text
embedding_model      # already present
embedding_dim        # already present
# later, not required for the first PR:
# embedding_weights_sha256
```

The compared fingerprint for v1 is `(model_id, dimension)`. Do not
hash weights in the first PR (download + hash is a new I/O path).

**ADR-008 receipts** already carry `embedding_model`. After this
work they also carry `embedding_dim` (additive). A query against a
refused store never writes a receipt.

**ADR-009 pins.** That ADR says ragfs retrieval/indexing/schema do
not change *under ADR-009*. This ADR *does* change indexing
defaults and open-time checks. The harness adapter must record the
sidecar fingerprint in the results `environment` / `pins` once
those fields exist. Protocol pins stay Hub revision + `sha256` of
model artefacts (`TBD (to be measured)` until first run). A
mismatch on open is a failed run, not a silent mix.

`--force` rebuilds the table (or deletes and recreates) and
rewrites the sidecar. It is the documented remedy.

### 4. Chunk quality floor and directory errors

- `[chunking].min_alnum_chars`, default **3**. A character counts if
  it is Unicode alphanumeric (categories L* or Nd), so CJK letters
  count. Chunks below the floor are dropped before embed.
- Record the value on the sidecar and, additively, on query JSON /
  receipts as `min_alnum_chars`. ADR-009 receipts copy the field
  when present.
- Replace `entries.flatten()` with a `warn!` per failed entry.
  Continue the walk. Same for other product walks that flatten
  (FUSE passthrough listing is out of scope unless it hides index
  errors; the indexer path is in scope).

### 5. Hybrid FTS staleness test; optional FUSE feature

- **Test first** (no behaviour change in that PR): insert rows after
  `init` on an empty table, run `hybrid_search`, assert the new
  text is found. If it fails, fix by refreshing/optimizing FTS after
  inserts — **not** by making hybrid opt-in. Credit sophie4869 as
  reporter in that PR body only.
- **`mount` Cargo feature** on `ragfs` (and the `ragfs-fuse`
  dependency). Default **on** for the published binary so ADR-004
  stays the product default. `cargo build -p ragfs --no-default-features
  --features candle,lancedb` must succeed without `fuser`. Mount
  subcommands error with “built without mount”. CI: one job for that
  no-mount build (desk build only).

### 6. Threat model

**Asset.** File text copied into Lance chunks and returned by query
surfaces. Highest sensitivity: SSH keys, cloud credentials, `.env`,
`.netrc`, npm/pypi tokens.

**Attacker.** Not a remote unauthenticated party. A local process
that can invoke `ragfs query`, read FUSE `.ragfs/.query/*` /
`.search/*` / `.similar/*`, or call MCP `ragfs_search` /
`ragfs_similar`. Typical cases: an MCP-connected LLM, a prompt
injected into that LLM (“search for AWS keys”), another user on a
shared host if `allow_other` is on (`SECURITY.md`), or anyone with
filesystem access to `~/.local/share/ragfs/indices/`.

**Channel.** Indexed secrets leak as `content` in CLI JSON, FUSE
query JSON (500-char truncate — still enough for a key), and MCP
search (500-char truncate). The index directory is a second copy
of the secret after the source file.

**Out of scope for this ADR.** Remote HTTP serve (see non-goals).
MCP write-jail (already shipped, [GHSA-qfm6-39c2-927v](https://github.com/gianlucamazza/ragfs/security/advisories/GHSA-qfm6-39c2-927v)).
Physical disk encryption of `~/.local/share/ragfs`.

**Mitigations this design provides.** Default-deny hidden and
secret *paths*; purge on upgrade; model-mismatch fail-closed.
Content scanning is out of this sequence. Residual: user opt-in,
secrets in non-hidden names (`notes/passwords.md`), and the
plaintext index directory.

### 7. Migration, semver, advisory

**Breaking.** Default corpus shrinks; existing indexes keep leaked
chunks until the next index run (purge). Model mismatch becomes an
error. Optional FUSE is a packaging change only if someone builds
`--no-default-features` without noticing. Receipts/sidecar gain
additive fields.

**Release: `0.3.0`.** v0.2.2 already shipped several MCP `BREAKING`
notes inside 0.2.x. This change alters *what is in the index* for
every `ragfs index` user, including `$HOME`. A minor bump is the
0.x signal for that. Do **not** ship this as `0.2.3`. CHANGELOG:
`Security` section plus a `!` conventional-commit title on PR 1
(`fix(index)!: …`). Keep a Changelog / SemVer as today.

**Upgrade notes (docs, not this PR):** re-run `ragfs index <path>`
once per index after upgrade (purge runs without `--force`). Use
`--include-hidden` if the tree *is* a hidden notes dir and the user
wants dotfiles. `--force` if the embedder id changed.

**Advisory.** Severity **moderate** (CWE-200 / local information
disclosure of credentials via query/FUSE/MCP; default config; no
remote unauthenticated access). Publish **together with the fixing
release** (`0.3.0`), same procedure as
[GHSA-qfm6-39c2-927v](https://github.com/gianlucamazza/ragfs/security/advisories/GHSA-qfm6-39c2-927v)
(published 2026-10-20, severity **low**, MCP write-gate / allowlist
/ bounds). Do not publish the advisory before PR 1 lands on a
released `0.3.0` tag.

### 8. PR sequencing

One PR per row. Security first. Tests on every PR. Target release
**0.3.0**. Where fork code is adapted, commit trailer
`Co-authored-by: sophie4869 <sophie4869@users.noreply.github.com>`
and name the source commits in the PR body.

| # | Title | Tests |
|---|-------|-------|
| **1** | `fix(index)!: exclude hidden paths and secret files by default` + `docs/community-forks.md` | Unit: `.ssh/id_rsa`, `.aws/credentials`, `.obsidian/x.md`, hidden index root `~/.notes` *kept*, `server.pem` excluded, `notes/keyboard.md` kept. CLI defaults == indexer defaults. Integration: temp tree, query via **CLI + MCP + FUSE** never returns those paths. Purge: pre-seeded chunk for an excluded path is gone after index. |
| **2** | `feat(index): .ragfsignore` | Parse, comments, trailing `/`, nested under the index root, **no** read of a file above the root. **Not** `$RAGFS_CONFIG_DIR/ignore`. |
| **3** | `fix(store): refuse a different embedding model` | Sidecar other model → error; `--force` rebuilds and rewrites sidecar; dim check still works. |
| **4** | `fix(index): skip degenerate chunks` | `---`, `#`, whitespace dropped; short CJK kept; value in sidecar/receipt. |
| **5** | `fix(index): log unreadable directory entries` | Unix permission-denied entry → warning, walk continues. |
| **6** | `test(store): hybrid search sees rows inserted after FTS create` | Test first; fix only if it fails. Reporter credit in body. |
| **7** | `build: optional mount feature` | CI no-mount build; mount subcommand message. |
| **8** | (folded into 1) community-forks credits | Entries for sophie4869/ragfs (taken / not taken / reopen) and manojtummala/SemPOSIX (ideas in #60). |

`docs/community-forks.md` is created in **PR 1**, not in this ADR
PR. Content scanning and `$RAGFS_CONFIG_DIR/ignore` are **not** in
this sequence. Later, only on owner request and behind their own
ADRs: content scan, user-global ignore file, Metal opt-in,
`ragfs compact`, HTTP `serve` with auth on by default.

### Non-goals

- Switching the default embedding model to e5 / multilingual-e5
  (would break ADR-009 pins and every existing index).
- Putting absolute paths (or last-N folder names) into embedding
  text (host leakage; retrieval change).
- `ragfs serve` web UI as in the fork (optional token, `CORS *`, no
  Host check).
- Synology / rsync helpers.
- Docker image publishing (see `examples/docker-rag-stack`).
- Content-level secret scanning (later ADR / PR).
- `$RAGFS_CONFIG_DIR/ignore` (deferred; not in PR 2).
- Implementing any of the PRs above in *this* change.

### Rationale
Path exclusion is the control that actually stops
`.ssh/id_rsa` from becoming a search hit. A single `ignore`-crate
matcher, bounded at the index root, is what ripgrep, Cursor, and
git already taught users. Content scanning and a web UI are larger
surfaces; they wait. Comparing the sidecar model id is the missing
half of the dim check and is what makes ADR-008/009 pins honest.
`--force` is already the CLI hammer.

### Trade-offs

**Pros.** One list; hidden dirs covered; leaked chunks purged;
fail-closed model mix; portable defaults; FUSE optional for
CLI-only hosts.

**Cons.** Users who indexed `~/.notes` *as a hidden tree of
dotfiles* must pass `--include-hidden`. Honouring `.gitignore` by
default may drop files a docs tree still wanted (opt out with
`honor_gitignore = false`). Deferred content scan will not catch
`notes/passwords.md`.

### Alternatives considered

| Alternative | Rejected because |
|-------------|------------------|
| Port sophie4869/ragfs matcher and ignore-to-`/` | Custom glob; ancestor walk to `/`; two lists would remain unless rewritten anyway |
| Keep `path_matches_pattern` and only add `**/.*` to the CLI list | Still basename-only; hidden-root vs hidden-child stays wrong; no gitignore semantics |
| Hidden files only (not directories) | `.ssh/id_rsa` is the bug |
| Content scan on by default | FP + skip/redact product choice; no fixtures yet |
| Auto-reindex on model mismatch (fork marker file) | Surprising CPU/disk; `--force` is explicit |
| Make hybrid opt-in to hide FTS staleness | Hides the bug; hybrid is the documented default |
| Ship as `0.2.3` with `!` | Owner chose `0.3.0` as the 0.x breaking signal |
| Implement in this PR | This PR is the accepted ADR only; code follows in sequenced PRs |

### Resolved decisions

Owner accepted this ADR on 2026-10-20:

1. **Release `0.3.0`.** Not `0.2.3`.
2. **Advisory severity MODERATE**, published together with the
   fixing `0.3.0` release (same procedure as GHSA-qfm6-39c2-927v).
3. **`index.honor_gitignore` default `true`.** `parents` and global
   gitignore are **off**.
4. **Content scan off.** Deferred to a later ADR and PR; no
   `secret_scan` key in this sequence.
5. **`.ragfsignore` nested under the index root.** No walk above
   the root (including no walk to `/`).
6. **`$RAGFS_CONFIG_DIR/ignore` deferred.** Not in PR 2.

### Sources verified

- This repo @ `bcb1611`: `crates/ragfs/src/config.rs`,
  `crates/ragfs-index/src/indexer.rs`, `watcher.rs`,
  `crates/ragfs-store/src/lancedb.rs`, `schema.rs`,
  `crates/ragfs-fuse/src/filesystem/mod.rs`,
  `crates/ragfs-mcp/src/ragfs_mcp/server.py`,
  `docs/CONFIGURATION.md`, `docs/USER_GUIDE.md`, ADR-008/009 in
  this file, [GHSA-qfm6-39c2-927v](https://github.com/gianlucamazza/ragfs/security/advisories/GHSA-qfm6-39c2-927v).
- Fork review (read-only, 2026-10-20) of sophie4869/ragfs and
  manojtummala/SemPOSIX; #60 on this repo.
- Prior-art URLs in the table above.

Social posts are not sources.

---

## ADR-011: Multimodal Indexing (Images, Audio, Video)

### Status
Accepted (2026-10-20)

### Context
ragfs is a local-first filesystem RAG. Text, code, PDF text, and Office
OOXML already go through extract → chunk → embed (`gte-small`, 384-d
Candle) → LanceDB. Images exist in the extractor crate; audio and video
do not. Agents that mount a tree or call MCP therefore cannot search
screenshots, scans, voice notes, or recordings except by filename or
the few words of metadata the image extractor writes.

This ADR is design only. It does **not** implement extractors, add
Cargo or Python dependencies, change the default embedder, bump a
version, or cut a tag. Implementation follows in the sequenced PRs
below, each feature-flagged and default-off. It does not invent
benchmark, latency, or VRAM numbers. Model names, sizes, licences, and
release dates below were fetched from the cited URLs while writing;
anything not fetched is marked unverified.

#### Sequencing relative to ADR-010 and 0.3.0

Do **not** start these PRs until the ADR-010 exclusion / model-
fingerprint sequence has landed and **0.3.0** is released, unless the
owner later accepts a documented exception.

Reasons, from the current code rather than a calendar guess:

1. **Exclusion applies to media.** ADR-010 changes *what* is eligible
   to enter the index (hidden paths, secret-file denylist,
   `.ragfsignore`, purge of newly excluded paths). Media files are
   large and often sit next to secrets (screenshots in `~/Downloads`,
   voice memos under a hidden notes dir, camera rolls). Shipping a
   working image or ASR path *before* those defaults would make more
   of those files searchable. The existing image path already writes
   metadata text into Lance (`process_file` embeds `content.text`);
   widening that surface without the new walker is the wrong order.
2. **Per-modality fingerprints need ADR-010's sidecar check.** ADR-010
   records that `SchemaSidecar.embedding_model` is written but only
   *dimension* is compared on open (`ensure_embedding_dim_matches`).
   Native CLIP / SigLIP / CLAP vectors must not mix with `gte-small`
   384-d. A fail-closed model-id check is the prerequisite; adding a
   second embedding space before that check repeats the same class of
   silent mix.
3. **Size and purge semantics.** `max_file_size` is 50 MiB
   (`crates/ragfs/src/config.rs` `default_max_file_size`, line 244).
   ADR-010's oversized-file delete path is the right hook for a later
   duration limit. Audio/video need that hook to exist and to be
   tested, not a second skip list.
4. **No concrete reason to invert the order.** The image captioner is
   already feature-gated and, as verified below, is not wired into the
   indexer. Completing that wire after exclusions is the smallest
   useful step and does not require a new model.

Owner may accept this ADR independently of ADR-010; the *code* PRs
still wait.

#### Verified on `main` @ `e310209c` (docs) / code as of that commit

**Images are metadata-first; captions are optional and unused by the
indexer.** `ImageExtractor` (`crates/ragfs-extract/src/image.rs`)
accepts `image/jpeg`, `image/png`, `image/gif`, `image/webp`,
`image/bmp`, `image/tiff`. `extract` decodes with
`image::load_from_memory` (`decode_image_metadata`, lines 143–154)
and builds `text` as `Image: {filename} ({w}x{h}, {format})`
(lines 88–96). If a captioner is present *and* initialized, a caption
is stored on `ExtractedImage.caption` (lines 99–121), **not** appended
to `text`. The CLI registers `ImageExtractor::new()` with no
captioner (`crates/ragfs/src/main.rs` line 293).

**`vision` is default-off.** `crates/ragfs-extract/Cargo.toml` feature
`vision` pulls Candle + `hf-hub` + `tokenizers`. `crates/ragfs/Cargo.toml`
default features are `candle` + `lancedb`; `full` adds `vision`.
`BlipCaptioner` (`crates/ragfs-extract/src/vision.rs`) loads
`Salesforce/blip-image-captioning-base` at 384×384 when the feature
is on. `PlaceholderCaptioner` always returns `None`. `docs/API.md`
and `docs/CONFIGURATION.md` describe the feature as optional
(~400 MB model download).

**The indexer never reads `ExtractedContent.images`.**
`process_file` (`crates/ragfs-index/src/indexer.rs` 652–793) extracts,
skips empty `content.text`, chunks `content`, and embeds
`chunk_outputs[].content` via `EmbedderPool::embed_batch` (text only).
`determine_content_type` (806–869) returns `Code`, `Markdown`, or
`Text` — never `ContentType::ImageCaption`, even though that variant
exists (`crates/ragfs-core/src/types.rs` 232–233) and Lance already
round-trips the string `image_caption`
(`crates/ragfs-store/src/lancedb.rs` 1392, 1436–1448). So a built
`--features vision` binary still indexes the metadata sentence, not
the BLIP caption.

**PDF embedded images are extracted, not captioned, not indexed as
images.** `PdfExtractor` (`crates/ragfs-extract/src/pdf.rs`) pulls
DCTDecode / FlateDecode / JPXDecode images with
`MAX_IMAGES = 100`, `MAX_TOTAL_BYTES = 50 * 1024 * 1024`,
`MIN_DIMENSION = 50` (lines 89–91). `ExtractedImage.caption` is
hard-coded `None` with the comment "Will be filled by vision model
in future" (line 204). Those bytes never reach `process_file`.

**Audio is a type, not a pipeline.** `Modality` is `Text | Image |
Audio` (`types.rs` 422–426). `Embedder::embed_image` defaults to
`EmbedError::ModalityNotSupported(Modality::Image)` (`traits.rs`
108–115). There is no `embed_audio`. Tests construct
`Modality::Audio` and `EmbedError::ModalityNotSupported(Modality::Audio)`
(`types.rs` 778–779; `error.rs` 183, 362) but no extractor or
embedder implements it.

**Video is `UnsupportedType`.** `ExtractorRegistry::get_for_mime("video/mp4")`
is asserted `None` (`crates/ragfs-extract/src/registry.rs` 118).
`ExtractError::UnsupportedType("video/mp4")` is a documented error
string (`crates/ragfs-core/src/error.rs` 235–238). No video MIME is
registered.

**Store schema has no modality or time range.** `chunks_schema`
(`crates/ragfs-store/src/schema.rs` 77–121) is v2: identity, content,
byte/line ranges, hierarchy, a single `FixedSizeList` embedding,
`embedding_model`, file MIME/size, code fields, directory-scope
columns. No `modality`, no `start_ms` / `end_ms`. `SearchResult`
(`types.rs` 515–530) exposes `file_path`, `content`, `score`,
`byte_range`, `line_range`, `metadata`. FUSE `.query/<text>` emits
those fields with content truncated to 500 characters
(`crates/ragfs-fuse/src/filesystem/mod.rs` 297–303). MCP
`ragfs_search` emits `file_path`, `content[:500]`, `score`,
`metadata` (`crates/ragfs-mcp/src/ragfs_mcp/server.py` 887–891).
Neither surface has a time code or a thumbnail.

**`max_file_size` is 50 MiB for every file.** Image decode has no
separate pixel budget. A 50 MiB PNG can still expand to a large
bitmap inside `image::load_from_memory`.

### Decision
Adopt a **text-first, feature-flagged, separate-space** multimodal
plan:

1. **Close the existing image gap** so metadata + optional BLIP
   captions (and later OCR) become `ContentType::ImageCaption` chunks
   in the *current* `gte-small` table. One embedding space, ADR-009
   pins unchanged.
2. **Native multimodal embeddings** (CLIP / SigLIP 2, later optional
   ColQwen) live in a **separate Lance table** with its own dimension
   and ADR-010-style model fingerprint. Never write a 512-d or 768-d
   vector into the 384-d chunks table.
3. **Audio is transcript-first** (timestamped Whisper chunks in the
   text table). Native audio embeddings (CLAP) are a later optional
   table, not the default.
4. **Video is last** and is a composition of keyframe images + an ASR
   track, with `start_ms` / `end_ms` on every hit. No Twelve Labs (or
   other cloud video API) in the product path.
5. Every new runtime is a **default-off Cargo feature**. Prefer
   Rust/Candle or a pinned subprocess (whisper.cpp, tesseract,
   optional ffmpeg) over a Python service. Linked ffmpeg is out of
   the first sequence.

### 1. Images: native embeddings vs caption-then-embed vs OCR

Two retrieval styles are in production use elsewhere, plus OCR as a
text overlay.

**Native dual-encoder (text and image in one space).** A text query
is embedded with the *text* tower and compared to *image* vectors.
This is how LlamaIndex, Haystack, Marqo, and LanceDB's Python
`open-clip` helper search photos.

| Model (fetched) | Hub / paper | Params (Hub overview unless noted) | Dim / notes | Licence |
|-----------------|-------------|-------------------------------------|-------------|---------|
| OpenAI CLIP ViT-B/32 | [openai/clip-vit-base-patch32](https://huggingface.co/openai/clip-vit-base-patch32); paper [arXiv:2103.00020](https://arxiv.org/abs/2103.00020) (2021-01) | Hub overview does not report a parameter count | Dual encoder; Candle has `ClipModel` ([docs.rs](https://docs.rs/candle-transformers/latest/candle_transformers/models/clip/struct.ClipModel.html), [example](https://github.com/huggingface/candle/blob/main/candle-examples/examples/clip/main.rs)) | Hub card has **no `license:` tag**. GitHub [openai/CLIP LICENSE](https://raw.githubusercontent.com/openai/CLIP/main/LICENSE) is MIT for the *software*. Weights licence is **unverified** from the Hub card. |
| OpenCLIP ViT-B-32 `laion2b_s34b_b79k` | Used as LanceDB `open-clip` default ([docs](https://docs.lancedb.com/integrations/embedding/openclip)) | Not re-counted here | CPU default in that helper | [open_clip LICENSE](https://raw.githubusercontent.com/mlfoundations/open_clip/main/LICENSE) is MIT (software) |
| SigLIP 2 | Paper [arXiv:2502.14786](https://arxiv.org/abs/2502.14786) (submitted 2025-02-20); [big_vision README](https://github.com/google-research/big_vision/blob/main/big_vision/configs/proj/image_text/README_siglip2.md); Hub e.g. [google/siglip2-base-patch16-224](https://huggingface.co/google/siglip2-base-patch16-224) | Paper: vision towers ViT-B **86M**, L **303M**, So400m **400M**, g **1B**. Hub reports **375.2M** for the `siglip2-base-patch16-224` dual-encoder repo (not the same number as the paper's vision-tower 86M) | Multilingual; NaFlex variants exist on the Hub (not opened in this pass beyond the paper's claim) | Hub `apache-2.0`; big_vision: software Apache-2.0, other materials CC-BY-4.0 |
| jina-clip-v2 | [jinaai/jina-clip-v2](https://huggingface.co/jinaai/jina-clip-v2); [arXiv:2412.08802](https://arxiv.org/abs/2412.08802) | Hub **865.3M** (card: text 561M + EVA02-L 304M) | 64–1024 Matryoshka; 512×512; 89 languages | **`cc-by-nc-4.0` — non-commercial. Do not default.** |
| jina-embeddings-v5-omni-small (reference only) | [jinaai/jina-embeddings-v5-omni-small](https://huggingface.co/jinaai/jina-embeddings-v5-omni-small); paper [arXiv:2605.08384](https://arxiv.org/abs/2605.08384). There is **no** Hub repo named `jinaai/jina-embeddings-v5-omni` (404 on fetch). Compact sibling: [jinaai/jina-embeddings-v5-omni-nano](https://huggingface.co/jinaai/jina-embeddings-v5-omni-nano). | Hub **1626.3M**. Card text says “~1.74B” (not reconciled here). | Card: **one shared space** for text, image, video, and audio; dim 1024; Matryoshka 32–1024; aligned with [jinaai/jina-embeddings-v5-text-small](https://huggingface.co/jinaai/jina-embeddings-v5-text-small). Card benchmark “open-weight frontier” figures are **vendor/paper claims**, not re-run. | **`cc-by-nc-4.0` — reference only. Do not default, do not pin.** |
| nomic-embed-vision-v1.5 | [nomic-ai/nomic-embed-vision-v1.5](https://huggingface.co/nomic-ai/nomic-embed-vision-v1.5); [arXiv:2406.18587](https://arxiv.org/abs/2406.18587) | Hub **92.9M** | Same space as [nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) (Hub **136.7M**, Apache-2.0). Card reports ImageNet 0-shot **71.0** vs OpenAI CLIP ViT-B/16 **68.3** (card figures, not re-run here) | `apache-2.0` |

**Visual-document retrievers (page-as-image, multi-vector).** These
target scanned PDFs and slides, not holiday photos.

| Model | Hub / paper | Notes | Licence |
|-------|-------------|-------|---------|
| ColPali v1.3 | [vidore/colpali-v1.3](https://huggingface.co/vidore/colpali-v1.3) (also [vidore/colpali](https://huggingface.co/vidore/colpali)); [arXiv:2407.01449](https://arxiv.org/abs/2407.01449) | ColBERT-style MaxSim. Needs a late-interaction index, not a single Lance `FixedSizeList`. **No official ONNX/GGUF** on the Hub card, tags, or file listing (safetensors adapter only). | Adapter card `mit`. **Sits on a Gemma / PaliGemma base**: `vidore/colpaligemma-3b-pt-448-base` (https://huggingface.co/vidore/colpaligemma-3b-pt-448-base) is `license:gemma`, architecture `paligemma`, `base_model:google/paligemma-3b-pt-448`. Gemma Terms: https://ai.google.dev/gemma/terms. **Do not default.** |
| ColQwen2 | [vidore/colqwen2-v1.0](https://huggingface.co/vidore/colqwen2-v1.0), [vidore/colqwen2-base](https://huggingface.co/vidore/colqwen2-base) | Hub base **2209.2M**, architecture `qwen2_vl`, `base_model:Qwen/Qwen2-VL-2B-Instruct` | Both cards `apache-2.0`. Still a multi-vector ~2B VLM; **no official ONNX/GGUF** on the Hub card or tags. CPU latency **UNVERIFIED**. |
| ColQwen2.5 | [vidore/colqwen2.5-v0.2](https://huggingface.co/vidore/colqwen2.5-v0.2), [vidore/colqwen2.5-base](https://huggingface.co/vidore/colqwen2.5-base) | Hub base **3754.9M**, architecture `qwen2_5_vl` | Adapter card `mit`; base card `apache-2.0`. **Treat as qwen-research**: card text and `base_model` are `Qwen/Qwen2.5-VL-3B-Instruct`. **No official ONNX/GGUF** (listing is safetensors + tokenizer only). Do not default. |

**Runtime pin if a later PR ever calls ColPali from Python.**
[colpali-engine 0.3.18](https://pypi.org/project/colpali-engine/0.3.18/)
(PyPI upload **2026-08-22**) requires
`transformers>=5.3.0,<6.0.0`. Under Transformers v5, **do not**
use an older engine: `>=0.3.18` is the floor. That stack is still
Python-only, multi-vector, and licence-gated by the base model; it
is not a phase-1..6 default.

**Caption-then-embed with a small VLM**, then the existing
`gte-small` text embedder. This is what Haystack's
`LLMDocumentContentExtractor` does with a vision chat model
([docs](https://docs.haystack.deepset.ai/docs/llmdocumentcontentextractor)).
ragfs already sketched this with BLIP.

| Model | Hub / paper | Params | Licence |
|-------|-------------|--------|---------|
| BLIP captioning base (already in-tree) | [Salesforce/blip-image-captioning-base](https://huggingface.co/Salesforce/blip-image-captioning-base); [arXiv:2201.12086](https://arxiv.org/abs/2201.12086) | Hub overview did not print a parameter count | `bsd-3-clause` |
| SmolVLM-256M-Instruct | [HuggingFaceTB/SmolVLM-256M-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct); [arXiv:2504.05299](https://arxiv.org/abs/2504.05299) | Hub **256.5M**; ONNX tag present | `apache-2.0` |
| SmolVLM-500M-Instruct | [HuggingFaceTB/SmolVLM-500M-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct) | Hub **507.5M** | `apache-2.0` |
| SmolVLM-Instruct (2B-class) | [HuggingFaceTB/SmolVLM-Instruct](https://huggingface.co/HuggingFaceTB/SmolVLM-Instruct) | Hub **2246.3M** | `apache-2.0` |
| Florence-2-base | [microsoft/Florence-2-base](https://huggingface.co/microsoft/Florence-2-base); [arXiv:2311.06242](https://arxiv.org/abs/2311.06242) | Card **0.23B**; Hub **231.6M** | `mit` |
| Qwen2.5-VL-3B-Instruct | [Qwen/Qwen2.5-VL-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct) | Hub **3754.6M** | **`qwen-research` ([LICENSE](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/raw/main/LICENSE), 2024-09-19): non-commercial unless a separate commercial licence is obtained. Do not default.** |
| Qwen3-VL-2B-Instruct | [Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct) | Hub **2127.5M**; architecture `qwen3_vl` | **`apache-2.0`** (Hub card + README `license:`). Prefer this over Qwen2.5-VL-3B if a later PR wants a Qwen VLM. Card marketing (“most powerful … to date”) is a **vendor claim**, not a measured ragfs result. Still ~2B; opt-in only. |
| Qwen3.5-0.8B (small) | [Qwen/Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B) | Hub **873.4M**; architecture `qwen3_5`; `image-text-to-text` | **`apache-2.0`** (README `license_link` to the same-repo LICENSE). Unified VL, not a dual-encoder. Candidate later captioner; not a phase-1 pin. |
| Qwen3.5-2B (small) | [Qwen/Qwen3.5-2B](https://huggingface.co/Qwen/Qwen3.5-2B) | Hub **2274.1M**; architecture `qwen3_5`; `image-text-to-text` | **`apache-2.0`**. Same family as 0.8B; still opt-in. |

**OCR.** Tesseract is [Apache-2.0](https://raw.githubusercontent.com/tesseract-ocr/tesseract/main/LICENSE).
It is the local, licence-clean way to get *searchable words* off
scans and screenshots. It does not replace a caption (a photo of a
cat has no text) and it does not replace a dual-encoder (a query
"red bicycle" will not match an OCR-empty photo). It *does* make
`gte-small` + FTS useful on slides and screenshots. No Tesseract
WER was measured in this pass.

**Hub licence red flags (cross-checked against Hub cards).**
Adapter-card `license:` is not enough when the base model is
more restrictive. Do **not** default any of these.

| Repo | Hub URL | Card `license` | Effective flag |
|------|---------|----------------|----------------|
| `jinaai/jina-clip-v2` | https://huggingface.co/jinaai/jina-clip-v2 | `cc-by-nc-4.0` | **CC-BY-NC** |
| `jinaai/jina-embeddings-v5-omni-small` | https://huggingface.co/jinaai/jina-embeddings-v5-omni-small | `cc-by-nc-4.0` | **CC-BY-NC — reference only** (omni text/image/video/audio). Same flag on `jinaai/jina-embeddings-v5-omni-nano`. |
| `Qwen/Qwen2.5-VL-3B-Instruct` | https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct | README `license_name: qwen-research`; [LICENSE](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/raw/main/LICENSE) is the Qwen Research Licence (non-commercial unless a separate commercial grant). Hub overview metadata prints no `license:` tag. | **qwen-research / NC** |
| `vidore/colqwen2.5-v0.2` | https://huggingface.co/vidore/colqwen2.5-v0.2 | adapter card `mit` | **qwen-research** via base `Qwen/Qwen2.5-VL-3B-Instruct` (card text: “based on Qwen2.5-VL-3B-Instruct”). `vidore/colqwen2.5-base` (https://huggingface.co/vidore/colqwen2.5-base) prints `apache-2.0` **and** `base_model:Qwen/Qwen2.5-VL-3B-Instruct` (Hub **3754.9M**). Treat the stack as research-licensed. |
| `vidore/colpali-v1.3` | https://huggingface.co/vidore/colpali-v1.3 | adapter card `mit` | **Gemma / PaliGemma**. `base_model` is `vidore/colpaligemma-3b-pt-448-base` (https://huggingface.co/vidore/colpaligemma-3b-pt-448-base, Hub `license:gemma`, **2924.6M**, architecture `paligemma`, itself `base_model:google/paligemma-3b-pt-448`). |
| `microsoft/msclap` | https://huggingface.co/microsoft/msclap | `ms-pl` | **MS-PL**. Hub overview did **not** print a parameter count (not copied). Prefer `laion/clap-htsat-fused` if a CLAP table is added. |

**ONNX / GGUF (official Hub only).** Official `vidore/colpali`,
`vidore/colpali-v1.3`, `vidore/colqwen2-v1.0`, and
`vidore/colqwen2.5-v0.2` Hub overviews have **no** `onnx` or
`gguf` tags. Directory listings of
`vidore/colpali-v1.3` and `vidore/colqwen2.5-v0.2` contain
safetensors adapters and tokenizer files only — **no official
ONNX or GGUF**. Community conversions were not exhaustively
searched and stay **UNVERIFIED**. `HuggingFaceTB/SmolVLM-256M-Instruct`
and `SmolVLM-500M-Instruct` **do** carry an `onnx` Hub tag.
`jinaai/jina-clip-v2` and `nomic-ai/nomic-embed-vision-v1.5` also
carry `onnx` tags (still NC / Apache as above).

**Recommendation for images.** Default product path:
**OCR (when text-like) + caption-then-embed into the existing
384-d table.** Native SigLIP 2 (Apache-2.0, Candle-shaped future
work) or OpenCLIP as a **second table** for "find this photo"
queries. Reject jina-clip-v2 and **jina-embeddings-v5-omni-***
(CC-BY-NC; omni is documentation contrast only),
Qwen2.5-VL-3B-Instruct and **colqwen2.5** (qwen-research), and
ColPali v1.3 (Gemma / PaliGemma base) as defaults. If a later PR
wants a Qwen VLM captioner, prefer **Qwen3-VL-2B-Instruct** or
**Qwen3.5-0.8B / 2B** (`apache-2.0`) over Qwen2.5-VL-3B.
`vidore/colqwen2-v1.0`
(https://huggingface.co/vidore/colqwen2-v1.0) prints
`apache-2.0` on the adapter; it is still a ~2B multi-vector VLM
with no official ONNX/GGUF — defer to a later opt-in after the
single-vector table exists. Candle already implements CLIP and
BLIP; SigLIP 2 in Candle is **UNVERIFIED** (do not claim a Rust
port exists until a crate API is fetched).

### 2. Audio: ASR vs audio embeddings

**Local ASR (timestamped chunks).**

| Stack | What was fetched | Licence / runtime | Notes |
|-------|------------------|-------------------|-------|
| whisper.cpp | [ggml-org/whisper.cpp README](https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/README.md); latest tag **[v1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5)** (published **2026-10-06**) | MIT badge on README | C/C++, CPU, Apple Silicon Metal/Core ML, no Python. README memory table: tiny 75 MiB disk / ~273 MB RAM … large 2.9 GiB / ~3.9 GB. CLI example converts input with **ffmpeg** to 16-bit WAV. Phase-5 pin should start from this tag (or newer) and be re-checked in that PR. |
| faster-whisper | [SYSTRAN/faster-whisper README](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/README.md) + [LICENSE](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/LICENSE); latest tag **[v1.2.1](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)** (published **2025-10-31**; no later GitHub release on fetch) | MIT; Python 3.9+ | CTranslate2; segment `start`/`end`; optional `word_timestamps`; Silero VAD; decodes via PyAV (bundles FFmpeg libs — no system ffmpeg required, per README). MCP/Python path only; not a CLI default. |
| distil-whisper | [distil-whisper/distil-small.en](https://huggingface.co/distil-whisper/distil-small.en); [arXiv:2311.00430](https://arxiv.org/abs/2311.00430) | `mit`; Hub **166.1M** | English-only for this checkpoint. Compatible with faster-whisper per that README. |
| OpenAI Whisper checkpoints | [openai/whisper-tiny](https://huggingface.co/openai/whisper-tiny) (**37.8M**), [openai/whisper-small](https://huggingface.co/openai/whisper-small) (**241.7M**); [arXiv:2212.04356](https://arxiv.org/abs/2212.04356) | `apache-2.0` | Candle ships a Whisper example (`tiny.en` default, timestamps on) at [candle-examples/whisper](https://github.com/huggingface/candle/blob/main/candle-examples/examples/whisper/main.rs). |
| NVIDIA Parakeet TDT 0.6B v2 | [nvidia/parakeet-tdt-0.6b-v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) | **`cc-by-4.0`**; card says commercial/non-commercial use | English; word-level timestamps; NeMo/Python; 0.6B. Strong quality on the card's WER table (not re-run). Heavier Python stack than whisper.cpp. |

**Diarization.** [pyannote/speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1)
is tagged `license:mit` **and is gated** on the Hub (accept terms +
token). Out of the first sequence: extra auth, extra model, and
speaker labels are not required to search a voice note.

**Audio embeddings.**

| Model | Hub URL | What was fetched | Licence |
|-------|---------|------------------|---------|
| LAION CLAP | https://huggingface.co/laion/clap-htsat-fused ([arXiv:2211.06687](https://arxiv.org/abs/2211.06687)) | Hub **153.6M**, `apache-2.0` | Prefer this if a later `audio-embed` table exists. |
| Microsoft CLAP (msclap) | https://huggingface.co/microsoft/msclap ([arXiv:2309.05767](https://arxiv.org/abs/2309.05767)) | Card `license: ms-pl`. Hub overview printed **no** parameter count (not invented here). | **MS-PL — do not default.** |

Useful for "find songs that sound like X" where ASR fails (music,
ambience). Useless for "what did we decide on the call?" — that is
a transcript problem. Candle CLAP support is **UNVERIFIED**.

**Recommendation for audio.** Default: **transcript-only**,
timestamped segments embedded with `gte-small`, hybrid FTS on the
words. Runtime preference: **whisper.cpp subprocess** (MIT, CPU +
Apple Silicon, no Python) or in-process Candle Whisper if the
existing `candle` feature can load `tiny`/`small` without a new
crate graph. `tiny` / `tiny.en` / `small.en` are the first pins;
larger models stay configurable. CLAP is a later optional table.
Diarization is later and must remain opt-in (gated Hub).

### 3. Video: keyframes + ASR + time codes

No local-first product reviewed here indexes "the video" as one
vector. The workable decomposition:

1. **Demux** an audio track (ffmpeg subprocess or a decoder crate).
2. **ASR** that track with the audio phase; each segment carries
   `start_ms` / `end_ms`.
3. **Select frames**: scene-change or fixed-interval keyframes;
   cap count and pixels the way PDF images already cap
   `MAX_IMAGES` / `MAX_TOTAL_BYTES` / `MIN_DIMENSION`.
4. **Caption and/or embed** those frames with the image phase.
5. **Return** hits as `{file_path, start_ms, end_ms, content, score}`.
   A client can seek a player; ragfs does not ship a player.

Cloud contrast: [Twelve Labs Embed v2](https://docs.twelvelabs.io/api-reference/create-embeddings-v2/create-embeddings.mdx)
uses Marengo 3.0 / 3.5 over HTTP (`x-api-key`). Sync limits (from
that page): Marengo 3.5 audio/video up to 30 seconds; Marengo 3.0
up to 10 minutes; longer files go through async tasks. This
contradicts ADR-001 (local-first, no per-query API). It is prior
art for *result shape* (time-ranged embeddings), not a backend.

Keyframe policy is still chosen in the phase-6 PR. A current
BSD-3-Clause candidate is
[PySceneDetect v0.7.2](https://github.com/Breakthrough/PySceneDetect/releases/tag/v0.7.2)
(published **2026-10-12**; PyPI
[scenedetect 0.7.2](https://pypi.org/project/scenedetect/0.7.2/),
BSD-3-Clause). That release is Python + OpenCV (or PyAV) and
changes default histogram/hash thresholds — it is **not** a
default CLI dependency. ffmpeg `select='gt(scene,…)'` remains
the lighter subprocess alternative. **No recall or speed number
is claimed here**; detector quality stays **UNVERIFIED** on ragfs
fixtures.

**Recommendation for video.** Last. Compose phases 1–5. Feature
`video` implies `audio` + image caption/OCR. Default-off.
No thumbnails in MCP/FUSE JSON in the first video PR (bytes and
inode growth; see §5). Time codes are mandatory on every video-
derived chunk.

### 4. How comparable tools do it

| Tool | What was fetched | Pattern | Fit for ragfs |
|------|------------------|---------|---------------|
| **LlamaIndex** | [Multi-modal models](https://developers.llamaindex.ai/python/framework/module_guides/models/multi_modal/); [`MultiModalVectorStoreIndex`](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/indices/multi_modal/base.py) | **Separate** text store and image store. Default image embedder `clip:ViT-B/32`. Optional `is_image_to_text`. Fusion at retrieve time. | Same split (text table vs image table) is the right store shape. Default CLIP matches Haystack/Marqo. |
| **Haystack** | [ImageFileToDocument](https://docs.haystack.deepset.ai/docs/imagefiletodocument); [SentenceTransformersDocumentImageEmbedder](https://docs.haystack.deepset.ai/docs/sentencetransformersdocumentimageembedder); [LLMDocumentContentExtractor](https://docs.haystack.deepset.ai/docs/llmdocumentcontentextractor) | Pipeline: wrap image path → CLIP embed (`sentence-transformers/clip-ViT-B-32` default; also lists jina-clip-v1/v2) **or** VLM caption via a vision `ChatGenerator`. | ragfs-python already exposes Haystack adapters. Caption path ≡ this ADR's phase 1–3. CLIP path ≡ phase 4. Do not pull jina-clip-v2 into the adapter default (NC). |
| **Marqo** | [Unstructured multimodal index](https://marqo.pages.dev/latest/other-resources/cookbook/indexes/creating-an-unstructured-index/multimodal-index/); [model selection](https://marqo.pages.dev/latest/other-resources/cookbook/model-selection/multimodal-search/) | One CLIP/OpenCLIP model; `treatUrlsAndPointersAsImages`; weighted `multimodal_combination` of text + image into **one** vector. | Weighted fusion into a single vector loses "query the photo vs query the filename" control. Prefer LlamaIndex's two stores. |
| **Twelve Labs** | Embed v2 docs cited above | Cloud-native video/audio/image embeddings (Marengo). | Result-shape prior art only. |
| **Vespa** | [Embedding](https://docs.vespa.ai/en/embedding.html) (fetched; multimodal subsection is VoyageAI API models, not a local CLIP embedder) | Multimodal embeddings via **VoyageAI hosted API**. | Same reject as Twelve Labs for the product path. Useful as "schema can hold several tensor fields". |
| **LanceDB** (ragfs already depends on this) | See the pin / v0.40.0 note below; [OpenCLIP integration](https://docs.lancedb.com/integrations/embedding/openclip); [Multimodal blobs](https://docs.lancedb.com/tables/multimodal); [Lance file format 2.2](https://www.lancedb.com/blog/lance-file-format-2-2-taming-complex-data) | Python `open-clip` embedding function (default ViT-B-32, `laion2b_s34b_b79k`, **CPU**). Binary / large-binary blob columns for raw bytes. Text *or* image queries. Blob V2 is a **format ≥2.2** feature. | Store layer already chosen (ADR-002). The Python helper is **not** what `ragfs-store` uses; embeddings are produced in Rust by Candle. Blob columns are optional later (thumbnails / raw frames); v1 stores paths + text, not image bytes in Lance. **Do not bump the crate in this ADR.** |

Consensus worth copying: **two (or N) vector spaces**, CLIP-class
defaults, caption as an alternative, time ranges for A/V, no
requirement to store raw media in the vector table.

**ragfs LanceDB pin vs upstream 0.40.0 (upgrade dependency).**
This is a note for a *later* Cargo PR, not a change in this ADR.

| Fact (fetched) | Source |
|----------------|--------|
| ragfs workspace pin | `Cargo.toml` `lancedb = "0.37.1"` with an intentional skip of 0.38.0 (`Error::Http` is `#[cfg(feature = "remote")]` while `src/job.rs` uses it under the default feature set). `Cargo.lock` resolves `lancedb` **0.37.1** and `lance` **10.0.0**. |
| Current Rust crate | crates.io [`lancedb` 0.40.0](https://crates.io/crates/lancedb) published **2026-10-07**; depends on `lance =13.0.0`. GitHub [lancedb/lancedb v0.40.0](https://github.com/lancedb/lancedb/releases/tag/v0.40.0) (same date) lists a **Breaking Changes** section and states the release uses **Lance 13.0.0**. |
| Current format crate | crates.io [`lance` 13.0.0](https://crates.io/crates/lance) published **2026-10-07**; repository metadata is **https://github.com/lance-format/lance** (repo moved off the older `lancedb/lance` path). |
| Blob V2 needs format ≥2.2 | Lance blog [File Format 2.2](https://www.lancedb.com/blog/lance-file-format-2-2-taming-complex-data): Blob V2 is introduced in format 2.2 (`data_storage_version="2.2"`); writers must opt in. Blog compression / “68x faster blob reads” figures are **vendor claims**, not re-run. |

Phase 1–3 do not need 0.40.0 or format 2.2: they write text / captions
into the existing 384-d chunks table. A native image table (phase 4)
and any later blob/thumbnail work **depend on a dedicated upgrade
PR** that (a) re-checks whether the 0.38 `Error::Http` default-feature
bug is gone on 0.40, (b) takes the 0.40 breaking list, (c) moves
`lance` 10 → 13, and (d) only then considers `data_storage_version="2.2"`
if ragfs actually stores blobs (this ADR’s v1 does not). Do not
silently bump `lancedb` in a multimodal implementation PR.

### 5. Local-first constraints

**CPU-only and Apple Silicon.** ADR-001 already chose Candle for
text. Candle CLIP + Candle Whisper run on CPU; Candle documents
Accelerate on macOS. whisper.cpp documents Metal and Core ML on
Apple Silicon. SigLIP 2 So400m / g and ColQwen (~2B) are not
plausible default CPU indexers; Base/tiny/small pins are.

**Model sizes (only numbers from fetched pages).**
`gte-small` Hub **33.4M**, MIT (status quo). BLIP is already the
vision pin. Whisper tiny 75 MiB ggml / ~273 MB RAM (whisper.cpp
README). SigLIP 2 base Hub 375.2M dual-encoder. nomic-embed-vision
92.9M. Anything ≥2B stays opt-in and documented as such.

**Licences — do not default.**

- `jinaai/jina-clip-v2`: **CC-BY-NC 4.0** (https://huggingface.co/jinaai/jina-clip-v2)
- `jinaai/jina-embeddings-v5-omni-small` / `-nano`: **CC-BY-NC 4.0** (https://huggingface.co/jinaai/jina-embeddings-v5-omni-small) — omni text/image/video/audio; **reference only**
- `Qwen/Qwen2.5-VL-3B-Instruct`: **qwen-research / NC** (https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct)
- Prefer if a Qwen VLM is ever opted in: `Qwen/Qwen3-VL-2B-Instruct`, `Qwen/Qwen3.5-0.8B`, `Qwen/Qwen3.5-2B` — all Hub **`apache-2.0`**
- `vidore/colqwen2.5-v0.2` / `vidore/colqwen2.5-base`: **qwen-research** via Qwen2.5-VL-3B-Instruct (https://huggingface.co/vidore/colqwen2.5-v0.2)
- `vidore/colpali-v1.3`: adapter MIT, **Gemma / PaliGemma base** (https://huggingface.co/vidore/colpali-v1.3, https://huggingface.co/vidore/colpaligemma-3b-pt-448-base)
- ColPali family (`colpali`, `colpali-v1.3`, `colqwen2-v1.0`, `colqwen2.5-v0.2`): **no official ONNX or GGUF** on the Hub cards/listings
- `microsoft/msclap`: **MS-PL** (https://huggingface.co/microsoft/msclap)
- `pyannote/speaker-diarization-3.1`: MIT **but gated** (https://huggingface.co/pyannote/speaker-diarization-3.1)
- `openai/clip-vit-base-patch32`: **Hub licence tag missing** (https://huggingface.co/openai/clip-vit-base-patch32); do not treat weights as Apache-cleared

Prefer Apache-2.0 / MIT / BSD-3 / CC-BY-4.0 (Parakeet) for anything
that ships as a default pin.

**Rust-native vs Python vs ONNX vs subprocess.**

| Path | Use | Do not use for |
|------|-----|----------------|
| Candle in-process (existing `candle` / `vision`) | CLIP, BLIP, Whisper when the example path is productized | Models Candle does not implement (unverified: SigLIP 2, CLAP, ColQwen) |
| Subprocess, pinned binary | whisper.cpp CLI; tesseract; optional ffmpeg | Unbounded `ffmpeg -i userfile` without args/timeouts |
| `ort` / ONNX Runtime | Later, if a specific ONNX (SmolVLM-256M has an `onnx` Hub tag) is the only CPU path | Default graph in phase 1 |
| Python (faster-whisper, NeMo Parakeet, Haystack VLM) | MCP/Python adapters may call these **outside** the Rust CLI | New required runtime for `ragfs index` |

**Cargo features (all default-off except today's `vision`).**

| Feature | Crate surface | What it unlocks |
|---------|---------------|-----------------|
| `vision` | already exists | BLIP captioner. Phase 1 *uses* it; does not add deps. |
| `ocr` | `ragfs-extract` | Tesseract subprocess. |
| `vision-embed` | `ragfs-embed` + `ragfs-store` | CLIP / SigLIP 2 second table. |
| `audio` | `ragfs-extract` + indexer | ASR → timestamped text chunks. |
| `video` | extract + index | Keyframes + ASR. Implies `audio`. |
| `audio-embed` | later | CLAP table. |

No feature in this sequence is on by default. `full` may grow only
in a release PR after the owner accepts, not in the ADR PR.

### 6. Index schema, MCP / FUSE, ADR-009

**Schema (additive; new `CHUNKS_SCHEMA_VERSION` only when a column
is required).**

- Keep the existing chunks table as the **text / caption / transcript
  / OCR** table. Still 384-d `gte-small` unless the user changes the
  embedder (ADR-010 `--force`).
- Add nullable `start_ms` / `end_ms` (`UInt32` or `UInt64`) and
  `modality` (`Utf8`: `text` \| `image` \| `audio` \| `video`) when
  audio/video land. Schema v3. Old rows: `modality = text`, times
  null. FTS and ANN stay on this table.
- Native image (and later audio) vectors: **new table**
  `multimodal_chunks` (name fixed at implementation) with its own
  `FixedSizeList` width and sidecar keys
  `embedding_model_image` / `embedding_model_audio` next to today's
  `embedding_model`. Opening a store with a different image model
  id fails closed (ADR-010 rule). Mixed spaces in one list are
  forbidden.
- `Modality` enum: add `Video` when video ships; keep `Audio`
  (already present).
- `ContentType`: start using `ImageCaption`; add
  `AudioTranscript { start_ms, end_ms }` and
  `VideoFrame { start_ms }` (or store times only on the chunk
  columns — pick one in the schema PR, test both query paths).
- Do **not** store raw image/audio bytes in Lance in v1
  (`ExtractedImage.data` is already an in-memory footgun). Path +
  optional page/time is enough. Blob columns are a later PR if a
  client needs thumbnails, and that PR must first upgrade past
  the 0.37.1 pin: **Blob V2 requires Lance file format ≥2.2**,
  which is not what `lance` 10.0.0 (today’s lockfile) writes by
  default.

**MCP and FUSE result shape.** Additive JSON keys, existing keys
stable (same compatibility rule as ADR-008 receipts):

```json
{
  "file": "talks/demo.mp4",
  "score": 0.81,
  "content": "…transcript or caption…",
  "byte_range": [0, 0],
  "line_range": null,
  "modality": "video",
  "start_ms": 142000,
  "end_ms": 147500
}
```

`byte_range` for a media file may be zero or the container byte
span; clients should prefer `start_ms`. **No thumbnails** in the
first MCP/FUSE PR: 500-char text is already the truncate policy;
images in `.query` JSON or FUSE inodes would enlarge every listing
and create a second decoder on the read path. A later opt-in
`.ragfs/.thumbs/` can be its own ADR.

**ADR-009 memory benchmark.** First-wave datasets are conversational
text (LongMemEval, LoCoMo, BEAM, synthetic versioned facts).
Multimodal is **out of band**: do not change the default embedder,
do not add image items to versioned-facts, do not publish a
"multimodal memory" score from this work. Threat to validity to
record when a later phase exists: a tree that is half screenshots
will look worse on a text-only protocol. Pins (`gte-small`, 384-d)
stay the published text pin.

Prior art for *multimodal memory* (not a first-wave harness
target): **OpenVLHarness** — Zhou et al.,
[arXiv:2610.26860](https://arxiv.org/abs/2610.26860)
(“OpenVLHarness: Real World Visual Agentic Tool-Use with
Multimodal Memory”, submitted **2026-10-19**;
[HF paper](https://huggingface.co/papers/2610.26860);
project [openvlharness.github.io](https://openvlharness.github.io/);
code [uclanlp/OpenVLHarness](https://github.com/uclanlp/OpenVLHarness)).
The paper describes a capability layer plus **persistent
multimodal memory** (images, structured data, web references as
addressable artifacts). Reported score deltas (e.g. +9.7–12.6
over no-tool baselines) are **author claims**, not harness
results. Record it next to ADR-009 as a later-phase candidate
corpus / protocol to *cite*, not as a number to chase, and do
not vendor their evaluation set in ragfs.

### 7. Security (media-specific)

ADR-010 exclusions, denylist, `.ragfsignore`, and purge apply to
**all** media. A `.jpg` inside `.ssh` or a `.wav` named like a
secret file is not a special case.

Additional controls for implementation PRs:

- **Decompression bombs.** PDF already bounds count, decompressed
  bytes, and minimum dimension (`pdf.rs` 89–91, FlateDecode
  `take(budget+1)`). `ImageExtractor` does **not**:
  `image::load_from_memory` (`image.rs` 143–144) decodes the full
  bitmap. Phase 1 must add a pixel-budget (and keep `max_file_size`).
  Reject images whose `width * height` exceeds a documented cap
  before caption/OCR/embed.
- **Parser attack surface.** `lopdf`, `image`, and any future media
  crate parse untrusted bytes. Prefer the already-used crates;
  do not add a second JPEG decoder. No new image formats in phase 1.
- **ffmpeg.** whisper.cpp's own README uses ffmpeg to make 16-bit
  WAV. If ragfs shells out: fixed argv (no user-controlled flags),
  timeout, output size cap, duration cap, no shell, no linked
  libavcodec in the default binary. Linked ffmpeg is a CVEs-follow-
  the-distro problem and is out of the first sequence.
- **Subprocess vs linked.** tesseract and whisper.cpp as **optional
  binaries on `PATH`** (or a config path) keep them out of
  `Cargo.lock` until a later vendoring PR. Missing binary → skip
  the file with a warning, do not fail the whole index.
- **Size and duration.** Reuse `max_file_size` (50 MiB). Add
  `index.max_media_duration_secs` (suggested default 30 minutes;
  value fixed in the audio PR, not here as a measured optimum).
  Skip + delete-if-previously-indexed, same as oversized files
  (`indexer.rs` 676–684).
- **No remote fetch.** Marqo/LanceDB helpers that pull image URLs
  are not copied. Index local paths only.

### Options considered

**A — Caption-then-embed only (no native image vectors).**
Pros: one table, one model fingerprint, ADR-009 intact, reuses
`vision` + `gte-small`, hybrid FTS works on captions/OCR.
Cons: "find photos of red bicycles" fails if the captioner said
"a vehicle"; no image-to-image.

**B — Native CLIP/SigLIP only (no captions).**
Pros: true visual retrieval; matches LlamaIndex/Haystack/Marqo
defaults. Cons: new space (breaks a naive single-table upsert);
no FTS on the photo; screenshots with small text lose to OCR;
Candle SigLIP 2 unverified.

**C — Cloud multimodal APIs (Twelve Labs, VoyageAI via Vespa,
hosted Jina).**
Pros: video-native quality. Cons: rejects ADR-001 (privacy,
offline, cost).

**D — Single weighted fusion vector (Marqo `multimodal_combination`).**
Pros: one ANN. Cons: cannot filter "image-only" vs "transcript-only";
weights are a hidden retrieval knob.

**E — Python sidecar (faster-whisper + OpenCLIP + Haystack).**
Pros: fastest path to SOTA checkpoints. Cons: new runtime for a
Rust CLI; MCP already has Python, the binary should not need it.

**F — Do video in the same PR as images.**
Pros: one story. Cons: ffmpeg + keyframes + ASR + schema at once;
not a small PR.

### Decision (detail)

**Choose A then B, in that order, with C rejected, D rejected as
the default, E rejected for the CLI, F rejected.**

Phase 1 is A on the code that already exists (wire captions and
`ImageCaption` into `process_file`). Phase 3 adds OCR to A.
Phase 4 is B in a second table (SigLIP 2 Base or OpenCLIP/CLIP,
Apache/MIT software, Hub licence checked again in that PR).
Audio is A-for-speech (transcript in the text table). Video
composes A+B after audio. Cloud APIs stay documentation
contrast only.

### Phased plan

Each phase is **one future PR** after this ADR is accepted **and**
after the ADR-010 sequence + 0.3.0 (see Context). Tests and
acceptance criteria are required on every PR. No phase adds a
dependency in *this* docs PR.

| Phase | Future PR | Scope | Tests / acceptance | Flag |
|-------|-----------|-------|--------------------|------|
| **0** | This PR | ADR only. Status Proposed. | Docs render; TOC + Summary updated. No `Cargo.toml` / `pyproject` / version / tag. | n/a |
| **1** | `feat(index): index image captions into ImageCaption chunks` | If `ExtractedImage.caption` or filename+geometry text is present, emit `ContentType::ImageCaption` chunks and embed them with `gte-small`. Wire `ImageExtractor::with_captioner` when `--features vision` and config enables it. Apply the same captioner to PDF `ExtractedImage`s (today `caption: None`). Pixel-budget on `ImageExtractor` decode. | Unit: captioned PNG → chunk content contains caption, `content_type` serializes `image_caption`. Uncaptioned → metadata sentence still indexed. PDF JPEG fixture → one image chunk after captioner stub. Decode of a huge-header PNG fails closed. Integration: `ragfs index` + `query` returns the caption text. CLI without `vision` unchanged. | existing `vision` for BLIP; caption-less metadata path stays default |
| **2** | `feat(store): modality and time-range columns (schema v3)` | Additive `modality`, `start_ms`, `end_ms`. Sidecar keys reserved for per-modality model ids. `SearchResult` + FUSE + MCP JSON gain optional fields (absent ≡ text). | Old v2 index opens; nulls backfilled. New rows round-trip. Receipts remain additive. No behaviour change for text queries. | none |
| **3** | `feat(extract): OCR images and PDF pages` | tesseract on `PATH` (or config). Text merged into the caption/metadata chunk. Skip if binary missing. | Fixture screenshot with known word is found via `query` and via FTS. Missing tesseract → warning, index continues. Pixel-budget still applies. | `ocr` default-off |
| **4** | `feat(embed): CLIP/SigLIP image table` | Second Lance table. Query path: embed the query with the image text tower, search that table, merge/rerank with text hits (simple score interleave is enough; no learned fusion). Pin one Apache-2.0 model (SigLIP 2 Base **or** OpenCLIP, re-verified in the PR). Refuse open if sidecar image model mismatches (ADR-010 rule). | Text-only index still works with the feature off. Feature on: query "red bicycle" hits a bicycle photo whose caption omitted the word (fixture). Model-id mismatch errors without `--force`. Dimension ≠ 384. | `vision-embed` default-off |
| **5** | `feat(extract): timestamped audio transcripts` | MIME `audio/mpeg`, `audio/wav`, `audio/x-wav`, `audio/mp4` (audio-only) as a starting set — exact list fixed in the PR from what the decoder accepts. Whisper tiny/small via whisper.cpp **or** Candle. Chunks carry `start_ms`/`end_ms`. Duration + size limits. | WAV fixture with known phrase → query hit with a non-null time range in CLI JSON, FUSE `.query`, and MCP `ragfs_search`. Over-duration file skipped and purged. Missing binary → skip + warn. | `audio` default-off |
| **6** | `feat(extract): video keyframes and ASR track` | Video MIME starting with `video/mp4` (the current unsupported test). Keyframe cap. Reuse phase 1/3/5. | MP4 fixture with speech + a distinct visual → text query hits the transcript range; a visual query (if phase 4 on) hits a frame near that time. `video/mp4` registry test updated. ffmpeg/decoder failure is a skip, not a panic. | `video` default-off |
| **7** | optional, own PR | CLAP table; diarization; ColQwen late-interaction; thumbnails. Each needs its own licence re-check. | As specified in that PR. | new flags, default-off |

Phases 4 and 5 may run in parallel after 2. Phase 6 requires 5 and
1 (3 and 4 optional but recommended). Phase 7 is not scheduled
until the owner asks.

### Non-goals

- Changing the default text embedder away from `gte-small`.
- Shipping a cloud video/image API.
- Thumbnails or raw media blobs in Lance / FUSE in the first
  sequence.
- Making `vision`, `ocr`, `audio`, or `video` default-on.
- Vendoring ffmpeg or tesseract into the crate graph in phase 1–3.
- Implementing any phase after 0 in *this* change.
- Version bump or tag.
- Content-level secret scanning of image/audio bytes (still a later
  ADR, as in ADR-010).

### Rationale
The useful increment is not "add CLIP". It is "make the image path
that already exists actually searchable, under the same exclusion
and fingerprint rules as text." Caption + OCR reuse one embedding
space and keep ADR-009 honest. A second table is how every
serious local multimodal index (LlamaIndex, Haystack, LanceDB's
own CLIP helper) avoids mixing dimensions. Audio as text is how
voice notes become `ragfs query` hits on CPU. Video is that
pipeline plus a clock. Licences that are NC, research-only, or
Gemma-gated are documented so a future PR cannot quietly default
them.

### Trade-offs

**Pros**

- Smallest first PR is a wiring fix, not a new model.
- One default embedding space for all *language* derived from media.
- Native visual search is possible later without rewriting text
  indexes.
- Default-off flags keep the 0.3.0 binary and the memory bench pin
  stable.
- Attack surface grows per phase (pixel budget, then subprocess,
  then demux), not all at once.

**Cons**

- Caption-only retrieval misses uncaptioned visual similarity until
  phase 4.
- Two tables mean two ANN queries and a merge.
- whisper.cpp/tesseract/ffmpeg as PATH binaries are an operator
  dependency.
- ColPali-quality page retrieval is deferred.
- CPU indexing of large video corpora will be slow; no number is
  claimed here.

### Alternatives considered

| Alternative | Rejected because |
|-------------|------------------|
| Native CLIP as phase 1 | Leaves the existing caption pipeline dark; mixes or forks the 384-d table before ADR-010's model check ships |
| Default jina-clip-v2, jina-embeddings-v5-omni-*, Qwen2.5-VL-3B, or colqwen2.5 | CC-BY-NC / qwen-research |
| Bump `lancedb` to 0.40.0 inside a multimodal PR | Separate dep PR: Lance 13 + 0.40 breaking list; Blob V2 unused until we store blobs |
| Default ColPali v1.3 | Gemma / PaliGemma base + multi-vector store + no official ONNX/GGUF |
| Default microsoft/msclap | MS-PL |
| Twelve Labs / VoyageAI in-process | Network, keys, contradicts ADR-001 |
| Marqo-style single fused vector | Hides modality; harder to filter transcripts vs frames |
| Python-only ASR in the CLI | Splits the install story; MCP may use it later, the binary should not require it |
| Linked libav* in default features | Parser CVEs on every host; subprocess + caps first |
| Video in the same PR as images | ffmpeg + schema + ASR is not one small PR |
| Implement in this PR | Owner has not accepted the design; this change is the Proposed ADR only |
| Start before ADR-010 / 0.3.0 | Would index more media under the weaker exclude list and without a fail-closed model fingerprint |

### Sources verified

Checked against the official paper, Hub card, repository README, or
vendor docs while writing this ADR (dates in those records, not
this file's clock). Social posts are not sources.

**This repo** @ `e310209c` (ADR-010) and the code paths listed under
"Verified on `main`": `crates/ragfs-core/src/{types,traits,error}.rs`,
`crates/ragfs-extract/src/{image,vision,pdf,registry}.rs`,
`crates/ragfs-extract/Cargo.toml`, `crates/ragfs/src/{main,config}.rs`,
`crates/ragfs/Cargo.toml`, workspace `Cargo.toml` (`lancedb = "0.37.1"`),
`Cargo.lock` (`lance` 10.0.0), `crates/ragfs-index/src/indexer.rs`,
`crates/ragfs-store/src/{schema,lancedb}.rs`,
`crates/ragfs-fuse/src/filesystem/mod.rs`,
`crates/ragfs-mcp/src/ragfs_mcp/server.py`,
`docs/API.md`, `docs/CONFIGURATION.md`, `docs/ARCHITECTURE.md`,
ADR-001/002/009/010 in this file.

**Images (Hub URLs for every model named).** CLIP paper
arXiv:2103.00020; https://huggingface.co/openai/clip-vit-base-patch32
(no licence tag);
[openai/CLIP LICENSE](https://raw.githubusercontent.com/openai/CLIP/main/LICENSE)
(MIT software); Candle CLIP docs.rs + example; SigLIP 2
arXiv:2502.14786 and
[README_siglip2.md](https://github.com/google-research/big_vision/blob/main/big_vision/configs/proj/image_text/README_siglip2.md);
https://huggingface.co/google/siglip2-base-patch16-224 (`apache-2.0`,
Hub 375.2M);
https://huggingface.co/jinaai/jina-clip-v2 (**CC-BY-NC-4.0**,
Hub 865.3M, arXiv:2412.08802);
https://huggingface.co/jinaai/jina-embeddings-v5-omni-small
(**CC-BY-NC-4.0**, Hub 1626.3M, arXiv:2605.08384; omni
text/image/video/audio; **no** Hub repo `jinaai/jina-embeddings-v5-omni`);
https://huggingface.co/jinaai/jina-embeddings-v5-omni-nano;
https://huggingface.co/nomic-ai/nomic-embed-vision-v1.5 and
https://huggingface.co/nomic-ai/nomic-embed-text-v1.5 (`apache-2.0`,
arXiv:2406.18587);
https://huggingface.co/vidore/colpali ,
https://huggingface.co/vidore/colpali-v1.3 ,
https://huggingface.co/vidore/colpaligemma-3b-pt-448-base
(`license:gemma`),
https://huggingface.co/vidore/colqwen2-v1.0 ,
https://huggingface.co/vidore/colqwen2-base ,
https://huggingface.co/vidore/colqwen2.5-v0.2 ,
https://huggingface.co/vidore/colqwen2.5-base
(arXiv:2407.01449; ColPali family: **no official ONNX/GGUF**;
colqwen2.5: **qwen-research** via Qwen2.5-VL-3B);
[Gemma Terms](https://ai.google.dev/gemma/terms);
https://huggingface.co/Salesforce/blip-image-captioning-base
(`bsd-3-clause`, arXiv:2201.12086);
https://huggingface.co/HuggingFaceTB/SmolVLM-256M-Instruct ,
https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct ,
https://huggingface.co/HuggingFaceTB/SmolVLM-Instruct
(arXiv:2504.05299, `apache-2.0`; 256M/500M have `onnx` tags);
https://huggingface.co/microsoft/Florence-2-base (`mit`, card 0.23B,
arXiv:2311.06242);
https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct README +
[LICENSE](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/raw/main/LICENSE)
(**qwen-research**, non-commercial);
https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct (`apache-2.0`,
Hub 2127.5M);
https://huggingface.co/Qwen/Qwen3.5-0.8B (`apache-2.0`, Hub 873.4M);
https://huggingface.co/Qwen/Qwen3.5-2B (`apache-2.0`, Hub 2274.1M);
[colpali-engine 0.3.18](https://pypi.org/project/colpali-engine/0.3.18/)
(2026-08-22; `transformers>=5.3.0,<6.0.0`);
https://huggingface.co/thenlper/gte-small (`mit`, Hub 33.4M);
[Tesseract LICENSE](https://raw.githubusercontent.com/tesseract-ocr/tesseract/main/LICENSE)
(Apache-2.0).

**Audio.** whisper.cpp README (MIT, memory table, ffmpeg note);
[whisper.cpp v1.9.5](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.9.5)
(2026-10-06);
faster-whisper README + MIT LICENSE;
[faster-whisper v1.2.1](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)
(2025-10-31; latest on fetch);
https://huggingface.co/openai/whisper-tiny ,
https://huggingface.co/openai/whisper-small (`apache-2.0`,
arXiv:2212.04356);
https://huggingface.co/distil-whisper/distil-small.en (`mit`,
arXiv:2311.00430);
Candle Whisper example;
https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2 (`cc-by-4.0`);
`laion/clap-htsat-fused` (https://huggingface.co/laion/clap-htsat-fused,
`apache-2.0`, arXiv:2211.06687);
`microsoft/msclap` (https://huggingface.co/microsoft/msclap, **MS-PL**);
`pyannote/speaker-diarization-3.1`
(https://huggingface.co/pyannote/speaker-diarization-3.1, `mit`, gated).

**Video / vendors.** Twelve Labs
[Create sync embeddings](https://docs.twelvelabs.io/api-reference/create-embeddings-v2/create-embeddings.mdx);
LlamaIndex multimodal module + `MultiModalVectorStoreIndex` source;
Haystack ImageFileToDocument, SentenceTransformersDocumentImageEmbedder,
LLMDocumentContentExtractor;
Marqo unstructured multimodal index + model-selection pages;
Vespa embedding guide (VoyageAI multimodal);
LanceDB OpenCLIP + multimodal blob docs;
[open_clip LICENSE](https://raw.githubusercontent.com/mlfoundations/open_clip/main/LICENSE)
(MIT software);
crates.io [lancedb 0.40.0](https://crates.io/crates/lancedb)
(2026-10-07, `lance =13.0.0`) and
[lance 13.0.0](https://crates.io/crates/lance)
(repo https://github.com/lance-format/lance);
[lancedb v0.40.0 release](https://github.com/lancedb/lancedb/releases/tag/v0.40.0)
(Breaking Changes + Lance 13);
[Lance file format 2.2 / Blob V2](https://www.lancedb.com/blog/lance-file-format-2-2-taming-complex-data);
[PySceneDetect v0.7.2](https://github.com/Breakthrough/PySceneDetect/releases/tag/v0.7.2)
(2026-10-12, BSD-3-Clause);
[scenedetect 0.7.2](https://pypi.org/project/scenedetect/0.7.2/);
OpenVLHarness [arXiv:2610.26860](https://arxiv.org/abs/2610.26860)
(2026-10-19), [HF paper](https://huggingface.co/papers/2610.26860),
[uclanlp/OpenVLHarness](https://github.com/uclanlp/OpenVLHarness).

**UNVERIFIED** in this pass (do not treat as facts):

- SigLIP 2 availability inside `candle-transformers`
- CLAP (LAION or msclap) in Candle
- A Hub `license:` tag on `openai/clip-vit-base-patch32` weights
- CPU latency or VRAM for any model on ragfs hardware
- PySceneDetect (including v0.7.2) recall/precision on ragfs fixtures,
  or any keyframe algorithm's quality
- Whether LanceDB's *Rust* crate exposes the Python `open-clip`
  embedding function (the Python docs were fetched; the Rust API
  was not)
- Whether the 0.38.0 `Error::Http` default-feature bug is gone in
  `lancedb` 0.40.0 (crates.io lists 0.40.0; the 0.38 source was not
  re-diffed here)
- Community / unofficial ONNX or GGUF conversions of the ColPali
  family (official Hub repos listed above have none)
- A parameter count for `microsoft/msclap` (Hub overview omitted it)
- Whether a future commercial grant exists for Qwen2.5-VL-3B-Instruct
  (the fetched LICENSE is research / NC unless separately licensed)
- Reconciliation of Hub **1626.3M** vs card “~1.74B” on
  `jina-embeddings-v5-omni-small`
- OpenVLHarness author-reported deltas as ragfs harness numbers
  (cite the paper; do not copy scores into ADR-009 results)

**Vendor / author claims (labelled, not adopted as measurements):**
Lance format 2.2 blog storage and “68x faster blob reads”;
crates.io lance README “100x faster than Parquet”;
Qwen3-VL card “most powerful … to date”;
jina-embeddings-v5-omni-small card “open-weight frontier” /
Table 1 scores; OpenVLHarness +9.7–12.6 tool-use deltas;
Twelve Labs / Marqo / vendor latency pages.


## ADR-012: Native Block-Device Filesystem vs Semantic Volume

### Status
Accepted (2026-10-20, decided by Chief of Staff under Gianluca's
delegation). Full text:
[`docs/adr/012-native-filesystem-vs-semantic-volume.md`](adr/012-native-filesystem-vs-semantic-volume.md).

This record is design only. It does not implement code, change
Cargo or Python packages, update `docs/ROADMAP.md`, or create
issues. It does not schedule work against 0.3.0 (ADR-010,
#179–#186).

### Decision
Native block-device filesystem (`mkfs.ragfs`, superblock,
`mount -t ragfs`, kernel driver): **REJECTED**. Current model
stays: documents canonical on the host FS; embeddings derived
and rebuildable in LanceDB (current FUSE architecture).
`ragfs volume` (versioned manifest +
`init` / `check` / `repair` / `upgrade`): **DEFERRED** until
after the 0.3.0 release, then its own ADR. It never touches
#179–#185. Schema v3 (#188) stays the Lance column bump.

---

## Summary

| Decision | Key Driver |
|----------|-----------|
| Candle embeddings | Privacy, offline capability |
| LanceDB | Embedded, hybrid search |
| Propose-Review-Apply | Agent safety |
| FUSE interface | Universal compatibility |
| Registry pattern | Extensibility |
| Blake3 hashing | Performance, reliability |
| Tokio async | Concurrency, I/O efficiency |
| Sidecar index revision + opt-in receipts | Backward-compatible audit of retrieval |
| Transparent memory benchmark harness (Accepted) | Protocol, pins, and dual scoring before any published number |
| Index exclusion, secret denylist, model fingerprint (Accepted) | Default-deny hidden/secret paths; fail-closed model mix |
| Multimodal indexing (Accepted) | Text-first captions/OCR/ASR; separate table for native CLIP/SigLIP; default-off flags |
| Native block FS vs semantic volume (Accepted) | Stay a layer over the host FS + LanceDB; `mkfs.ragfs` / kernel driver rejected. Volume manifest deferred until after 0.3.0 (own ADR; never #179–#185). See [ADR-012](adr/012-native-filesystem-vs-semantic-volume.md). |

These decisions collectively create a system that is:
- **Private**: All processing local
- **Safe**: Reversible operations with approval workflow
- **Fast**: Efficient async I/O and vector search
- **Extensible**: Plugin-like architecture for formats
- **Universal**: Filesystem interface works with any tool
