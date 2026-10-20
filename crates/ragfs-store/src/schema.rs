//! Arrow schema definitions for `LanceDB` tables.

use arrow_schema::{DataType, Field, Schema, TimeUnit};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// Current chunks table schema version.
///
/// Version 1: pre-scope columns (no `dir_path` / `dir_depth` / `path_components`).
/// Version 2: directory-scope columns for `ragfs query --scope`.
pub const CHUNKS_SCHEMA_VERSION: u32 = 2;

/// Sidecar written beside the Lance database (`…/indices/<hash>/ragfs-schema.json`).
pub const SCHEMA_SIDECAR_FILENAME: &str = "ragfs-schema.json";

/// First assigned revision for a new or lazily migrated index.
pub const INITIAL_INDEX_REVISION: u64 = 1;

/// Persisted schema version for an existing Lance index.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SchemaSidecar {
    pub chunks_schema_version: u32,
    /// Embedding width of the `vector` `FixedSizeList`, when known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub embedding_dim: Option<usize>,
    /// Embedder model id that wrote this index, when known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub embedding_model: Option<String>,
    /// Alphanumeric floor used during indexing (absent on legacy indexes).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub min_alnum_chars: Option<usize>,
    /// Monotonic retrieval revision. Missing on pre-receipt indexes (`0`).
    ///
    /// This is sidecar metadata, not a Lance table schema change:
    /// `CHUNKS_SCHEMA_VERSION` stays at 2. Old sidecars deserialize to `0`
    /// and `init` persists [`INITIAL_INDEX_REVISION`] without rewriting tables.
    #[serde(default)]
    pub index_revision: u64,
}

impl Default for SchemaSidecar {
    fn default() -> Self {
        Self {
            chunks_schema_version: CHUNKS_SCHEMA_VERSION,
            embedding_dim: None,
            embedding_model: None,
            min_alnum_chars: None,
            index_revision: 0,
        }
    }
}

/// Treat `0` (missing / uninitialized) as the first persisted revision.
#[must_use]
pub fn effective_index_revision(stored: u64) -> u64 {
    if stored == 0 {
        INITIAL_INDEX_REVISION
    } else {
        stored
    }
}

/// Scope columns missing from a pre-v2 chunks table (nullable so `add_columns` can fill nulls).
#[must_use]
pub fn missing_scope_columns(schema: &Schema) -> Vec<Field> {
    let mut missing = Vec::new();
    if schema.field_with_name("dir_path").is_err() {
        missing.push(Field::new("dir_path", DataType::Utf8, true));
    }
    if schema.field_with_name("dir_depth").is_err() {
        missing.push(Field::new("dir_depth", DataType::UInt16, true));
    }
    if schema.field_with_name("path_components").is_err() {
        missing.push(Field::new("path_components", DataType::Utf8, true));
    }
    missing
}

/// Schema for the chunks table.
#[must_use]
pub fn chunks_schema(embedding_dim: usize) -> Schema {
    Schema::new(vec![
        // Identity
        Field::new("chunk_id", DataType::Utf8, false),
        Field::new("file_id", DataType::Utf8, false),
        Field::new("file_path", DataType::Utf8, false),
        // Content
        Field::new("content", DataType::Utf8, false),
        Field::new("content_type", DataType::Utf8, false),
        // Position
        Field::new("chunk_index", DataType::UInt32, false),
        Field::new("start_byte", DataType::UInt64, false),
        Field::new("end_byte", DataType::UInt64, false),
        Field::new("start_line", DataType::UInt32, true),
        Field::new("end_line", DataType::UInt32, true),
        // Hierarchy
        Field::new("parent_chunk_id", DataType::Utf8, true),
        Field::new("depth", DataType::UInt8, false),
        // Embedding
        Field::new(
            "embedding",
            DataType::FixedSizeList(
                Arc::new(Field::new("item", DataType::Float32, true)),
                embedding_dim as i32,
            ),
            false,
        ),
        // Metadata
        Field::new("embedding_model", DataType::Utf8, true),
        Field::new(
            "indexed_at",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        // File metadata (denormalized)
        Field::new("file_mime_type", DataType::Utf8, true),
        Field::new("file_size_bytes", DataType::UInt64, true),
        // Code-specific
        Field::new("language", DataType::Utf8, true),
        Field::new("symbol_type", DataType::Utf8, true),
        Field::new("symbol_name", DataType::Utf8, true),
        Field::new("dir_path", DataType::Utf8, false),
        Field::new("dir_depth", DataType::UInt16, false),
        Field::new("path_components", DataType::Utf8, false),
    ])
}

/// Schema for the files metadata table.
#[must_use]
pub fn files_schema() -> Schema {
    Schema::new(vec![
        Field::new("file_id", DataType::Utf8, false),
        Field::new("path", DataType::Utf8, false),
        Field::new("size_bytes", DataType::UInt64, false),
        Field::new("mime_type", DataType::Utf8, false),
        Field::new("content_hash", DataType::Utf8, false),
        Field::new(
            "modified_at",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            false,
        ),
        Field::new(
            "indexed_at",
            DataType::Timestamp(TimeUnit::Millisecond, None),
            true,
        ),
        Field::new("chunk_count", DataType::UInt32, false),
        Field::new("status", DataType::Utf8, false),
        Field::new("error_message", DataType::Utf8, true),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_missing_scope_columns_on_v1_schema() {
        let v1 = Schema::new(vec![Field::new("file_path", DataType::Utf8, false)]);
        let missing = missing_scope_columns(&v1);
        assert_eq!(missing.len(), 3);
        assert_eq!(missing[0].name(), "dir_path");
        assert_eq!(missing[1].name(), "dir_depth");
        assert_eq!(missing[2].name(), "path_components");
        assert!(missing.iter().all(Field::is_nullable));
    }

    #[test]
    fn test_missing_scope_columns_on_v2_schema() {
        let v2 = chunks_schema(384);
        assert!(missing_scope_columns(&v2).is_empty());
    }

    #[test]
    fn old_sidecar_deserializes_without_embedding_fields() {
        let s: SchemaSidecar = serde_json::from_str(r#"{"chunks_schema_version":2}"#).unwrap();
        assert_eq!(s.chunks_schema_version, 2);
        assert_eq!(s.embedding_dim, None);
        assert_eq!(s.embedding_model, None);
        assert_eq!(s.index_revision, 0);
        assert_eq!(
            effective_index_revision(s.index_revision),
            INITIAL_INDEX_REVISION
        );
    }

    #[test]
    fn old_sidecar_without_revision_does_not_bump_schema_version() {
        let s: SchemaSidecar = serde_json::from_str(r#"{"chunks_schema_version":2}"#).unwrap();
        assert_eq!(s.chunks_schema_version, CHUNKS_SCHEMA_VERSION);
        assert_eq!(CHUNKS_SCHEMA_VERSION, 2);
    }

    #[test]
    fn sidecar_round_trips_index_revision() {
        let original = SchemaSidecar {
            chunks_schema_version: CHUNKS_SCHEMA_VERSION,
            embedding_dim: Some(384),
            embedding_model: Some("thenlper/gte-small".into()),
            index_revision: 7,
            min_alnum_chars: Some(3),
        };
        let json = serde_json::to_string(&original).unwrap();
        let parsed: SchemaSidecar = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, original);
        assert!(json.contains("\"index_revision\":7"));
    }
}
