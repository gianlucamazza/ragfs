//! Extractor registry for managing content extractors.

use ragfs_core::{ContentExtractor, ExtractError, ExtractedContent};
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;

/// Registry of content extractors.
pub struct ExtractorRegistry {
    /// Named extractors
    extractors: HashMap<String, Arc<dyn ContentExtractor>>,
    /// MIME type to extractor name mapping
    mime_mapping: HashMap<String, String>,
    captioner: Option<Arc<dyn crate::ImageCaptioner>>,
}

impl ExtractorRegistry {
    /// Create a new empty registry.
    #[must_use]
    pub fn new() -> Self {
        Self {
            extractors: HashMap::new(),
            mime_mapping: HashMap::new(),
            captioner: None,
        }
    }

    /// Caption images from all extractors, including embedded PDF images.
    pub fn set_captioner(&mut self, captioner: Arc<dyn crate::ImageCaptioner>) {
        self.captioner = Some(captioner);
    }

    /// Register an extractor.
    pub fn register<E: ContentExtractor + 'static>(&mut self, name: &str, extractor: E) {
        let extractor = Arc::new(extractor);
        for mime in extractor.supported_types() {
            self.mime_mapping
                .insert((*mime).to_string(), name.to_string());
        }
        self.extractors.insert(name.to_string(), extractor);
    }

    /// Get an extractor for a MIME type.
    #[must_use]
    pub fn get_for_mime(&self, mime_type: &str) -> Option<Arc<dyn ContentExtractor>> {
        self.mime_mapping
            .get(mime_type)
            .and_then(|name| self.extractors.get(name))
            .cloned()
    }

    /// Get an extractor that can handle a file.
    #[must_use]
    pub fn get_for_file(&self, path: &Path, mime_type: &str) -> Option<Arc<dyn ContentExtractor>> {
        // First try by MIME type
        if let Some(extractor) = self.get_for_mime(mime_type) {
            return Some(extractor);
        }

        // Then try by extension
        for extractor in self.extractors.values() {
            if extractor.can_extract(path, mime_type) {
                return Some(extractor.clone());
            }
        }

        None
    }

    /// Extract content from a file.
    pub async fn extract(
        &self,
        path: &Path,
        mime_type: &str,
    ) -> Result<ExtractedContent, ExtractError> {
        let extractor = self
            .get_for_file(path, mime_type)
            .ok_or_else(|| ExtractError::UnsupportedType(mime_type.to_string()))?;

        let mut content = extractor.extract(path).await?;
        if let Some(captioner) = &self.captioner {
            for image in &mut content.images {
                if image.caption.is_some() {
                    continue;
                }
                if let Err(error) = crate::image::checked_dimensions(&image.data) {
                    tracing::warn!("Skipping caption for {:?}: {error}", path);
                    continue;
                }
                match captioner.caption(&image.data).await {
                    Ok(caption) => image.caption = caption,
                    Err(error) => tracing::warn!("Caption failed for {:?}: {error}", path),
                }
            }
        }
        Ok(content)
    }
}

impl Default for ExtractorRegistry {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::TextExtractor;
    use tempfile::tempdir;

    #[test]
    fn test_new_registry_is_empty() {
        let registry = ExtractorRegistry::new();
        assert!(registry.extractors.is_empty());
        assert!(registry.mime_mapping.is_empty());
    }

    #[test]
    fn test_register_extractor() {
        let mut registry = ExtractorRegistry::new();
        registry.register("text", TextExtractor::new());

        assert!(registry.extractors.contains_key("text"));
        // TextExtractor supports text/plain and text/markdown
        assert!(registry.mime_mapping.contains_key("text/plain"));
    }

    #[test]
    fn test_get_for_mime_existing() {
        let mut registry = ExtractorRegistry::new();
        registry.register("text", TextExtractor::new());

        let extractor = registry.get_for_mime("text/plain");
        assert!(extractor.is_some());
    }

    #[test]
    fn test_get_for_mime_nonexistent() {
        let registry = ExtractorRegistry::new();
        let extractor = registry.get_for_mime("video/mp4");
        assert!(extractor.is_none());
    }

    #[test]
    fn test_get_for_file_by_mime() {
        let mut registry = ExtractorRegistry::new();
        registry.register("text", TextExtractor::new());

        let path = std::path::PathBuf::from("/test/file.txt");
        let extractor = registry.get_for_file(&path, "text/plain");
        assert!(extractor.is_some());
    }

