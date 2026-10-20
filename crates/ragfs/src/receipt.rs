//! Local query retrieval receipts.
//!
//! Receipts are written only when the user opts in (`ragfs query --save-receipt`).
//! They stay on disk next to the index and are never sent over the network.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Directory name under an index data dir (`…/indices/<hash>/receipts/`).
pub const RECEIPTS_DIR_NAME: &str = "receipts";

/// One hit in query JSON / a receipt. Existing field names stay stable.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ResultItem {
    #[serde(default, flatten)]
    pub media: ragfs_core::MediaInfo,
    pub file: String,
    pub score: f32,
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lines: Option<String>,
}

/// `ragfs query --format json` body. New fields are additive after `results`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct QueryOutput {
    pub query: String,
    pub results: Vec<ResultItem>,
    pub index_revision: u64,
    pub ragfs_version: String,
    pub embedding_model: String,
    #[serde(default)]
    pub embedding_dim: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min_alnum_chars: Option<usize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub receipt_path: Option<String>,
}

/// Persisted retrieval receipt. Local only; not telemetry.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct QueryReceipt {
    pub query: String,
    pub timestamp: DateTime<Utc>,
    pub index_revision: u64,
    pub ragfs_version: String,
    pub embedding_model: String,
    #[serde(default)]
    pub embedding_dim: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min_alnum_chars: Option<usize>,
    pub results: Vec<ResultItem>,
}

impl QueryReceipt {
    /// Snapshot the printed answer plus a timestamp.
    #[must_use]
    pub fn from_output(output: &QueryOutput, timestamp: DateTime<Utc>) -> Self {
        Self {
            query: output.query.clone(),
            timestamp,
            index_revision: output.index_revision,
            ragfs_version: output.ragfs_version.clone(),
            embedding_model: output.embedding_model.clone(),
            embedding_dim: output.embedding_dim,
            min_alnum_chars: output.min_alnum_chars,
            results: output.results.clone(),
        }
    }
}

/// Parent of `index.lance` (`~/.local/share/ragfs/indices/<hash>/`).
#[must_use]
pub fn index_dir_from_db_path(db_path: &Path) -> PathBuf {
    db_path.parent().unwrap_or(db_path).to_path_buf()
}

/// Default receipts directory for an index.
#[must_use]
pub fn default_receipts_dir(index_dir: &Path) -> PathBuf {
    index_dir.join(RECEIPTS_DIR_NAME)
}

/// Collision-resistant filename: UTC timestamp plus a short query hash.
#[must_use]
pub fn receipt_filename(query: &str, timestamp: DateTime<Utc>) -> String {
    let stamp = timestamp.format("%Y%m%dT%H%M%S%.3fZ");
    let digest = blake3::hash(query.as_bytes());
    let short = &digest.to_hex()[..8];
    format!("{stamp}-{short}.json")
}

/// Resolve where a receipt should be written.
///
/// * `requested == None` → `<index-dir>/receipts/<filename>`
/// * existing directory → that directory plus the default filename
/// * otherwise → the path as a file
#[must_use]
pub fn resolve_receipt_path(
    requested: Option<&Path>,
    index_dir: &Path,
    query: &str,
    timestamp: DateTime<Utc>,
) -> PathBuf {
    let name = receipt_filename(query, timestamp);
    match requested {
        None => default_receipts_dir(index_dir).join(name),
        Some(path) if path.is_dir() => path.join(name),
        Some(path) => path.to_path_buf(),
    }
}

/// Write a receipt as pretty JSON, creating parent directories.
pub fn save_receipt(path: &Path, receipt: &QueryReceipt) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let json = serde_json::to_string_pretty(receipt)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))?;
    std::fs::write(path, json)
}

/// Read a receipt written by [`save_receipt`].
pub fn load_receipt(path: &Path) -> std::io::Result<QueryReceipt> {
    let bytes = std::fs::read(path)?;
    serde_json::from_slice(&bytes)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::InvalidData, e))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn sample_output() -> QueryOutput {
        QueryOutput {
            query: "auth login".into(),
            results: vec![ResultItem {
                media: Default::default(),
                file: "src/auth.rs".into(),
                score: 0.91,
                content: "fn login() {}".into(),
                lines: Some("10:20".into()),
            }],
            index_revision: 3,
            ragfs_version: "0.2.1".into(),
            embedding_model: "thenlper/gte-small".into(),
            embedding_dim: 384,
            min_alnum_chars: Some(3),
            receipt_path: None,
        }
    }

    #[test]
    fn receipt_round_trips_on_disk() {
        let dir = tempfile::tempdir().unwrap();
        let ts = Utc.with_ymd_and_hms(2026, 10, 19, 8, 0, 0).unwrap();
        let output = sample_output();
        let receipt = QueryReceipt::from_output(&output, ts);
        let path = resolve_receipt_path(None, dir.path(), &output.query, ts);

        save_receipt(&path, &receipt).unwrap();
        assert!(path.starts_with(dir.path().join(RECEIPTS_DIR_NAME)));
        assert!(path.extension().is_some_and(|e| e == "json"));

        let loaded = load_receipt(&path).unwrap();
        assert_eq!(loaded, receipt);
        assert_eq!(loaded.query, "auth login");
        assert_eq!(loaded.index_revision, 3);
        assert_eq!(loaded.results[0].file, "src/auth.rs");
        assert_eq!(loaded.results[0].lines.as_deref(), Some("10:20"));
        assert!((loaded.results[0].score - 0.91).abs() < f32::EPSILON);
    }

    #[test]
    fn requested_file_path_is_used_as_is() {
        let dir = tempfile::tempdir().unwrap();
        let dest = dir.path().join("custom.json");
        let ts = Utc.with_ymd_and_hms(2026, 10, 19, 8, 0, 0).unwrap();
        let path = resolve_receipt_path(Some(&dest), dir.path(), "q", ts);
        assert_eq!(path, dest);
    }

    #[test]
    fn requested_directory_gets_default_filename() {
        let dir = tempfile::tempdir().unwrap();
        let ts = Utc.with_ymd_and_hms(2026, 10, 19, 8, 0, 0).unwrap();
        let path = resolve_receipt_path(Some(dir.path()), dir.path(), "q", ts);
        assert_eq!(path.parent().unwrap(), dir.path());
        assert!(
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .ends_with(".json")
        );
    }

    #[test]
    fn query_json_keeps_existing_fields() {
        let json = serde_json::to_value(sample_output()).unwrap();
        assert_eq!(json["query"], "auth login");
        assert_eq!(json["results"][0]["file"], "src/auth.rs");
        let score = json["results"][0]["score"].as_f64().unwrap();
        assert!((score - 0.91).abs() < 1e-5);
        assert_eq!(json["results"][0]["content"], "fn login() {}");
        assert_eq!(json["results"][0]["lines"], "10:20");
        assert_eq!(json["index_revision"], 3);
        assert_eq!(json["ragfs_version"], "0.2.1");
        assert_eq!(json["embedding_model"], "thenlper/gte-small");
        assert!(json.get("receipt_path").is_none());
    }
}
