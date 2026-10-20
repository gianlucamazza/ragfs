//! Shared default exclusion lists and matcher (ADR-010).
//!
//! One source of truth for CLI, FUSE/mount, library `IndexerConfig`, and docs.
//! Hidden files *and* hidden directories under the index root are excluded by
//! default. A separate secret-file denylist is always applied unless the user
//! sets `include_secret_files`. Gitignore `!` rules cannot re-include a secret
//! or hidden path.
//!
//! Built-in secret patterns follow gitleaks / TruffleHog-style filename
//! denylists (`*.pem`, `*.key`, `id_rsa` / `id_ed25519`, credentials files,
//! `.netrc`, `.npmrc`, `.pypirc`, `.env*`, kube config). A bare `id_*` is
//! intentionally not used (false positive on `id_mapping.md`).
//!
//! Hidden/secret path exclusion is adapted from [sophie4869/ragfs](https://github.com/sophie4869/ragfs)
//! onto the `ignore` crate (`WalkBuilder` + `OverrideBuilder`) as specified
//! by ADR-010. Nested `.ragfsignore` files are supported under the index root.

use ignore::WalkBuilder;
use ignore::gitignore::Gitignore;
use ignore::overrides::{Override, OverrideBuilder};
use std::path::{Component, Path, PathBuf};
use tracing::warn;

use crate::indexer::path_matches_pattern;

/// Noise / build-artifact globs used as the default `[index].exclude` list.
///
/// Secrets and hidden paths are *not* in this list so replacing `exclude` in
/// config cannot disable the denylist or hidden-path rule.
pub const DEFAULT_NOISE_PATTERNS: &[&str] = &[
    "**/node_modules/**",
    "**/.git/**",
    "**/target/**",
    "**/__pycache__/**",
    "**/*.pyc",
    "**/.venv/**",
    "**/venv/**",
    "**/*.lock",
];

/// Secret-file denylist (ADR-010). Always applied unless `include_secret_files`.
///
/// Public keys (`id_*.pub`) are not listed and stay eligible when hidden
/// opt-in is on. Case-sensitive on Linux; case-insensitive on macOS/Windows
/// (same as the `ignore` crate / git on that host).
pub const DEFAULT_SECRET_PATTERNS: &[&str] = &[
    "**/.env",
    "**/.env.*",
    "**/*.env",
    "**/.netrc",
    "**/.npmrc",
    "**/.pypirc",
    "**/.git-credentials",
    "**/*.key",
    "**/*.pem",
    "**/*.p12",
    "**/*.pfx",
    "**/*.kdbx",
    "**/*.jks",
    "**/*.keystore",
    "**/*.ppk",
    "**/id_rsa",
    "**/id_dsa",
    "**/id_ecdsa",
    "**/id_ed25519",
    "**/secrets.*",
    "**/credentials.*",
    "**/.aws/credentials",
    "**/.kube/config",
];

/// Default `[index].exclude` / `IndexerConfig.exclude_patterns` (noise only).
#[must_use]
pub fn default_exclude_patterns() -> Vec<String> {
    DEFAULT_NOISE_PATTERNS
        .iter()
        .map(|pattern| (*pattern).to_string())
        .collect()
}

/// Options for [`ExclusionMatcher`].
#[derive(Debug, Clone)]
pub struct ExclusionOptions {
    /// Index hidden descendants of the root (`--include-hidden`).
    pub include_hidden: bool,
    /// Index secret-named files (does not affect hidden unless also set).
    pub include_secret_files: bool,
    /// Honour `.gitignore` / `.ignore` under the index root only.
    pub honor_gitignore: bool,
    /// Additional ignore globs (`[index].exclude`).
    pub extra_excludes: Vec<String>,
    /// Include globs; empty means “all non-excluded”.
    pub include_patterns: Vec<String>,
}

impl Default for ExclusionOptions {
    fn default() -> Self {
        Self {
            include_hidden: false,
            include_secret_files: false,
            honor_gitignore: true,
            extra_excludes: default_exclude_patterns(),
            include_patterns: vec!["**/*".to_string()],
        }
    }
}

/// Matcher bound to one index root.
#[derive(Debug, Clone)]
pub struct ExclusionMatcher {
    root: PathBuf,
    options: ExclusionOptions,
    overrides: Override,
}

