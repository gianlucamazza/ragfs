//! No-op embedder for testing without Candle.
//!
//! This module provides a [`NoopEmbedder`] that returns zero-vectors for all embeddings.
//! It's useful for:
//! - Testing without the Candle ML stack
//! - Development builds with faster compilation
//! - Stubbing embeddings in unit tests

use async_trait::async_trait;
use ragfs_core::{EmbedError, Embedder, EmbeddingConfig, EmbeddingOutput, Modality};

/// No-op embedder that returns zero-vectors.
///
/// This embedder is always available, even without the `candle` feature.
/// It returns 384-dimensional zero-vectors for all inputs, making it useful
/// for testing and development.
///
/// # Example
///
/// ```rust
/// use ragfs_embed::NoopEmbedder;
/// use ragfs_core::{Embedder, EmbeddingConfig};
///
/// # async fn example() -> Result<(), Box<dyn std::error::Error>> {
/// let embedder = NoopEmbedder::new();
/// let config = EmbeddingConfig::default();
/// let texts: Vec<&str> = vec!["Hello", "World"];
/// let outputs = embedder.embed_text(&texts, &config).await?;
///
/// assert_eq!(outputs.len(), 2);
/// assert_eq!(outputs[0].embedding.len(), 384);
/// assert!(outputs[0].embedding.iter().all(|&v| v == 0.0));
/// # Ok(())
/// # }
/// ```
pub struct NoopEmbedder {
    dimension: usize,
    unit_vector: bool,
    modalities: Vec<Modality>,
}

impl NoopEmbedder {
    /// Create a new no-op embedder with default dimension (384).
    #[must_use]
    pub fn new() -> Self {
        Self {
            dimension: 384,
            unit_vector: false,
            modalities: vec![Modality::Text],
        }
    }

    /// Constant unit vector for integration tests requiring defined cosine distance.
    /// This is not a semantic embedding model and must never be benchmarked.
    #[must_use]
    pub fn unit_for_tests() -> Self {
        Self {
            unit_vector: true,
            ..Self::new()
        }
    }

    /// Create a new no-op embedder with custom dimension.
    #[must_use]
    pub fn with_dimension(dimension: usize) -> Self {
        Self {
            dimension,
            unit_vector: false,
            modalities: vec![Modality::Text],
        }
    }
}

impl Default for NoopEmbedder {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Embedder for NoopEmbedder {
    fn model_name(&self) -> &str {
        if self.unit_vector {
            "test-unit"
        } else {
            "noop"
        }
    }

    fn dimension(&self) -> usize {
        self.dimension
    }

    fn max_tokens(&self) -> usize {
        512
    }

    fn modalities(&self) -> &[Modality] {
        &self.modalities
    }

    async fn embed_text(
        &self,
        texts: &[&str],
        _config: &EmbeddingConfig,
    ) -> Result<Vec<EmbeddingOutput>, EmbedError> {
        Ok(texts
            .iter()
            .map(|_| EmbeddingOutput {
                embedding: {
                    let mut vector = vec![0.0; self.dimension];
                    if self.unit_vector {
                        vector[0] = 1.0;
                    }
                    vector
                },
                token_count: 0,
            })
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn unit_test_vectors_have_defined_cosine_norm() {
        let embedder = NoopEmbedder::unit_for_tests();
        let output = embedder
            .embed_text(&["caption"], &EmbeddingConfig::default())
            .await
            .unwrap();
        assert_eq!(embedder.model_name(), "test-unit");
        assert_eq!(output[0].embedding.iter().map(|v| v * v).sum::<f32>(), 1.0);
    }

    #[test]
    fn test_noop_new() {
        let embedder = NoopEmbedder::new();
        assert_eq!(embedder.dimension(), 384);
        assert_eq!(embedder.model_name(), "noop");
    }

    #[test]
    fn test_noop_default() {
        let embedder = NoopEmbedder::default();
        assert_eq!(embedder.dimension(), 384);
    }

    #[test]
    fn test_noop_with_dimension() {
        let embedder = NoopEmbedder::with_dimension(768);
        assert_eq!(embedder.dimension(), 768);
    }

    #[test]
    fn test_noop_modalities() {
        let embedder = NoopEmbedder::new();
        let modalities = embedder.modalities();
        assert_eq!(modalities.len(), 1);
        assert!(matches!(modalities[0], Modality::Text));
    }

    #[test]
    fn test_noop_max_tokens() {
        let embedder = NoopEmbedder::new();
        assert_eq!(embedder.max_tokens(), 512);
    }

    #[tokio::test]
    async fn test_noop_embed_text() {
        let embedder = NoopEmbedder::new();
        let texts: Vec<&str> = vec!["Hello", "World"];
        let config = EmbeddingConfig::default();

        let outputs = embedder.embed_text(&texts, &config).await.unwrap();

        assert_eq!(outputs.len(), 2);
        assert_eq!(outputs[0].embedding.len(), 384);
        assert_eq!(outputs[1].embedding.len(), 384);
        assert!(outputs[0].embedding.iter().all(|&v| v == 0.0));
        assert_eq!(outputs[0].token_count, 0);
    }

    #[tokio::test]
    async fn test_noop_embed_empty() {
        let embedder = NoopEmbedder::new();
        let texts: Vec<&str> = vec![];
        let config = EmbeddingConfig::default();

        let outputs = embedder.embed_text(&texts, &config).await.unwrap();

        assert!(outputs.is_empty());
    }

    #[tokio::test]
    async fn test_noop_embed_custom_dimension() {
        let embedder = NoopEmbedder::with_dimension(768);
        let texts: Vec<&str> = vec!["Test"];
        let config = EmbeddingConfig::default();

        let outputs = embedder.embed_text(&texts, &config).await.unwrap();

        assert_eq!(outputs[0].embedding.len(), 768);
    }
}
