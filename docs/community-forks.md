# Community forks

Ideas taken from community forks, what was not taken, and what could be
reopened later. Forks are a source of *ideas*, not patches to apply wholesale.
Implementation follows [ADR-010](ARCHITECTURE_DECISIONS.md#adr-010-index-exclusion-secret-handling-and-store-integrity).

## sophie4869/ragfs

Source: <https://github.com/sophie4869/ragfs> (reviewed against
`45d729f4833c053eaf99c0a9417f3c1eebc5c5ad`).

### Taken

- Hidden files **and** hidden directories excluded by default, with the index
  root itself allowed to be hidden (`~/.notes`).
- A separate secret-file denylist (gitleaks / TruffleHog-style names such as
  `*.pem`, `*.key`, `id_rsa` / `id_ed25519`, credentials files, `.env*`).
  Adapted here onto a single `ignore`-crate matcher (`WalkBuilder` +
  `OverrideBuilder`) shared by the CLI, mount/FUSE, MCP (via the CLI-built
  index), and library `IndexerConfig`.

### Not taken

- Custom `globset` matcher and `.ragfsignore` ancestor walk to `/` (ADR-010
  rejects walking above the index root).
- Default embedding model `intfloat/multilingual-e5-small`.
- `ragfs serve` web UI (optional token, `CORS *`, no Host check).
- Auto-reindex on embedding-model change via a marker file.
- Making hybrid search opt-in.

### Reopen later

- `.ragfsignore` (nested under the index root only) — ADR-010 PR 2.
- Degenerate-chunk floor, model-id mismatch on open, optional `mount` Cargo
  feature — later PRs in ADR-010.

## manojtummala/SemPOSIX

Source: <https://github.com/manojtummala/SemPOSIX>.

### Taken

- Scoped search (restrict query results to a directory under the index root).
  Already ported on this repo in [#60](https://github.com/gianlucamazza/ragfs/pull/60).
  This ADR does not re-port that work.

### Not taken

- Broader SemPOSIX filesystem semantics beyond scoped search.

### Reopen later

- Only on owner request and behind their own ADRs.