impl ExclusionMatcher {
    /// Build a matcher for `root`. Invalid override globs are skipped.
    #[must_use]
    pub fn new(root: impl Into<PathBuf>, options: ExclusionOptions) -> Self {
        let root = root.into();
        let overrides = build_overrides(&root, &options);
        Self {
            root,
            options,
            overrides,
        }
    }

    /// Index root this matcher is bound to.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Options used to build this matcher.
    #[must_use]
    pub fn options(&self) -> &ExclusionOptions {
        &self.options
    }

    /// Whether `path` is excluded by hidden / secret / noise / gitignore rules.
    ///
    /// Include globs are not applied here; see [`Self::should_process`].
    #[must_use]
    pub fn is_excluded(&self, path: &Path) -> bool {
        if !self.options.include_hidden && self.is_hidden_under_root(path) {
            return true;
        }
        let Ok(relative) = path.strip_prefix(&self.root) else {
            return true;
        };
        let mut candidate = self.root.clone();
        let components: Vec<_> = relative.components().collect();
        for (index, component) in components.iter().enumerate() {
            candidate.push(component.as_os_str());
            if override_ignores(
                &self.overrides,
                &candidate,
                index + 1 < components.len() || path.is_dir(),
            ) {
                return true;
            }
        }
        self.options.honor_gitignore && gitignore_excludes(&self.root, path)
    }

    /// Whether a file should be indexed (not excluded and matches include globs).
    #[must_use]
    pub fn should_process(&self, path: &Path) -> bool {
        if self.is_excluded(path) {
            return false;
        }
        matches_include(&self.options.include_patterns, path)
    }

    /// Whether a directory should be descended into during a hand-rolled walk.
    #[must_use]
    pub fn should_descend(&self, path: &Path) -> bool {
        if path == self.root {
            return true;
        }
        !self.is_excluded(path)
    }

    /// Walk the index root with the `ignore` crate (`WalkBuilder`).
    ///
    /// Hidden opt-in, secret/noise overrides, and gitignore (no parents, no
    /// global gitignore) are applied here. Include globs are applied after.
    #[must_use]
    pub fn collect_files(&self) -> Vec<PathBuf> {
        self.collect_files_with_status().0
    }

    /// Return eligible files and whether every visited entry was readable.
    /// An incomplete walk must never be used to infer deletions.
    pub fn collect_files_with_status(&self) -> (Vec<PathBuf>, bool) {
        let mut complete = true;
        let mut builder = WalkBuilder::new(&self.root);
        let matcher = self.clone();
        builder
            .standard_filters(false)
            .follow_links(false)
            .filter_entry(move |entry| entry.depth() == 0 || !matcher.is_excluded(entry.path()));

        let files = builder
            .build()
            .filter_map(|entry| match entry {
                Ok(entry) => Some(entry),
                Err(error) => {
                    complete = false;
                    warn!("Cannot read index entry: {error}");
                    None
                }
            })
            .filter(|entry| entry.file_type().is_some_and(|kind| kind.is_file()))
            .map(ignore::DirEntry::into_path)
            .filter(|path| matches_include(&self.options.include_patterns, path))
            .collect();
        (files, complete)
    }

    fn is_hidden_under_root(&self, path: &Path) -> bool {
        is_hidden_under_root(&self.root, path)
    }
}

fn build_overrides(root: &Path, options: &ExclusionOptions) -> Override {
    let mut builder = OverrideBuilder::new(root);
    builder
        .case_insensitive(cfg!(any(target_os = "macos", target_os = "windows")))
        .expect("case policy configured before adding globs");
    if !options.include_secret_files {
        for pattern in DEFAULT_SECRET_PATTERNS {
            add_ignore_override(&mut builder, pattern);
        }
    }
    for pattern in &options.extra_excludes {
        add_ignore_override(&mut builder, pattern);
    }
    match builder.build() {
        Ok(overrides) => overrides,
        Err(error) => {
            warn!("Failed to build exclusion overrides ({error}); using empty set");
            OverrideBuilder::new(root)
                .build()
                .expect("empty OverrideBuilder")
        }
    }
}

