# ADR-012: Native Block-Device Filesystem vs Semantic Volume

This record evaluates whether ragfs should become a native block-device
filesystem (`mkfs.ragfs`, an on-disk format with superblock and
checksums, `fsck.ragfs`, `mount -t ragfs`, later a kernel driver) or
remain a semantic layer over a host filesystem plus LanceDB (the
current FUSE architecture). It is **design only**. It does not
implement code, change Cargo or Python packages, update
`docs/ROADMAP.md`, or create issues or milestones.

### Status

Proposed (HOLD) — owner decision required. Do not implement. Do not
schedule against 0.3.0.

Verified against `main` @ `3e16a5c0c4923cfa764642a443c153d33ac2db3d`
(docs: completion plan for accepted ADRs, #178) unless a citation
names another commit or an open PR.

### Context

The idea arrived from a ChatGPT answer that had not read this tree. It
proposed seven phases: loop-device prototype → versioned on-disk
format → atomic persistence / recovery / `fsck` → FUSE mount →
persistent semantic index → physical partitions → kernel driver only
if benchmarks justify; embeddings as derived, rebuildable indexes
separate from canonical data; and the question “traditional FS with
RAG, or a new storage model where documents and semantic relations
are native primitives?”.

That plan describes a product ragfs **already is not**, and one it
does not need to become, in order to answer the useful question
inside it.

Accepted ADRs that bind this evaluation:

- ADR-002 — LanceDB as the vector store.
- ADR-004 — FUSE as the advanced interface; CLI for simple
  operations.
- ADR-008 — `index_revision` on `ragfs-schema.json`;
  `CHUNKS_SCHEMA_VERSION` stays 2; receipts opt-in and local.
- ADR-009 — Accepted (2026-10-19). Benchmark harness; no unpublished
  numbers. Sequenced as #194–#202 in `docs/ROADMAP.md`.
- ADR-010 — Accepted (2026-10-20). Exclusion, secret-file denylist,
  model fingerprint, optional `mount` feature. Target release
  **0.3.0**. Sequenced as #179–#186.
- ADR-011 — Accepted (2026-10-20). Multimodal, **after 0.3.0**.
  Schema v3 is phase 2 (#188).

`docs/ROADMAP.md` is the completion plan for work already accepted
on `main`. This ADR must not delay the ADR-010 security sequence
(#179–#185) or the 0.3.0 release PR (#186).

---

## 1. What exists today

### Architecture (code on `main`)

ragfs is a **userspace semantic layer** over a directory the user
already has. The pipeline is extract → chunk → embed → store
(`docs/ARCHITECTURE.md`). Crates:

| Crate | Role on `main` |
|-------|----------------|
| `crates/ragfs` | CLI: `mount`, `index`, `query`, `status`, `config` (`src/main.rs`) |
| `crates/ragfs-core` | Traits and types; `path_jail` |
| `crates/ragfs-extract` | `ExtractorRegistry` (text, PDF, Office, image) |
| `crates/ragfs-chunker` | `ChunkerRegistry` |
| `crates/ragfs-embed` | Candle `gte-small`, 384-d |
| `crates/ragfs-store` | `LanceStore` (`lancedb = "0.37.1"` in workspace `Cargo.toml`) and `MemoryStore` |
| `crates/ragfs-index` | `IndexerService` + `FileWatcher` (`notify` / `notify-debouncer-full`) |
| `crates/ragfs-query` | Query execution |
| `crates/ragfs-fuse` | FUSE passthrough + virtual `.ragfs/` |
| `crates/ragfs-python` | PyO3 bindings / adapters |
| `crates/ragfs-mcp` | Python MCP server (not a Cargo member) |

Workspace version is `0.2.2`. Default CLI features are `candle` +
`lancedb`. `full` adds `vision`. `crates/ragfs` always depends on
`ragfs-fuse` and `fuser` today (`crates/ragfs/Cargo.toml` lines 23,
47, 64). ADR-010 PR 7 (#185) is the accepted plan to make `mount` a
default-on feature so a CLI-only build does not need FUSE headers.

FUSE mount (`main.rs` 524–555) sets `MountOption::FSName("ragfs")`,
`AutoUnmount`, and `DefaultPermissions`. That is a **FUSE filesystem
name**, not a kernel `mount -t ragfs` type. Passthrough reads and
writes the source directory (`crates/ragfs-fuse/src/filesystem/passthrough.rs`).
Virtual control lives under `.ragfs/` (query, ops, safety, semantic)
as specified in ADR-004 and `crates/ragfs-fuse/src/lib.rs`.

MCP does not walk trees. It opens the Lance index the CLI wrote
(`crates/ragfs-mcp/src/ragfs_mcp/server.py` `get_indices_dir` /
`index.lance`; `docs/MCP.md`). Write tools are opt-in and
allowlist-jailed.

### Canonical data vs derived index

**Canonical documents stay on the host filesystem** (ext4, Btrfs,
XFS, APFS, …). ragfs does not format a block device, does not own
file bytes, and does not replace `stat` / `read` / `write` for
real files except by FUSE passthrough to the same path.

**Derived index** lives beside a hash of the source path:

```
get_db_path(source) =
  $RAGFS_DATA_DIR/indices/{blake3(source)[:16]}/index.lance
```

(`crates/ragfs/src/main.rs` 199–205). Default data dir is
`~/.local/share/ragfs` via `ProjectDirs` (`crates/ragfs/src/config.rs`
`data_dir()`). Next to `index.lance`:

- `ragfs-schema.json` — `SchemaSidecar`:
  `chunks_schema_version`, optional `embedding_dim` /
  `embedding_model`, `index_revision`
  (`crates/ragfs-store/src/schema.rs`).
- `receipts/` — opt-in query receipts (ADR-008).

Lance tables (`chunks`, `files`) hold chunk text, 384-d vectors,
file records with blake3 `content_hash`, and directory-scope
columns (`dir_path`, `dir_depth`, `path_components`). Schema
version is **2**. There is no `modality` / `start_ms` / `end_ms`
(ADR-011 phase 2 / #188).

Soft-deleted files go to `~/.local/share/ragfs/trash/`
(`docs/ARCHITECTURE.md`; `crates/ragfs-fuse/src/safety.rs`), not
into the source tree. History is append-only JSONL.

Embeddings are **already** derived and rebuildable: `ragfs index
--force` skips the content-hash short-circuit
(`IndexerConfig.force`; `process_file` in
`crates/ragfs-index/src/indexer.rs`). Deleting
`~/.local/share/ragfs/indices/<hash>/` and re-running `ragfs index
<source>` rebuilds the store from the host files (`docs/API.md`
schema-migration note). Models cache under
`~/.local/share/ragfs/models/`.

The ChatGPT brief was correct that embeddings must not be the
canonical copy of a document. That is already the architecture.
It was incorrect that ragfs therefore needs a new block format
to make that true.

### Shared exclusion matcher (ADR-010, in flight)

On `main` @ `3e16a5c0` the matcher is still the hand-rolled
`path_matches_pattern` in `crates/ragfs-index/src/indexer.rs`.
Two default lists disagree (ADR-010, verified at `bcb1611`, still
true on this `main`):

- CLI / FUSE / documented config: `config.rs` `default_exclude()`
  (no `**/.*`).
- `IndexerConfig::default()`: includes `**/.*` (basename-only
  hidden files).
- Watcher (`crates/ragfs-index/src/watcher.rs` 106–111) drops
  events whose **basename** starts with `.`, independently of
  either list.

Reindex does not purge newly excluded paths (`process_file` 671–674
returns without `delete_by_file_path`). Oversized files *are*
deleted (676–684). Empty extract skips without delete (711–714).
`scan_directory` uses `entries.flatten()` (silent failed entries).
Sidecar writes `embedding_model` but `init` compares **dimension
only** (`ensure_embedding_dim_matches`,
`crates/ragfs-store/src/lancedb.rs`).

Open PR **#206** (`fix(index)!: exclude hidden paths and secret
files by default`, closes #179) is ADR-010 PR 1. It is **not
merged**. Head at evaluation time:
`010b105a674d70027beddf8cfa580876c04a85d7` on
`cursor/index-default-exclusions-d2fa`. It adds
`crates/ragfs-index/src/exclude.rs` (`WalkBuilder` +
`OverrideBuilder` from the `ignore` crate), shared CLI/library
defaults, watcher integration, and purge of excluded store rows.
PR 2 (#180) is nested `.ragfsignore`. A volume design, if any,
must **consume** that matcher, not invent a third walker.

### Current failure modes (observed in code, not measured)

These are classes of failure, not rates. No reliability or
performance figure is claimed.

| Mode | What the code does |
|------|--------------------|
| Host crash during `process_file` | `delete_by_file_path` then `upsert_chunks`. A crash between those calls leaves that file absent from the index until the next successful index. |
| Sidecar write | `tokio::fs::write` of pretty JSON (`write_schema_sidecar`, `lancedb.rs` 376–394). Not a write-to-temp + rename. A crash can leave a truncated sidecar; `read_schema_sidecar` then returns `None`. |
| Lance commit | Lance commits by atomically publishing a new manifest (see prior art). ragfs does not ship `ragfs compact`; optimize is best-effort on ANN (`ensure_vector_index`). |
| FTS freshness | FTS is created on an empty `chunks` table (`init` 838–852). ANN is refreshed on upsert. Whether hybrid search sees rows inserted after that empty FTS create is **unverified** on `main` (ADR-010; #184 is test-first). |
| Model mix | Two 384-d models can share a table; only width is checked. ADR-010 #181 is the fail-closed fingerprint. |
| Path identity | Index id is blake3 of the source path string. Rename or copy the tree → new empty index. The files did not move in any ragfs format; the key changed. |
| Corpus leak | Chunks store file text. CLI, FUSE `.query` (content truncated to 500 chars), and MCP `ragfs_search` return it. The on-disk index is plaintext (ADR-010). |
| FUSE / platform | ADR-004 trade-off: “Linux only (FUSE)”. `docs/DEVELOPMENT.md`: macFUSE, “macOS support is experimental”. Windows is documented for MCP config paths, not for mount. |
| No volume check | There is no `ragfs fsck` / `volume check` that compares source files, `files` table hashes, chunk rows, and sidecar fingerprint. |

Lance’s own crash story is better than a green-field ragfs
superblock would be on day one. ragfs does not currently expose
that (no compact CLI, no check CLI, sidecar not atomic).

---

## 2. Real cost and risk of a native on-disk format

A native ragfs would mean: ragfs **owns** file bytes and metadata
on a block device or image; `mkfs.ragfs` writes a superblock;
`fsck.ragfs` walks allocation and checksums; `mount -t ragfs`
(kernel) or a FUSE driver that speaks that format, not passthrough
to ext4/Btrfs.

### Durability and crash consistency

A new block filesystem must define: allocation, directories,
crash consistency (journaling, soft updates, or CoW), checksums,
and what “fsck replay” means. That is the product. Semantic
search is then a guest.

Kernel documentation for adding a filesystem states that a `mkfs`
is expected, `fsck` is strongly recommended, and
[xfstests](https://docs.kernel.org/filesystems/adding-new-filesystems.html)
is the standard test harness. It also asks authors to justify why
**FUSE is not enough**. ragfs already chose FUSE (ADR-004).

Lessons that are dated and sourced, not invented durations of
“how long ragfs would take”:

- **Btrfs.** Chris Mason announced an early-alpha CoW filesystem
  with checksums on 2007-06-12
  ([LKML](https://lkml.rescloud.iu.edu/0706.1/1732.html);
  ~10,547 lines, format expected to change). It was merged for
  Linux 2.6.29
  ([LWN, 2009-01-10](https://lwn.net/Articles/314429/);
  [Phoronix](https://www.phoronix.com/news/Njk4Mw)). Linux 2.6.29
  released 2009-03-23; kernelnewbies still labelled Btrfs
  **UNSTABLE** and “for testing, benchmarking and developing”
  ([Linux_2_6_29](https://kernelnewbies.org/Linux_2_6_29)).
  Production confidence arrived years after merge. That is the
  cost of *checksums + CoW + fsck*, not of embeddings.
- **bcachefs.** LWN (2018) records that it grew out of bcache
  (merged in Linux 3.10, mid-2013) and that Overstreet came to
  LSFMM to discuss *getting the code upstream* after “a number of
  years” of development
  ([LWN](https://lwn.net/Articles/755276/)). Kent Overstreet
  later wrote that most “next generation” filesystem efforts
  fail, and that doing one right needs a team funded for many
  years
  ([LSF/MM topic mail, 2025-01](https://lkml.indiana.edu/hypermail/linux/kernel/2501.2/02741.html)).
  The journal design aims at prefix-consistent crash recovery
  ([bcachefs Principles of Operation](https://bcachefs.org/bcachefs-principles-of-operation.pdf)).
  That is the class of work a `mkfs.ragfs` superblock would
  enter. It is not a weekend format bump.

No latency, corruption-rate, or “N engineer-years” figure is
stated here. The sourced fact is the **kind** of project: crash
consistency, `fsck`, xfstests, fuzzing of corrupted images, and
years of format stability — independent of RAG.

### Testing burden

A native FS that people `mount` for their documents must survive:
power loss mid-write, torn writes, bitrot, `xfstests` generic
and rw groups, crash-injection, and fuzzed images that must not
panic the kernel (in-kernel) or the FUSE daemon. Kernel docs:
handle corrupted input “without corrupting memory, hanging, or
crashing the kernel.” ragfs today can lose or stale an **index**;
the user’s markdown still sits on ext4/Btrfs. Inverting that
(ragfs owns the bytes; ext4 is gone) raises the failure domain
from “re-run `ragfs index`” to “data loss.”

### Maintenance and portability

- **Linux kernel driver.** In-tree filesystems are GPL-2.0
  ([license-rules](https://docs.kernel.org/process/license-rules.html)).
  ragfs is `MIT OR Apache-2.0` (`Cargo.toml`
  `workspace.package.license`). A kernel module is a new legal
  surface, not a crate feature. Submission goes to
  `linux-fsdevel@`; reviewers expect iomap/folios, a
  `MAINTAINERS` entry, and sustained backing
  ([Adding New Filesystems](https://docs.kernel.org/filesystems/adding-new-filesystems.html)).
  The same page says a niche FS should stay FUSE.
- **macOS / Windows.** Current mount is FUSE (`fuser`). macOS is
  experimental via macFUSE (`docs/DEVELOPMENT.md`). A Linux-only
  `mount -t ragfs` **drops** the platforms MCP already documents
  (`docs/MCP.md` Claude Desktop paths; data dir on macOS/Windows).
  CLI `index` / `query` and MCP do not need FUSE; a block format
  would, unless a second userspace driver is written for each OS.
- **User value vs ext4/Btrfs.** Those filesystems already provide
  journaling or CoW, checksums (Btrfs data+metadata; ext4
  metadata), snapshots (Btrfs), and `fsck`. ragfs users who want
  bitrot protection can put the source tree on Btrfs/ZFS today
  **without** a ragfs format. A native ragfs does not make
  `gte-small` better; it makes document durability ragfs’s job.

### Honest assessment

A native on-disk format does **not** unlock semantic search,
agent ops, or multimodal indexing. Those already sit on host
files + Lance. It would consume the same maintainer attention
ADR-010 reserved for exclusions and ADR-011 reserved for schema
v3. It would make embeddings *harder* to treat as derived
(temptation: store vectors in the same allocation pool as file
data). It would not help 0.3.0 secret-file defaults.

The ChatGPT phase list (loop device → kernel driver) is the
standard “write a teaching filesystem” syllabus. It is not a
gap analysis of this repository.

**Recommendation on this option: reject.** Not “later.” Reject
as a product path unless the owner later writes a new ADR with
a user who cannot keep documents on ext4/Btrfs and a team
prepared to own `fsck` and xfstests. That ADR does not exist.

---

## 3. Middle option: a ragfs volume (directory or image)

### What it is

A **volume** is a **directory** (or a file that is a loop-mounted
ext4/Btrfs image) with a **versioned manifest** next to the
existing Lance index. Documents remain ordinary files on the
host FS. Embeddings remain derived. The volume is a **contract**
for “this tree + this index + these pins,” not a new block
allocator.

Illustrative layout (names fixed at implementation if accepted):

```
<volume>/                 # or ~/.local/share/ragfs/indices/<hash>/
  ragfs-volume.json       # manifest (schema version, pins, roots)
  ragfs-schema.json       # today’s sidecar (or merged into the manifest)
  index.lance/            # Lance dataset (chunks, files, later multimodal_chunks)
  receipts/               # ADR-008, unchanged
```

Optional: `ragfs volume init --image vol.img` creates a **loop
file**, `mkfs.ext4`/`mkfs.btrfs` (host tools), and mounts it;
ragfs still sees a directory. That reuses a mature FS for
crash consistency instead of inventing one. It is **not**
`mkfs.ragfs`.

CLI (illustrative; bikeshed at implementation):

```
ragfs volume init   <dir-or-image>   # write manifest + empty store
ragfs volume check  <dir-or-image>   # sidecar ↔ Lance ↔ source hashes
ragfs volume repair <dir-or-image>   # rebuild derived rows; never rewrite user files
ragfs volume upgrade <dir-or-image>  # manifest + schema bump (e.g. v2 → v3)
```

`check` / `repair` are **gocryptfs/JuiceFS-style** tools: they
audit ragfs metadata, not ext4 allocation bitmaps. See prior
art below.

Manifest fields that earn their keep (additive JSON; old indexes
without a volume file stay valid, like a missing
`index_revision` deserializes as `0`):

- Volume format version (independent of
  `CHUNKS_SCHEMA_VERSION`).
- Canonical source root(s) (so MCP/`source` sidecars and CLI
  hashes agree).
- `chunks_schema_version` and, when ADR-011 lands, reserved
  `embedding_model_image` / `embedding_model_audio`.
- Model fingerprint **as ADR-010 defines it**: v1 is
  `(embedding_model, embedding_dim)` (#181). Do not hash
  weights in a first volume PR.
- Exclusion config snapshot (or a hash of the resolved
  matcher): hidden / secret / `honor_gitignore` / purge flags
  from ADR-010, so `check` can say “index was built with
  different excludes.”
- `index_revision` (already on the sidecar).

`repair` rebuilds embeddings and chunk rows from host files.
It must not “fix” a user’s document.

### Semantic relations as native primitives — at the metadata layer

Gifford’s SFS (1991), HAC (1999), Tagsistant, TagFS, and LiFS
all put **associative access on top of ordinary files**:
virtual directories are queries; tags and links are metadata;
file bytes stay in a Unix tree (or a DB-backed blob). None of
them required a new block allocator to make “document” and
“relation” first-class.

ragfs already exposes relations in userspace:

- `.ragfs/.query/<text>`, `.search`, `.similar` — query as path
  (Gifford virtual directory).
- `.semantic/.organize`, `.dedupe`, `.cleanup`, propose /
  approve / reject (ADR-003).
- Lance `files` / `chunks` rows: file → chunks → embedding;
  blake3 identity (ADR-006).
- MCP tools (`ragfs_search`, `ragfs_similar`,
  `ragfs_propose_organization`, …) over the same store.

What is *not* first-class today: a versioned, checkable
**volume** that names the root, the pins, and the exclusion
generation; stable relations that survive “I copied the tree
to another machine”; a CLI that answers “is this index
coherent with these files?”

Those are **metadata primitives**. They belong in the sidecar /
manifest / Lance tables, not in a superblock. Treating
“documents and semantic relations as native primitives” at the
**block** layer would mean inode types for Chunk and Edge, and
`fsck` walking them. That duplicates Lance fragments and the
host directory. Treating them at the **volume** layer means:
documents = host files; relations = rows and JSON; both
addressable by path and by query. That is HAC’s move
(hierarchy **and** content), which ragfs already approximates.

xattrs (`user.*` on ext4/Btrfs/ZFS;
[xattr(7)](https://man7.org/linux/man-pages/man7/xattr.7.html);
[ext4](https://docs.kernel.org/filesystems/ext4/attributes.html);
[OpenZFS `xattr`](https://openzfs.github.io/openzfs-docs/Basic%20Concepts/Datasets/ACLs.html))
can carry small per-file tags. They are a poor home for
384-d vectors or chunk text (size limits; not queryable as a
corpus; copy/tar/rsync portability varies). A volume may
*optionally* stamp `user.ragfs.index_revision` later; it is
not a substitute for Lance.

### Assessment

| | Volume (this section) | Native FS (section 2) |
|--|----------------------|------------------------|
| Canonical bytes | Host FS | ragfs allocator |
| Crash domain | Index (rebuildable) | Documents |
| Portability | Directory copy + `volume check`; optional loop image | Linux `mount -t` first |
| Fits ADR-008/010/011 | Additive sidecar / schema | New stack |
| User-visible win | `check` / `upgrade`; movable index; honest pins | None that FUSE+Lance lack |

The volume is the **only** option in this ADR that could
deserve a later implementation PR, and only after 0.3.0, and
only if the owner wants the CLI. Status quo already answers
the ChatGPT product question.

---

## 4. Impact on the 0.3.0 / 0.4.0 critical path

**Must not delay ADR-010 PRs #179–#185 or 0.3.0 (#186).**
Those change what is eligible to enter the index and whether
open refuses a mixed embedder. A volume or a native FS that
ships first would index the same secret paths ADR-010 is
closing, or pin a fingerprint ADR-010 has not written.

`docs/ROADMAP.md` critical path: #179 (shared matcher, **in
progress** as #206) → #180–#185 (can overlap after #179) →
#186 (Gianluca, 0.3.0) → ADR-011 code. ADR-009 waits on
0.3.0 / #181 before claiming an honest embedding fingerprint
in results. This ADR adds **zero** boxes to that graph until
the owner takes it off HOLD.

If later accepted, place volume work **after 0.3.0**, as an
unscheduled / post-0.3.0 item the owner adds to the completion
plan. Do not fold it into #179–#186.

**Interaction with ADR-011 schema v3 (#188):**

- Schema v3 adds nullable `modality`, `start_ms`, `end_ms` on
  `chunks` and reserved sidecar keys
  `embedding_model_image` / `embedding_model_audio`
  (`docs/ARCHITECTURE_DECISIONS.md` ADR-011 §6;
  `docs/ROADMAP.md` adr011-p2).
- A volume manifest must treat `chunks_schema_version` as
  **authoritative for Lance columns**, and its own volume
  version as **authoritative for manifest keys**. v3 is an
  additive Lance migration (old v2 opens; nulls backfilled).
- `ragfs volume upgrade` is the user-facing name for “run the
  same `LanceStore::init` migration + rewrite sidecar,” not a
  second migrator. Implement it **after** #188 exists, or in
  the same milestone as #188 if the owner wants a CLI wrapper —
  never before #188, and never as a parallel schema.
- Do not store raw media bytes in the volume (ADR-011: no
  blobs until a dedicated Lance upgrade, #205).
- Exclusion snapshot on the volume must be the ADR-010 matcher
  (#179–#180), including media paths (ADR-011 sequencing
  reason 1).

ADR-009 does not need a volume. If a volume exists later, the
harness adapter records the same sidecar fingerprint #181
already requires.

This ADR does **not** update `docs/ROADMAP.md`. The owner
decides first.

---

## 5. Recommendation and smallest ADR scope

### Proposed decision (HOLD)

1. **Reject** a native block-device filesystem: no
   `mkfs.ragfs` superblock, no ragfs allocator, no
   `mount -t ragfs` kernel type, no kernel driver track.
2. **Keep** the current model: host filesystem is canonical;
   Lance embeddings and chunk text are derived; FUSE is
   passthrough + virtual `.ragfs/` (ADR-004); CLI and MCP
   remain first-class without mount (ADR-010 #185).
3. **Optionally accept later** (separate implementation ADR or
   a status change of *this* record) the **smallest volume
   scope** below — after 0.3.0, and only if Gianluca wants
   `volume check` / movable pins. Until then, **do nothing**.

ChatGPT’s useful residue — “embeddings are derived” and
“should relations be primitives?” — is already true and is
best extended at the **volume/metadata** layer, not the block
layer.

### Smallest scope if the owner later says yes

**In**

- A versioned `ragfs-volume.json` (or an additive extension of
  `ragfs-schema.json`) recording schema version, model
  fingerprint (ADR-010 v1), exclusion generation, source
  root, `index_revision`.
- `ragfs volume init|check|repair|upgrade` as thin CLI over
  `LanceStore::init`, purge, and `--force` rebuild.
- Tests: missing manifest ≡ today’s index; `check` fails on
  dim/model mismatch once #181 exists; `repair` does not
  write user files; `upgrade` is the v2→v3 path after #188.
- Docs: user-facing “what is a volume” (directory, not
  `mkfs`).

**Out (explicit)**

- Block device, partition, superblock, allocation bitmaps,
  journaling, ragfs checksum trees.
- `mkfs.ragfs` / `fsck.ragfs` as VFS tools (name collision
  with `volume check` is intentional: do not ship `mkfs.*`).
- Kernel driver, DKMS, `mount -t ragfs`.
- Loop-device *requirement* (optional host `mkfs.ext4` image
  is extra, default off).
- Storing documents inside Lance or inside the manifest.
- Changing default embedder, Lance pin, or FUSE default.
- Content-level secret scanning (#203), global ignore file
  (#204), `lancedb` 0.40 / Lance 13 (#205).
- Any work in the 0.3.0 window (#179–#186).
- Benchmark numbers (ADR-009).

### Decision points for Gianluca

1. **Reject native FS?** This draft says yes. Confirm or
   reopen with a user who needs ragfs to own blocks.
2. **Volume now, later, or never?** Never = close this ADR as
   Rejected (native) + Accepted (stay on host FS + Lance) and
   leave the sidecar as-is. Later = keep HOLD until 0.3.0 is
   tagged, then a small implementation PR. Now = **not
   offered**; it fights #179–#185.
3. **Manifest vs grow `ragfs-schema.json`?** Growing the
   sidecar is less user-facing API. A new filename is clearer
   for `volume check`. Owner picks; both stay additive JSON.
4. **Optional loop image** as a documented recipe (`dd` +
   `mkfs.ext4` + `ragfs index`) vs a `ragfs volume init
   --image` wrapper. Recipe needs no code.
5. **Whether `volume check` is in scope for 0.4.x** or stays
   unscheduled (same bucket as Metal, `ragfs compact`, HTTP
   `serve` in ADR-010 deferred list).

---

## Comparison

| | Status quo (`main`) | Volume (smallest later scope) | Native block FS |
|--|---------------------|-------------------------------|-----------------|
| Canonical documents | Host directory | Host directory (or loop-backed host FS) | ragfs on-disk format |
| Derived index | `indices/<hash>/index.lance` + sidecar | Same + versioned manifest / check CLI | Coupled to FS metadata |
| Rebuild embeddings | `ragfs index --force` | `volume repair` / existing `--force` | Reindex if vectors are not canonical — if they *are* canonical, worse |
| FUSE | Passthrough + `.ragfs/` | Unchanged | Driver for ragfs format |
| `mount -t` | No (`FSName=ragfs` FUSE) | No | Yes (Linux) |
| `fsck` story | None (Lance + delete index) | Metadata check/repair | Full FS `fsck` + xfstests |
| Crash loses | Index rows / sidecar | Same, plus a check to see it | Documents |
| macOS / Windows | CLI/MCP; mount experimental / absent | Same | Linux `mount -t` first; other OS drivers not proposed |
| Kernel licence | N/A (userspace MIT/Apache-2.0) | N/A | GPL-2.0 in-tree |
| 0.3.0 impact | In progress (#206 / #179) | None if HOLD | Would stall 0.3.0 |
| Schema v3 (#188) | Planned after 0.3.0 | `upgrade` wraps it | Unrelated new format |
| Honest fit | Product as designed (ADR-004/002) | Integrity UX | Teaching-FS / research OS |

---

## Prior art (cited)

### Semantic / tagging filesystems (not block allocators)

- **Semantic File Systems**, Gifford, Jouvelot, Sheldon, O’Toole,
  SOSP ’91. Virtual directories as queries; transducers extract
  attributes; compatibility with tree protocols.
  [ACM](https://dl.acm.org/doi/10.1145/121133.121138),
  [DOI](https://doi.org/10.1145/121132.121138),
  [MIT PDF](https://web.mit.edu/6.826/archive/S97/13-Gifford-Semantic-file-systems-paper.pdf).
- **HAC** (Hierarchy And Content), Gopal and Manber, OSDI ’99.
  Semantic directories are real directories plus a query;
  results are symlinks; files stay in a Unix tree.
  [USENIX](https://www.usenix.org/conference/osdi-99/integrating-content-based-access-mechanisms-hierarchical-file-systems),
  [PDF](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/gopal/gopal.pdf).
- **TagFS**, Bloehdorn and Völkel, WWW 2006 workshop. Tag
  semantics mapped onto hierarchical paths; WebDAV
  implementation, not a new disk format.
  [PDF](https://site.xam.de/2006/01-tagfs.pdf).
- **Tagsistant** — FUSE semantic/tag FS for Linux/BSD;
  directories as tags; plugin transducers.
  [site](https://www.tagsistant.net/),
  [plugins](https://www.tagsistant.net/docs/how_to_write_a_plugin/).
- **LiFS**, Ames et al., MSST 2005–2006. Attributes and
  directed links; FUSE prototype; **PostgreSQL for metadata,
  Linux FS for file bytes**.
  [MSST 2005](https://users.soe.ucsc.edu/~sbrandt/papers/MSST05c.pdf),
  [MSST 2006](https://users.soe.ucsc.edu/~scott/papers/MSST06a.pdf).

Consensus of this line: **do not replace the host FS**. Add a
query/tag layer. ragfs is in this line (vector transducers
instead of keyword transducers).

### xattrs as metadata carriers

- [xattr(7)](https://man7.org/linux/man-pages/man7/xattr.7.html) —
  `user.*` for arbitrary user metadata; access follows file
  mode.
- [ext4 xattrs](https://docs.kernel.org/filesystems/ext4/attributes.html)
  — in-inode or one external block.
- Btrfs: standard Linux `user` / `trusted` / `security` /
  `system` handlers (`fs/btrfs/xattr.c` in the kernel tree).
- [OpenZFS xattr](https://openzfs.github.io/openzfs-docs/Basic%20Concepts/Datasets/ACLs.html)
  — `sa` (32 KiB / 64 KiB SA limits, then directory overflow)
  vs `dir`.

Useful for small tags; not a vector corpus.

### FUSE systems that ship mkfs/fsck *without* a kernel FS

These tools format or check a **volume stored on an existing
FS or object store**. They are the precedent for
`ragfs volume *`, not for `mkfs.ragfs` on a partition.

- **S3QL** — `mkfs.s3ql <storage-url>`, `fsck.s3ql`; exclusive
  ownership of the storage prefix.
  [mkfs](https://www.rath.org/s3ql-docs/mkfs.html),
  [fsck](https://www.rath.org/s3ql-docs/fsck.html).
- **JuiceFS** — `juicefs format META-URL NAME` creates a
  volume (metadata engine + object/local storage);
  `juicefs fsck` checks metadata ↔ objects. Data and metadata
  are separated; POSIX comes from FUSE, not a new kernel FS.
  [intro](https://juicefs.com/docs/community/introduction/),
  [architecture](https://juicefs.com/docs/community/architecture/),
  [commands](https://juicefs.com/docs/community/command_reference/).
- **gocryptfs** — `gocryptfs -init CIPHERDIR`,
  `gocryptfs -fsck CIPHERDIR` (exit 26 on corruption). Encrypted
  tree is a **directory** on the host FS.
  [MANPAGE](https://github.com/rfjakob/gocryptfs/blob/master/Documentation/MANPAGE.md).
- **mergerfs** — no `mkfs`; `fsck.mergerfs` audits
  permission/ownership drift across branches.
  [tooling](https://trapexit.github.io/mergerfs/latest/tooling/).
- **SeaweedFS** — distributed object store + FUSE/S3; not a
  `mkfs` of a POSIX disk format. One `weed` binary, O(1) blob
  reads.
  [README](https://github.com/seaweedfs/seaweedfs).

### Lance / LanceDB on-disk format (what ragfs already uses)

Pin on `main`: `lancedb = "0.37.1"` (workspace `Cargo.toml`;
0.38.0 skipped because `Error::Http` is behind `remote`).
Dedicated 0.40.0 / Lance 13 upgrade is deferred (#205).

Published format (not a ragfs measurement):

- Versioned **manifests**; fragments (row groups) with data
  files and optional deletion files; compaction merges
  fragments and removes deleted rows but does not immediately
  reclaim bytes until old versions are expired.
  [Lance table format](https://lance.org/format/table/),
  [versioning / feature flags](https://lance.org/format/table/versioning/),
  [LanceDB Lance overview](https://docs.lancedb.com/lance).
- Commit protocol: a change is visible only when a new
  manifest is published; a crash during `optimize` does not
  corrupt the prior version (maintainer on
  [lancedb#2423](https://github.com/lancedb/lancedb/issues/2423)).
- ADR-011: Blob V2 needs Lance file format ≥2.2, which is not
  what `lance` 10.0.0 in the current lockfile writes by
  default. Irrelevant to a volume that does not store blobs.

ragfs should keep using this commit story rather than write a
second one.

### Kernel / native FS burden

- [Adding New Filesystems](https://docs.kernel.org/filesystems/adding-new-filesystems.html)
  — prefer improving an existing FS; FUSE for niche; `mkfs` +
  `fsck` + xfstests; GPL-compatible; long-term maintainers;
  corrupted images must not take down the kernel.
- [License rules](https://docs.kernel.org/process/license-rules.html)
  — kernel GPL-2.0-only.
- Btrfs and bcachefs timelines: section 2.

---

## Alternatives considered

| Alternative | Disposition |
|-------------|-------------|
| Native block FS + later kernel driver (ChatGPT 7 phases) | **Reject.** Wrong failure domain; years-class FS work; conflicts with MIT/Apache userspace and 0.3.0. |
| Status quo only (no volume CLI) | **Default while HOLD.** Already matches Gifford/HAC + Lance. Owner may stop here. |
| Smallest volume (manifest + `init/check/repair/upgrade`) | **Optional, after 0.3.0**, if owner wants checkable pins. No block device. |
| Documents and relations as block-level inode types | **Reject.** Duplicates host FS + Lance. Relations belong in tables/JSON. |
| Store canonical files inside Lance | **Reject.** ADR-011 already forbids raw media bytes in v1; text files would lose ordinary editors unless FUSE re-exports them. |
| xattrs-only index | **Reject** as primary store. Size and query limits; keep xattrs optional later. |
| Implement anything in this PR | **Out of scope.** Docs only. |

---

## Non-goals of this PR

- Code, Cargo.toml, pyproject, version, tag.
- Updating `docs/ROADMAP.md` or creating issues/milestones.
- Publishing any benchmark number.
- Changing ADR-010/011 sequences.
- Shipping `mkfs.ragfs`, a kernel module, or a volume CLI.

---

## Unverified / not claimed

- Any runtime, corruption-rate, or “effort” number for a
  hypothetical ragfs FS or volume CLI.
- Whether hybrid FTS on `main` misses post-create rows (open
  #184).
- Whether `tokio::fs::write` of the sidecar has been observed
  to tear in production (the API is non-atomic; no incident
  log is cited).
- Candle/Lance internals beyond the docs linked above.

---

## References (in-tree)

- `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE_DECISIONS.md`
  (ADR-001…011), `docs/ROADMAP.md` (milestones / issues
  #179–#205), `docs/CONFIGURATION.md`, `docs/USER_GUIDE.md`,
  `docs/MCP.md`, `docs/API.md`, `docs/DEVELOPMENT.md`
- `crates/ragfs/src/main.rs`, `crates/ragfs/src/config.rs`,
  `crates/ragfs/src/receipt.rs`
- `crates/ragfs-index/src/indexer.rs`,
  `crates/ragfs-index/src/watcher.rs`;
  open #206 `crates/ragfs-index/src/exclude.rs`
- `crates/ragfs-store/src/schema.rs`,
  `crates/ragfs-store/src/lancedb.rs`
- `crates/ragfs-fuse/src/lib.rs`,
  `crates/ragfs-fuse/src/filesystem/passthrough.rs`,
  `crates/ragfs-fuse/src/safety.rs`,
  `crates/ragfs-fuse/src/semantic.rs`,
  `crates/ragfs-fuse/src/ops.rs`
- `crates/ragfs-mcp/src/ragfs_mcp/server.py`
- Workspace `Cargo.toml` (`lancedb = "0.37.1"`, license,
  rust-version 1.91)
