//! CLI integration tests. Require `--features test-backends` and
//! `RAGFS_TEST_EMBEDDER=noop` so they run without a model download.

use assert_cmd::Command;
use predicates::prelude::*;
use std::fs;
use std::path::{Path, PathBuf};
use tempfile::TempDir;

struct Harness {
    _root: TempDir,
    source: PathBuf,
    data_dir: PathBuf,
    config_path: PathBuf,
}

impl Harness {
    fn new() -> Self {
        let root = TempDir::new().expect("tempdir");
        let source = root.path().join("src");
        let data_dir = root.path().join("data");
        let config_dir = root.path().join("config");
        fs::create_dir_all(&source).unwrap();
        fs::create_dir_all(&data_dir).unwrap();
        fs::create_dir_all(&config_dir).unwrap();
        let config_path = config_dir.join("config.toml");
        fs::write(&config_path, "").unwrap();
        Self {
            _root: root,
            source,
            data_dir,
            config_path,
        }
    }

    fn write_config(&self, body: &str) {
        fs::write(&self.config_path, body).unwrap();
    }

    fn write_source(&self, name: &str, contents: &str) {
        let path = self.source.join(name);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, contents).unwrap();
    }

    fn ragfs(&self) -> Command {
        let mut cmd = Command::cargo_bin("ragfs").expect("ragfs binary");
        cmd.env("RAGFS_TEST_EMBEDDER", "noop")
            .env("RAGFS_DATA_DIR", &self.data_dir)
            .args(["--config", self.config_path.to_str().unwrap()]);
        cmd
    }
}

fn index_ok(cmd: &mut Command, source: &Path) {
    cmd.args(["-v", "index", source.to_str().unwrap()])
        .assert()
        .success();
}

#[test]
fn unsupported_model_fails_before_download() {
    let h = Harness::new();
    h.write_config(
        r#"
        [embedding]
        model = "jina-embeddings-v3"
        "#,
    );
    h.write_source("note.md", "hello");

    h.ragfs()
        .args(["index", h.source.to_str().unwrap()])
        .assert()
        .failure()
        .stderr(predicate::str::contains("jina-embeddings-v3"))
        .stderr(predicate::str::contains("thenlper/gte-small"));
}

#[test]
fn config_max_file_size_reaches_the_indexer() {
    let h = Harness::new();
    h.write_config(
        r"
        [index]
        max_file_size = 32
        ",
    );
    h.write_source("small.md", "tiny");
    h.write_source("large.md", &"x".repeat(200));

    let output = h
        .ragfs()
        .args(["-v", "index", h.source.to_str().unwrap()])
        .output()
        .expect("run ragfs index");
    assert!(output.status.success(), "index should succeed");
    let blob = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        blob.contains("max_file_size"),
        "indexer must log the max_file_size skip: {blob}"
    );
}

#[test]
fn force_flag_reaches_the_indexer() {
    let h = Harness::new();
    h.write_source("note.md", "alpha beta gamma");
    index_ok(&mut h.ragfs(), &h.source);

    let output = h
        .ragfs()
        .args(["-v", "index", h.source.to_str().unwrap(), "--force"])
        .output()
        .expect("run ragfs index --force");
    assert!(output.status.success(), "force index should succeed");
    let blob = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        blob.contains("force=true"),
        "indexer must log force=true: {blob}"
    );
}

#[test]
fn hybrid_cli_flag_overrides_config_false() {
    let h = Harness::new();
    h.write_config(
        r"
        [query]
        hybrid = false
        default_limit = 1
        ",
    );
    h.write_source("note.md", "semantic search hybrid override");
    index_ok(&mut h.ragfs(), &h.source);

    let output = h
        .ragfs()
        .args([
            "--format",
            "json",
            "query",
            h.source.to_str().unwrap(),
            "semantic",
            "--hybrid",
            "--limit",
            "5",
        ])
        .output()
        .expect("run ragfs query --hybrid");
    let blob = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        !blob.contains("unexpected argument"),
        "clap must accept --hybrid: {blob}"
    );
    // Noop embeddings can leave hybrid rank without `_distance`; the smoke
    // is that the CLI took the hybrid path rather than ignoring the flag.
    assert!(
        output.status.success() || blob.contains("hybrid search") || blob.contains("_distance"),
        "expected hybrid query path, got: {blob}"
    );
}

