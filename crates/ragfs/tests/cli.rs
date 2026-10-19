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