/// Add an *ignore* override (`!glob`).
///
/// `OverrideBuilder` polarity is the inverse of gitignore: a bare glob is a
/// whitelist, and a `!` prefix is an ignore. ADR-010 uses ignore overrides so
/// gitignore `!` cannot re-include a secret or noise path.
fn add_ignore_override(builder: &mut OverrideBuilder, pattern: &str) {
    let pattern = pattern.trim();
    if pattern.is_empty() || pattern == "!" {
        return;
    }
    // `[index].exclude` always adds excludes, even if the user wrote `!`.
    let stripped = pattern.strip_prefix('!').unwrap_or(pattern);
    let ignore_glob = format!("!{stripped}");
    if let Err(error) = builder.add(&ignore_glob) {
        warn!("Ignoring invalid exclude pattern {pattern:?}: {error}");
    }
}

fn override_ignores(overrides: &Override, path: &Path, is_dir: bool) -> bool {
    overrides.matched(path, is_dir).is_ignore()
        || overrides
            .matched(path_for_override(path), is_dir)
            .is_ignore()
}

fn path_for_override(path: &Path) -> &Path {
    path.strip_prefix("/").unwrap_or(path)
}

fn is_hidden_under_root(root: &Path, path: &Path) -> bool {
    let relative = match path.strip_prefix(root) {
        Ok(relative) => relative,
        Err(_) => return path.components().any(is_hidden_component),
    };
    relative.components().any(is_hidden_component)
}

fn is_hidden_component(component: Component<'_>) -> bool {
    match component {
        Component::Normal(name) => {
            let name = name.to_string_lossy();
            name.starts_with('.') && name != "." && name != ".."
        }
        _ => false,
    }
}

fn matches_include(include_patterns: &[String], path: &Path) -> bool {
    if include_patterns.is_empty() {
        return true;
    }
    let path_str = path.to_string_lossy();
    include_patterns
        .iter()
        .any(|pattern| path_matches_pattern(&path_str, pattern))
}