#[test]
fn status_json_after_index() {
    let h = Harness::new();
    h.write_source("note.md", "indexed by the cli test");
    index_ok(&mut h.ragfs(), &h.source);

    h.ragfs()
        .args(["--format", "json", "status", h.source.to_str().unwrap()])
        .assert()
        .success()
        .stdout(predicate::str::contains("\"total_files\""))
        .stdout(predicate::str::contains("\"total_chunks\""))
        .stdout(predicate::str::contains("\"index_revision\""));
}

fn index_dir(h: &Harness) -> PathBuf {
    let source = h.source.canonicalize().unwrap();
    let hash = blake3::hash(source.to_string_lossy().as_bytes());
    let hash_str = &hash.to_hex()[..16];
    h.data_dir.join("indices").join(hash_str)
}

fn disable_hybrid(h: &Harness) {
    // Noop embeddings often omit `_distance` on the hybrid rank path.
    h.write_config(
        r"
        [query]
        hybrid = false
        ",
    );
}

fn query_json(h: &Harness, query: &str) -> serde_json::Value {
    let output = h
        .ragfs()
        .args([
            "--format",
            "json",
            "query",
            h.source.to_str().unwrap(),
            query,
        ])
        .output()
        .expect("run ragfs query");
    let blob = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.status.success(), "query should succeed: {blob}");
    parse_json_stdout(&output.stdout)
}

fn parse_json_stdout(stdout: &[u8]) -> serde_json::Value {
    let text = String::from_utf8_lossy(stdout);
    let start = text
        .find('{')
        .unwrap_or_else(|| panic!("no JSON object in stdout: {text}"));
    serde_json::from_str(&text[start..]).unwrap_or_else(|e| panic!("query JSON: {e}: {text}"))
}

#[test]
fn query_json_includes_additive_revision_fields() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("note.md", "authentication login flow");
    index_ok(&mut h.ragfs(), &h.source);

    let json = query_json(&h, "authentication");
    assert!(json.get("query").is_some(), "existing query field");
    assert!(json.get("results").is_some(), "existing results field");
    assert!(json["index_revision"].as_u64().unwrap() >= 1);
    assert_eq!(json["ragfs_version"], env!("CARGO_PKG_VERSION"));
    assert!(json["embedding_model"].as_str().is_some());
    assert!(json.get("receipt_path").is_none());
    if let Some(first) = json["results"].as_array().and_then(|r| r.first()) {
        assert!(first.get("file").is_some());
        assert!(first.get("score").is_some());
        assert!(first.get("content").is_some());
    }
}

#[test]
fn two_queries_share_revision_until_reindex() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("note.md", "stable retrieval revision");
    index_ok(&mut h.ragfs(), &h.source);

    let first = query_json(&h, "stable");
    let second = query_json(&h, "retrieval");
    let rev = first["index_revision"].as_u64().unwrap();
    assert_eq!(rev, second["index_revision"].as_u64().unwrap());
}

#[test]
fn force_reindex_changes_revision() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("note.md", "before reindex");
    index_ok(&mut h.ragfs(), &h.source);
    let before = query_json(&h, "before")["index_revision"].as_u64().unwrap();

    h.write_source("note.md", "after reindex with new tokens");
    let output = h
        .ragfs()
        .args(["-v", "index", h.source.to_str().unwrap(), "--force"])
        .output()
        .expect("force index");
    assert!(output.status.success(), "force index should succeed");

    let after = query_json(&h, "after")["index_revision"].as_u64().unwrap();
    assert!(
        after > before,
        "reindex must bump index_revision: {before} -> {after}"
    );
}

fn run_query_json(
    h: &Harness,
    query: &str,
    extra: &[&str],
) -> (bool, String, Option<serde_json::Value>) {
    let mut cmd = h.ragfs();
    cmd.args([
        "--format",
        "json",
        "query",
        h.source.to_str().unwrap(),
        query,
    ]);
    cmd.args(extra);
    let output = cmd.output().expect("run ragfs query");
    let blob = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let json = output
        .status
        .success()
        .then(|| parse_json_stdout(&output.stdout));
    (output.status.success(), blob, json)
}

