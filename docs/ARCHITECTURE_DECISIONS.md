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
Proposed

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
- **Results file.** JSON, schema version 1, required keys:

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
  "systems": [],
  "metrics": {
    "exact_match_strict": "TBD (to be measured)",
    "exact_match_lenient": "TBD (to be measured)",
    "token_f1_strict": "TBD (to be measured)",
    "token_f1_lenient": "TBD (to be measured)",
    "recall_at_k_any": "TBD (to be measured)",
    "recall_at_k_all": "TBD (to be measured)",
    "recall_at_k_frac": "TBD (to be measured)",
    "latency_s_per_query": "TBD (to be measured)",
    "cost_usd_per_query": "TBD (to be measured)",
    "judge": null
  }
}
```

`git_sha` is the harness repo commit that produced the file.
`git_dirty` must be `false` for any published artefact. `judge` is
`null` when the judge is off; otherwise it names the pinned model and
prompt hash **and** a sibling `metrics_without_judge` object is
required.

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
| **0** | This PR | ADR only. Status Proposed. No code, no config, no CI. |
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
| Transparent memory benchmark harness (Proposed) | Protocol, pins, and dual scoring before any published number |

These decisions collectively create a system that is:
- **Private**: All processing local
- **Safe**: Reversible operations with approval workflow
- **Fast**: Efficient async I/O and vector search
- **Extensible**: Plugin-like architecture for formats
- **Universal**: Filesystem interface works with any tool