/// Honour `.gitignore` / `.ignore` from the index root down to `path`.
///
/// Never reads a file above `root`. A `!` whitelist in those files cannot
/// undo [`ExclusionMatcher::is_excluded`] secret/hidden decisions because
/// those run first.
fn gitignore_excludes(root: &Path, path: &Path) -> bool {
    let Ok(relative) = path.strip_prefix(root) else {
        return true;
    };
    let mut candidate = root.to_path_buf();
    let components: Vec<_> = relative.components().collect();
    // An ignored parent cannot be resurrected by a child negation. Evaluate
    // each ancestor as a directory, even for a deleted watcher path.
    for (index, component) in components.iter().enumerate() {
        candidate.push(component.as_os_str());
        let is_dir = index + 1 < components.len() || path.is_dir();
        let mut dirs = Vec::new();
        let mut parent = candidate.parent();
        while let Some(dir) = parent {
            if !dir.starts_with(root) {
                break;
            }
            dirs.push(dir);
            if dir == root {
                break;
            }
            parent = dir.parent();
        }
        dirs.reverse();
        let mut ignored = false;
        // File kind takes precedence over depth; the nearest file of the
        // same kind wins. All evaluation stays inside the index root.
        for name in [".gitignore", ".ignore", ".ragfsignore"] {
            for dir in &dirs {
                let ignore_path = dir.join(name);
                if !ignore_path.is_file() {
                    continue;
                }
                let (rules, error) = Gitignore::new(&ignore_path);
                if let Some(error) = error {
                    warn!("Failed to parse {}: {error}", ignore_path.display());
                }
                let matched = rules.matched(&candidate, is_dir);
                if matched.is_ignore() {
                    ignored = true;
                } else if matched.is_whitelist() {
                    ignored = false;
                }
            }
        }
        if ignored {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    fn matcher_at(root: &Path) -> ExclusionMatcher {
        ExclusionMatcher::new(root, ExclusionOptions::default())
    }

    fn write(root: &Path, relative: &str, body: &str) {
        let path = root.join(relative);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, body).unwrap();
    }

    #[test]
    fn override_builder_bang_is_an_ignore_not_a_whitelist() {
        // Guard the ignore-crate polarity: bare globs whitelist, `!` ignores.
        let root = tempdir().unwrap();
        let root = root.path();
        write(root, "notes/keyboard.md", "kept");
        write(root, "server.pem", "secret");
        write(root, "node_modules/pkg/index.js", "noise");

        let matcher = matcher_at(root);
        assert!(
            matcher.should_process(&root.join("notes/keyboard.md")),
            "ignore-only overrides must not treat unmatched files as ignored"
        );
        assert!(matcher.is_excluded(&root.join("server.pem")));
        assert!(matcher.is_excluded(&root.join("node_modules/pkg/index.js")));
        let collected = matcher.collect_files();
        assert_eq!(
            collected.len(),
            1,
            "walk must keep the note and drop noise/secrets: {collected:?}"
        );
    }

    #[test]
    fn default_exclude_lists_are_the_shared_noise_patterns() {
        assert_eq!(
            default_exclude_patterns(),
            DEFAULT_NOISE_PATTERNS
                .iter()
                .map(|p| (*p).to_string())
                .collect::<Vec<_>>()
        );
        assert!(
            !DEFAULT_NOISE_PATTERNS.contains(&"**/.*"),
            "hidden paths are a separate rule, not a **/.* glob"
        );
        assert!(
            !DEFAULT_SECRET_PATTERNS.contains(&"**/id_*"),
            "bare id_* is a false positive on id_mapping.md"
        );
    }

    #[test]
    fn hidden_file_and_hidden_dir_are_excluded() {
        let root = tempdir().unwrap();
        let root = root.path();
        write(root, "notes/keyboard.md", "kept");
        write(root, ".hidden.md", "hidden file");
        write(root, ".obsidian/x.md", "hidden dir");
        write(root, ".ssh/id_rsa", "ssh key");
        let matcher = matcher_at(root);

        assert!(matcher.should_process(&root.join("notes/keyboard.md")));
        assert!(matcher.is_excluded(&root.join(".hidden.md")));
        assert!(matcher.is_excluded(&root.join(".obsidian/x.md")));
        assert!(matcher.is_excluded(&root.join(".ssh/id_rsa")));
        assert!(!matcher.should_descend(&root.join(".obsidian")));
        assert!(matcher.should_descend(root));
    }

    #[test]
    fn hidden_index_root_keeps_visible_descendants() {
        let tmp = tempdir().unwrap();
        let root = tmp.path().join(".notes");
        fs::create_dir_all(&root).unwrap();
        write(&root, "todo.md", "visible in hidden root");
        write(&root, "sub/deep.md", "also visible");
        write(&root, ".obsidian/app.json", "hidden inside");
        let matcher = matcher_at(&root);

        assert!(
            matcher.should_process(&root.join("todo.md")),
            "index root may itself be hidden"
        );
        assert!(matcher.should_process(&root.join("sub/deep.md")));
        assert!(matcher.is_excluded(&root.join(".obsidian/app.json")));
    }

    #[test]
    fn secret_denylist_matches_adr_examples() {
        let root = tempdir().unwrap();
        let root = root.path();
        let matcher = matcher_at(root);

        assert!(matcher.is_excluded(&root.join("server.pem")));
        assert!(matcher.is_excluded(&root.join("certs/server.pem")));
        assert!(matcher.is_excluded(&root.join("deploy.key")));
        assert!(matcher.is_excluded(&root.join("passwords.kdbx")));
        assert!(matcher.is_excluded(&root.join(".env")));
        assert!(matcher.is_excluded(&root.join(".env.local")));
        assert!(matcher.is_excluded(&root.join("prod.env")));
        assert!(matcher.is_excluded(&root.join(".netrc")));
        assert!(matcher.is_excluded(&root.join(".npmrc")));
        assert!(matcher.is_excluded(&root.join(".pypirc")));
        assert!(matcher.is_excluded(&root.join(".git-credentials")));
        assert!(matcher.is_excluded(&root.join("id_rsa")));
        assert!(matcher.is_excluded(&root.join("id_ed25519")));
        assert!(matcher.is_excluded(&root.join(".aws/credentials")));
        assert!(matcher.is_excluded(&root.join(".kube/config")));
        assert!(matcher.is_excluded(&root.join("secrets.yaml")));
        assert!(matcher.is_excluded(&root.join("credentials.json")));
        assert!(
            !matcher.is_excluded(&root.join("notes/keyboard.md")),
            "ordinary notes stay eligible"
        );
        assert!(
            !matcher.is_excluded(&root.join("id_mapping.md")),
            "bare id_* must not exclude id_mapping.md"
        );
        assert!(
            !matcher.is_excluded(&root.join("id_rsa.pub")),
            "public keys are not secrets"
        );
    }

    #[test]
    fn include_hidden_does_not_disable_secret_denylist() {
        let root = tempdir().unwrap();
        let root = root.path();
        write(root, ".notes.md", "dotfile");
        write(root, ".ssh/id_rsa", "private");
        write(root, ".ssh/id_rsa.pub", "public");
        write(root, "server.pem", "cert");
        write(root, "notes/keyboard.md", "kept");

        let matcher = ExclusionMatcher::new(
            root,
            ExclusionOptions {
                include_hidden: true,
                ..ExclusionOptions::default()
            },
        );

        assert!(
            matcher.should_process(&root.join(".notes.md")),
            "hidden opt-in indexes a visible-named file in a hidden basename"
        );
        assert!(
            matcher.should_process(&root.join(".ssh/id_rsa.pub")),
            "public key is eligible once hidden dirs are included"
        );
        assert!(
            matcher.is_excluded(&root.join(".ssh/id_rsa")),
            "include-hidden must not disable the secret denylist"
        );
        assert!(matcher.is_excluded(&root.join("server.pem")));
        assert!(matcher.should_process(&root.join("notes/keyboard.md")));
    }

    #[test]
    fn gitignore_under_root_is_honoured_without_parents() {
        let tmp = tempdir().unwrap();
        let root = tmp.path().join("proj");
        fs::create_dir_all(&root).unwrap();
        write(&root, "kept.md", "keep");
        write(&root, "skip.log", "noise");
        write(&root, ".gitignore", "*.log\n");
        // Parent gitignore must not apply (parents off).
        write(tmp.path(), ".gitignore", "*.md\n");

        let matcher = matcher_at(&root);
        assert!(matcher.should_process(&root.join("kept.md")));
        assert!(
            matcher.is_excluded(&root.join("skip.log")),
            "root .gitignore applies"
        );
    }

    #[test]
    fn gitignore_bang_cannot_reinclude_secrets() {
        let root = tempdir().unwrap();
        let root = root.path();
        write(root, ".env", "SECRET=1");
        write(root, "server.pem", "cert");
        write(root, ".gitignore", "!.env\n!*.pem\n");

        let hidden_on = ExclusionMatcher::new(
            root,
            ExclusionOptions {
                include_hidden: true,
                ..ExclusionOptions::default()
            },
        );
        assert!(
            hidden_on.is_excluded(&root.join(".env")),
            "!.env in gitignore must not re-include a secret"
        );
        assert!(hidden_on.is_excluded(&root.join("server.pem")));
    }

    #[test]
    fn honor_gitignore_false_skips_gitignore() {
        let root = tempdir().unwrap();
        let root = root.path();
        write(root, "skip.log", "noise");
        write(root, ".gitignore", "*.log\n");
        let matcher = ExclusionMatcher::new(
            root,
            ExclusionOptions {
                honor_gitignore: false,
                ..ExclusionOptions::default()
            },
        );
        assert!(matcher.should_process(&root.join("skip.log")));
    }

    #[test]
    fn walkbuilder_collect_agrees_with_should_process() {
        let root = tempdir().unwrap();
        let root = root.path();
        write(root, "notes/keyboard.md", "kept");
        write(root, ".obsidian/x.md", "hidden dir");
        write(root, "server.pem", "secret");
        write(root, "node_modules/pkg/index.js", "noise");
        write(root, ".hidden.md", "hidden file");

        let matcher = matcher_at(root);
        let collected = matcher.collect_files();
        assert_eq!(
            collected.len(),
            1,
            "only the visible note is walked: {collected:?}"
        );
        assert!(collected[0].ends_with("keyboard.md"));
        assert!(matcher.should_process(&root.join("notes/keyboard.md")));
    }

    #[test]
    fn include_patterns_filter_after_excludes() {
        let root = tempdir().unwrap();
        let root = root.path();
        write(root, "src/lib.rs", "fn x() {}");
        write(root, "readme.md", "docs");
        let matcher = ExclusionMatcher::new(
            root,
            ExclusionOptions {
                include_patterns: vec!["**/*.rs".to_string()],
                ..ExclusionOptions::default()
            },
        );
        assert!(matcher.should_process(&root.join("src/lib.rs")));
        assert!(!matcher.should_process(&root.join("readme.md")));
        let collected = matcher.collect_files();
        assert_eq!(collected.len(), 1);
        assert!(collected[0].ends_with("lib.rs"));
    }
    #[test]
    fn scan_and_direct_match_agree_for_ignored_ancestors() {
        let tmp = tempdir().unwrap();
        let root = tmp.path();
        write(root, ".gitignore", "private/\n");
        write(root, "private/.gitignore", "!note.md\n");
        write(root, "private/note.md", "private");
        write(root, "public.md", "public");
        let matcher = matcher_at(root);
        assert!(matcher.is_excluded(&root.join("private/note.md")));
        assert_eq!(matcher.collect_files(), vec![root.join("public.md")]);
    }

    #[test]
    fn ignore_kind_precedence_beats_nested_gitignore() {
        let tmp = tempdir().unwrap();
        let root = tmp.path();
        write(root, ".ignore", "*.md\n");
        write(root, "sub/.gitignore", "!note.md\n");
        write(root, "sub/note.md", "private");
        let matcher = matcher_at(root);
        assert!(matcher.is_excluded(&root.join("sub/note.md")));
        assert!(matcher.collect_files().is_empty());
    }

    #[test]
    fn secret_case_policy_is_explicit() {
        let tmp = tempdir().unwrap();
        let matcher = matcher_at(tmp.path());
        assert_eq!(
            matcher.is_excluded(&tmp.path().join("SERVER.PEM")),
            cfg!(any(target_os = "macos", target_os = "windows"))
        );
    }
    #[test]
    fn nested_ragfsignore_is_bounded_and_has_highest_priority() {
        let tmp = tempdir().unwrap();
        let root = tmp.path().join("root");
        fs::create_dir_all(&root).unwrap();
        write(tmp.path(), ".ragfsignore", "*.md\n");
        write(&root, ".ignore", "*.md\n");
        write(&root, ".ragfsignore", "# keep notes\n!*.md\ncache/\n");
        write(&root, "sub/.ragfsignore", "drop.md\n!secrets.md\n");
        write(&root, "sub/keep.md", "keep");
        write(&root, "sub/drop.md", "drop");
        write(&root, "sub/secrets.md", "secret");
        write(&root, "cache/note.md", "cached");
        let matcher = matcher_at(&root);
        assert_eq!(matcher.collect_files(), vec![root.join("sub/keep.md")]);
        for name in ["sub/drop.md", "sub/secrets.md", "cache/note.md"] {
            assert!(matcher.is_excluded(&root.join(name)));
        }
        fs::remove_file(root.join(".ignore")).unwrap();
        fs::remove_file(root.join(".ragfsignore")).unwrap();
        assert!(matcher.should_process(&root.join("sub/keep.md")));
    }
    #[test]
    fn unreadable_walk_entry_emits_warning() {
        use std::io::Write;
        use std::sync::{Arc, Mutex};
        #[derive(Clone)]
        struct Capture(Arc<Mutex<Vec<u8>>>);
        impl Write for Capture {
            fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
                self.0.lock().unwrap().extend_from_slice(bytes);
                Ok(bytes.len())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let bytes = Arc::new(Mutex::new(Vec::new()));
        let capture = Capture(bytes.clone());
        let subscriber = tracing_subscriber::fmt()
            .without_time()
            .with_ansi(false)
            .with_writer(move || capture.clone())
            .finish();
        let temp = tempdir().unwrap();
        // A missing entry is deterministic even when tests run as root.
        let matcher = matcher_at(&temp.path().join("missing"));
        tracing::subscriber::with_default(subscriber, || {
            assert!(matcher.collect_files().is_empty());
        });
        let log = String::from_utf8(bytes.lock().unwrap().clone()).unwrap();
        assert!(log.contains("Cannot read index entry"), "{log}");
    }
    #[test]
    fn directory_override_also_excludes_direct_child_events() {
        let temp = tempdir().unwrap();
        write(temp.path(), "cache/note.md", "cached");
        let matcher = ExclusionMatcher::new(
            temp.path(),
            ExclusionOptions {
                extra_excludes: vec!["cache/".into()],
                ..ExclusionOptions::default()
            },
        );
        assert!(matcher.is_excluded(&temp.path().join("cache/note.md")));
        assert!(matcher.collect_files().is_empty());
    }
}