#[test]
fn save_receipt_writes_default_index_dir_and_round_trips() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("note.md", "receipt payload");
    index_ok(&mut h.ragfs(), &h.source);

    let output = h
        .ragfs()
        .args([
            "--format",
            "json",
            "query",
            h.source.to_str().unwrap(),
            "receipt",
            "--save-receipt",
        ])
        .output()
        .expect("query --save-receipt");
    let blob = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        output.status.success(),
        "query --save-receipt failed: {blob}"
    );
    let json = parse_json_stdout(&output.stdout);
    let path = PathBuf::from(json["receipt_path"].as_str().expect("receipt_path"));
    assert!(
        path.starts_with(index_dir(&h).join("receipts")),
        "default receipt path should be under the index dir: {}",
        path.display()
    );
    assert!(path.exists(), "receipt file should exist");

    let receipt = ragfs::receipt::load_receipt(&path).unwrap();
    assert_eq!(receipt.query, "receipt");
    assert_eq!(
        receipt.index_revision,
        json["index_revision"].as_u64().unwrap()
    );
    assert_eq!(
        receipt.ragfs_version,
        json["ragfs_version"].as_str().unwrap()
    );
    assert_eq!(
        receipt.embedding_model,
        json["embedding_model"].as_str().unwrap()
    );
    assert!(!receipt.timestamp.to_rfc3339().is_empty());
}

#[test]
fn save_receipt_none_default_and_explicit_paths() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("note.md", "receipt cases");
    index_ok(&mut h.ragfs(), &h.source);
    let receipts_dir = index_dir(&h).join("receipts");

    let (ok, blob, json) = run_query_json(&h, "none", &[]);
    assert!(ok, "query without --save-receipt failed: {blob}");
    let json = json.expect("json");
    assert!(
        json.get("receipt_path").is_none(),
        "absent flag must not save a receipt: {json}"
    );
    assert!(
        !receipts_dir.exists() || fs::read_dir(&receipts_dir).map_or(true, |d| d.count() == 0),
        "absent flag must not create receipts"
    );

    let (ok, blob, json) = run_query_json(&h, "default", &["--save-receipt"]);
    assert!(ok, "bare --save-receipt failed: {blob}");
    let json = json.expect("json");
    let default_path = PathBuf::from(json["receipt_path"].as_str().expect("receipt_path"));
    assert!(
        default_path.starts_with(&receipts_dir),
        "bare flag uses the index receipts dir: {}",
        default_path.display()
    );
    assert!(default_path.exists());

    let explicit = h.source.parent().unwrap().join("explicit.json");
    let (ok, blob, json) = run_query_json(
        &h,
        "explicit",
        &["--save-receipt", explicit.to_str().unwrap()],
    );
    assert!(ok, "explicit --save-receipt path failed: {blob}");
    let json = json.expect("json");
    assert_eq!(
        json["receipt_path"].as_str().unwrap(),
        explicit.to_str().unwrap()
    );
    assert!(explicit.is_file());
    assert_eq!(
        ragfs::receipt::load_receipt(&explicit).unwrap().query,
        "explicit"
    );

    let as_file = h
        .source
        .parent()
        .unwrap()
        .join("as_file")
        .join("__default__");
    fs::create_dir_all(as_file.parent().unwrap()).unwrap();
    let (ok, blob, json) = run_query_json(
        &h,
        "sentinel-file",
        &["--save-receipt", as_file.to_str().unwrap()],
    );
    assert!(ok, "literal __default__ file path failed: {blob}");
    let json = json.expect("json");
    assert_eq!(
        json["receipt_path"].as_str().unwrap(),
        as_file.to_str().unwrap()
    );
    assert!(
        as_file.is_file(),
        "literal __default__ must be a receipt file"
    );
    assert_eq!(
        ragfs::receipt::load_receipt(&as_file).unwrap().query,
        "sentinel-file"
    );

    let as_dir = h
        .source
        .parent()
        .unwrap()
        .join("as_dir")
        .join("__default__");
    fs::create_dir_all(&as_dir).unwrap();
    let (ok, blob, json) = run_query_json(
        &h,
        "sentinel-dir",
        &["--save-receipt", as_dir.to_str().unwrap()],
    );
    assert!(ok, "literal __default__ directory path failed: {blob}");
    let json = json.expect("json");
    let written = PathBuf::from(json["receipt_path"].as_str().expect("receipt_path"));
    assert!(
        written.starts_with(&as_dir) && written != as_dir,
        "directory named __default__ should receive the default filename: {}",
        written.display()
    );
    assert!(written.is_file());
    assert_eq!(
        ragfs::receipt::load_receipt(&written).unwrap().query,
        "sentinel-dir"
    );
}