    #[test]
    fn test_get_for_file_unknown_type() {
        let registry = ExtractorRegistry::new();
        let path = std::path::PathBuf::from("/test/file.xyz");
        let extractor = registry.get_for_file(&path, "application/unknown");
        assert!(extractor.is_none());
    }

    #[tokio::test]
    async fn test_extract_success() {
        let temp_dir = tempdir().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        std::fs::write(&file_path, "Hello, world!").unwrap();

        let mut registry = ExtractorRegistry::new();
        registry.register("text", TextExtractor::new());

        let result = registry.extract(&file_path, "text/plain").await;
        assert!(result.is_ok());

        let content = result.unwrap();
        assert_eq!(content.text, "Hello, world!");
    }

    #[tokio::test]
    async fn test_extract_unsupported_type() {
        let temp_dir = tempdir().unwrap();
        let file_path = temp_dir.path().join("test.bin");
        std::fs::write(&file_path, [0u8; 10]).unwrap();

        let registry = ExtractorRegistry::new();

        let result = registry
            .extract(&file_path, "application/octet-stream")
            .await;
        assert!(result.is_err());

        match result.unwrap_err() {
            ExtractError::UnsupportedType(mime) => {
                assert_eq!(mime, "application/octet-stream");
            }
            _ => panic!("Expected UnsupportedType error"),
        }
    }

    #[test]
    fn test_multiple_extractors() {
        let mut registry = ExtractorRegistry::new();
        registry.register("text", TextExtractor::new());
        // Could register more extractors here

        assert_eq!(registry.extractors.len(), 1);
        // TextExtractor registers multiple MIME types
        assert!(!registry.mime_mapping.is_empty());
    }

    #[test]
    fn test_default_implementation() {
        let registry = ExtractorRegistry::default();
        assert!(registry.extractors.is_empty());
    }
}

#[cfg(test)]
mod caption_tests {
    use super::*;
    use crate::{CaptionError, ImageCaptioner, PdfExtractor};
    use lopdf::{Document, Object, Stream, dictionary};

    struct CaptionStub;
    #[async_trait::async_trait]
    impl ImageCaptioner for CaptionStub {
        async fn init(&self) -> Result<(), CaptionError> {
            Ok(())
        }
        async fn caption(&self, _: &[u8]) -> Result<Option<String>, CaptionError> {
            Ok(Some("A lighthouse".into()))
        }
        async fn is_initialized(&self) -> bool {
            true
        }
        fn model_name(&self) -> &str {
            "fixture"
        }
    }

    #[tokio::test]
    async fn embedded_pdf_jpeg_uses_the_shared_captioner() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("image.pdf");
        let image = image::RgbImage::from_pixel(64, 64, image::Rgb([255, 0, 0]));
        let mut jpeg = std::io::Cursor::new(Vec::new());
        image.write_to(&mut jpeg, image::ImageFormat::Jpeg).unwrap();
        let mut doc = Document::with_version("1.5");
        let pages = doc.new_object_id();
        let image_id = doc.add_object(Stream::new(
            dictionary! {
                "Type" => "XObject", "Subtype" => "Image", "Width" => 64, "Height" => 64,
                "ColorSpace" => "DeviceRGB", "BitsPerComponent" => 8, "Filter" => "DCTDecode",
            },
            jpeg.into_inner(),
        ));
        let content = doc.add_object(Stream::new(
            dictionary! {},
            b"q 64 0 0 64 0 0 cm /Im0 Do Q".to_vec(),
        ));
        let page = doc.add_object(dictionary! {
            "Type" => "Page", "Parent" => pages, "MediaBox" => vec![0.into(), 0.into(), 100.into(), 100.into()],
            "Resources" => dictionary! { "XObject" => dictionary! { "Im0" => image_id } }, "Contents" => content,
        });
        doc.objects.insert(
            pages,
            Object::Dictionary(
                dictionary! { "Type" => "Pages", "Kids" => vec![page.into()], "Count" => 1 },
            ),
        );
        let catalog = doc.add_object(dictionary! { "Type" => "Catalog", "Pages" => pages });
        doc.trailer.set("Root", catalog);
        doc.save(&path).unwrap();
        let mut registry = ExtractorRegistry::new();
        registry.register("pdf", PdfExtractor::new());
        registry.set_captioner(Arc::new(CaptionStub));
        let content = registry.extract(&path, "application/pdf").await.unwrap();
        assert_eq!(content.images.len(), 1);
        assert_eq!(content.images[0].caption.as_deref(), Some("A lighthouse"));
        assert_eq!(content.images[0].page, Some(1));
    }
}
