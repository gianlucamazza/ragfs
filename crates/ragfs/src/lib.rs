//! Library surface for the RAGFS CLI.
//!
//! The binary (`main.rs`) uses these types to load `config.toml` and apply it
//! to the indexer, query executor, and embedder.

pub mod config;

pub use config::{Config, ConfigError, SUPPORTED_EMBEDDING_MODEL, resolve_supported_model};

#[cfg(test)]
mod docs_drift {
    /// Fail if `CLAUDE.md` / `AGENTS.md` omit a Cargo workspace member.
    /// Do not assert a test-function count; that number drifts every PR.
    #[test]
    fn agent_docs_list_every_workspace_member() {
        let manifest = include_str!("../../../Cargo.toml");
        let claude = include_str!("../../../CLAUDE.md");
        let agents = include_str!("../../../AGENTS.md");
        let members = workspace_members(manifest);
        assert!(
            !members.is_empty(),
            "failed to parse [workspace] members from Cargo.toml"
        );
        for member in members {
            let name = member.rsplit('/').next().expect("crate path");
            let needle = format!("`{name}`");
            assert!(
                claude.contains(&needle),
                "CLAUDE.md does not mention workspace member {name}"
            );
            assert!(
                agents.contains(&needle),
                "AGENTS.md does not mention workspace member {name}"
            );
        }
    }

    fn workspace_members(manifest: &str) -> Vec<&str> {
        let start = manifest.find("members = [").expect("members = [");
        let rest = &manifest[start..];
        let end = rest.find(']').expect("members ]");
        rest[..end]
            .lines()
            .filter_map(|line| {
                let line = line.trim();
                let line = line.strip_prefix('"')?;
                let line = line.trim_end_matches(',');
                let line = line.strip_suffix('"')?;
                Some(line)
            })
            .collect()
    }

    /// Workspace crates talk TOML/JSON. YAML in the lockfile is only the
    /// `lancedb → lindera → serde_yaml_ng → unsafe-libyaml` chain (issue #160).
    #[test]
    fn workspace_manifests_do_not_depend_on_yaml_parsers() {
        const MANIFESTS: &[(&str, &str)] = &[
            ("Cargo.toml", include_str!("../../../Cargo.toml")),
            (
                "crates/ragfs/Cargo.toml",
                include_str!("../../../crates/ragfs/Cargo.toml"),
            ),
            (
                "crates/ragfs-core/Cargo.toml",
                include_str!("../../../crates/ragfs-core/Cargo.toml"),
            ),
            (
                "crates/ragfs-fuse/Cargo.toml",
                include_str!("../../../crates/ragfs-fuse/Cargo.toml"),
            ),
            (
                "crates/ragfs-index/Cargo.toml",
                include_str!("../../../crates/ragfs-index/Cargo.toml"),
            ),
            (
                "crates/ragfs-chunker/Cargo.toml",
                include_str!("../../../crates/ragfs-chunker/Cargo.toml"),
            ),
            (
                "crates/ragfs-embed/Cargo.toml",
                include_str!("../../../crates/ragfs-embed/Cargo.toml"),
            ),
            (
                "crates/ragfs-extract/Cargo.toml",
                include_str!("../../../crates/ragfs-extract/Cargo.toml"),
            ),
            (
                "crates/ragfs-store/Cargo.toml",
                include_str!("../../../crates/ragfs-store/Cargo.toml"),
            ),
            (
                "crates/ragfs-query/Cargo.toml",
                include_str!("../../../crates/ragfs-query/Cargo.toml"),
            ),
            (
                "crates/ragfs-python/Cargo.toml",
                include_str!("../../../crates/ragfs-python/Cargo.toml"),
            ),
        ];
        let banned = [
            "serde_yaml",
            "serde_yaml_ng",
            "serde_yml",
            "unsafe-libyaml",
            "serde-saphyr",
            "noyalib",
        ];
        for (path, manifest) in MANIFESTS {
            let deps = dependency_block(manifest);
            for crate_name in banned {
                assert!(
                    !deps.contains(crate_name),
                    "{path} must not depend on {crate_name} (issue #160)"
                );
            }
        }
    }

    fn dependency_block(manifest: &str) -> String {
        manifest
            .split("\n[")
            .filter(|section| {
                let header = section.split(']').next().unwrap_or("");
                header.contains("dependencies")
            })
            .collect::<Vec<_>>()
            .join("\n")
    }

    /// `candle-core` 0.11.0 still requires zip ^8.6; keep the local patch
    /// (issue #155) while ignoring RUSTSEC-2024-0449.
    #[test]
    fn candle_core_vendor_patch_is_present() {
        let manifest = include_str!("../../../Cargo.toml");
        assert!(
            manifest.contains("vendor/candle-core"),
            "do not drop the vendored candle-core patch (issue #155)"
        );
    }

    /// RUSTSEC-2024-0449 is transitive-only. The ignore must stay scoped to
    /// `serde_yaml_ng` and point at issue #160. `serde_yml` is RUSTSEC-2025-0068.
    #[test]
    fn rustsec_2024_0449_ignore_is_scoped_and_justified() {
        let deny = include_str!("../../../deny.toml");
        let security = include_str!("../../../.github/workflows/security.yml");
        let pre_release = include_str!("../../../.github/workflows/pre-release.yml");
        let audit_md = include_str!("../../../docs/AUDIT.md");
        let advisory_id = "RUSTSEC-2024-0449";

        let ignore = advisory_ignore_entries(deny);
        assert_eq!(
            ignore.len(),
            1,
            "deny.toml must ignore only {advisory_id}: {ignore:?}"
        );
        let entry = &ignore[0];
        assert!(
            entry.contains(advisory_id),
            "ignore entry must be {advisory_id}: {entry}"
        );
        assert!(
            entry.contains("#160"),
            "ignore reason must link issue #160: {entry}"
        );
        assert!(
            entry.contains("serde_yaml_ng"),
            "ignore must be scoped to serde_yaml_ng: {entry}"
        );
        assert!(
            entry.contains("RUSTSEC-2025-0068"),
            "ignore reason must record why serde_yml is not the replacement: {entry}"
        );

        assert!(
            security.contains(advisory_id),
            "security.yml must ignore {advisory_id} for rustsec/audit-check"
        );
        assert!(
            pre_release.contains(advisory_id),
            "pre-release.yml must ignore {advisory_id} for rustsec/audit-check"
        );
        assert!(
            audit_md.contains(advisory_id) && audit_md.contains("#160"),
            "docs/AUDIT.md §1.2 must name {advisory_id} and issue #160"
        );
    }

    fn advisory_ignore_entries(deny: &str) -> Vec<String> {
        let adv = deny.find("[advisories]").expect("deny.toml [advisories]");
        let rest = &deny[adv..];
        let section_end = rest[1..].find("\n[").map_or(rest.len(), |i| i + 1);
        let section = &rest[..section_end];
        let start = section
            .find("ignore =")
            .expect("deny.toml [advisories] ignore");
        let after_eq = section[start + "ignore =".len()..].trim_start();
        let inner = after_eq
            .strip_prefix('[')
            .expect("deny.toml ignore must be an array")
            .trim_start();
        if inner.starts_with(']') {
            return Vec::new();
        }
        let end = inner.find("\n]").expect("deny.toml ignore closing ]");
        inner[..end]
            .lines()
            .map(str::trim)
            .filter(|line| !line.is_empty() && !line.starts_with('#'))
            .map(ToOwned::to_owned)
            .collect()
    }
}