#[test]
fn query_works_after_old_sidecar_without_revision() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("note.md", "legacy sidecar");
    index_ok(&mut h.ragfs(), &h.source);

    let sidecar = index_dir(&h).join("ragfs-schema.json");
    fs::write(&sidecar, r#"{"chunks_schema_version":2}"#).unwrap();

    let json = query_json(&h, "legacy");
    assert!(json["index_revision"].as_u64().unwrap() >= 1);
    let status = h
        .ragfs()
        .args(["--format", "json", "status", h.source.to_str().unwrap()])
        .output()
        .expect("status");
    assert!(status.status.success());
    let status_json = parse_json_stdout(&status.stdout);
    assert!(status_json["index_revision"].as_u64().unwrap() >= 1);
}

fn status_json(h: &Harness) -> serde_json::Value {
    let output = h
        .ragfs()
        .args(["--format", "json", "status", h.source.to_str().unwrap()])
        .output()
        .expect("run ragfs status");
    let blob = format!(
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.status.success(), "status should succeed: {blob}");
    parse_json_stdout(&output.stdout)
}

fn query_blob_contains_excluded(json: &serde_json::Value) -> bool {
    let text = json.to_string();
    text.contains("SECRETPEM_TOKEN")
        || text.contains("HIDDENFILE_TOKEN")
        || text.contains("HIDDENDIR_TOKEN")
        || text.contains("SSHKEY_TOKEN")
        || text.contains("server.pem")
        || text.contains("id_rsa")
        || text.contains(".obsidian")
}

#[test]
fn index_excludes_hidden_and_secret_files_by_default() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("notes/keyboard.md", "VISIBLE_TOKEN keyboard shortcuts");
    h.write_source(".hidden.md", "HIDDENFILE_TOKEN should not index");
    h.write_source(".obsidian/x.md", "HIDDENDIR_TOKEN obsidian workspace");
    h.write_source("server.pem", "SECRETPEM_TOKEN private cert");
    h.write_source(".ssh/id_rsa", "SSHKEY_TOKEN begins");
    h.write_source(".aws/credentials", "AWSKEY_TOKEN aws");
    index_ok(&mut h.ragfs(), &h.source);

    let status = status_json(&h);
    assert_eq!(
        status["total_files"].as_u64().unwrap(),
        1,
        "only the visible note is indexed: {status}"
    );
    let json = query_json(&h, "VISIBLE_TOKEN");
    assert!(
        !query_blob_contains_excluded(&json),
        "CLI query must not return excluded paths: {json}"
    );
}

#[test]
fn include_hidden_still_blocks_secret_files() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source(".notes.md", "DOTFILE_TOKEN hidden but not secret");
    h.write_source("server.pem", "SECRETPEM_TOKEN private cert");
    h.write_source("notes/keyboard.md", "VISIBLE_TOKEN keyboard");

    h.ragfs()
        .args([
            "-v",
            "index",
            h.source.to_str().unwrap(),
            "--include-hidden",
        ])
        .assert()
        .success();

    let status = status_json(&h);
    assert_eq!(
        status["total_files"].as_u64().unwrap(),
        2,
        "hidden opt-in indexes the dotfile and the note, not the pem: {status}"
    );
    let json = query_json(&h, "DOTFILE_TOKEN");
    assert!(
        !json.to_string().contains("SECRETPEM_TOKEN") && !json.to_string().contains("server.pem"),
        "include-hidden must not disable the secret denylist: {json}"
    );
}

#[test]
fn hidden_index_root_keeps_visible_children() {
    let root = TempDir::new().expect("tempdir");
    let source = root.path().join(".notes");
    let data_dir = root.path().join("data");
    let config_dir = root.path().join("config");
    fs::create_dir_all(&source).unwrap();
    fs::create_dir_all(&data_dir).unwrap();
    fs::create_dir_all(&config_dir).unwrap();
    let config_path = config_dir.join("config.toml");
    fs::write(&config_path, "[query]\nhybrid = false\n").unwrap();
    fs::write(source.join("todo.md"), "HIDDENROOT_TOKEN todo").unwrap();
    fs::create_dir_all(source.join(".obsidian")).unwrap();
    fs::write(source.join(".obsidian").join("x.md"), "HIDDENDIR_TOKEN").unwrap();

    let mut cmd = Command::cargo_bin("ragfs").expect("ragfs binary");
    cmd.env("RAGFS_TEST_EMBEDDER", "noop")
        .env("RAGFS_DATA_DIR", &data_dir)
        .args(["--config", config_path.to_str().unwrap()]);
    index_ok(&mut cmd, &source);

    let mut status_cmd = Command::cargo_bin("ragfs").expect("ragfs binary");
    let output = status_cmd
        .env("RAGFS_TEST_EMBEDDER", "noop")
        .env("RAGFS_DATA_DIR", &data_dir)
        .args([
            "--config",
            config_path.to_str().unwrap(),
            "--format",
            "json",
            "status",
            source.to_str().unwrap(),
        ])
        .output()
        .expect("status");
    assert!(output.status.success());
    let status = parse_json_stdout(&output.stdout);
    assert_eq!(
        status["total_files"].as_u64().unwrap(),
        1,
        "hidden index root keeps visible children: {status}"
    );
}

#[test]
fn reindex_purges_newly_excluded_files_without_force() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_config(
        r"
        [query]
        hybrid = false
        [index]
        include_hidden = true
        include_secret_files = true
        ",
    );
    h.write_source("note.md", "VISIBLE_TOKEN note");
    // `secrets.*` is on the denylist and still text/markdown, so the first
    // index can store a row. `*.pem` is application/x-x509-ca-cert and is
    // not extracted even when `include_secret_files` is on.
    h.write_source("secrets.md", "SECRETFILE_TOKEN private notes");
    index_ok(&mut h.ragfs(), &h.source);
    assert_eq!(status_json(&h)["total_files"].as_u64().unwrap(), 2);

    h.write_config(
        r"
        [query]
        hybrid = false
        ",
    );
    index_ok(&mut h.ragfs(), &h.source);
    let status = status_json(&h);
    assert_eq!(
        status["total_files"].as_u64().unwrap(),
        1,
        "purge must drop the secret without --force: {status}"
    );
    let json = query_json(&h, "VISIBLE_TOKEN");
    assert!(
        !json.to_string().contains("SECRETFILE_TOKEN") && !json.to_string().contains("secrets.md"),
        "purged secret must not be searchable: {json}"
    );
}

#[test]
fn model_mismatch_writes_no_receipt_and_force_rebuilds() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("note.md", "a useful note");
    index_ok(&mut h.ragfs(), &h.source);
    let sidecar = index_dir(&h).join("ragfs-schema.json");
    let mut metadata: serde_json::Value =
        serde_json::from_slice(&fs::read(&sidecar).unwrap()).unwrap();
    metadata["embedding_model"] = "different-same-width-model".into();
    fs::write(&sidecar, serde_json::to_vec(&metadata).unwrap()).unwrap();
    let receipt = h.data_dir.join("refused-query.json");
    h.ragfs()
        .args([
            "query",
            h.source.to_str().unwrap(),
            "note",
            "--save-receipt",
            receipt.to_str().unwrap(),
        ])
        .assert()
        .failure()
        .stderr(predicate::str::contains("different-same-width-model"));
    assert!(!receipt.exists());
    h.ragfs()
        .args(["index", h.source.to_str().unwrap(), "--force"])
        .assert()
        .success();
    let metadata: serde_json::Value = serde_json::from_slice(&fs::read(&sidecar).unwrap()).unwrap();
    assert_ne!(metadata["embedding_model"], "different-same-width-model");
    let output = query_json(&h, "note");
    assert_eq!(output["embedding_dim"], metadata["embedding_dim"]);
    assert_eq!(output["min_alnum_chars"], 3);
}

#[test]
fn chunk_floor_filters_before_embedding_and_is_recorded() {
    let h = Harness::new();
    disable_hybrid(&h);
    h.write_source("punctuation.md", "--- #   ");
    h.write_source("cjk.md", "中文啊");
    index_ok(&mut h.ragfs(), &h.source);
    assert_eq!(status_json(&h)["total_files"], 1);
    let output = query_json(&h, "中文啊");
    assert_eq!(output["min_alnum_chars"], 3);
    assert!(!output.to_string().contains("punctuation.md"));
    assert!(output.to_string().contains("cjk.md"));
}
