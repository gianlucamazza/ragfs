//! Export the actual indexed chunk boundaries for ADR-009 lexical baselines.
//! Run only against a disposable benchmark index; opening may migrate a legacy store.
#[cfg(feature = "lancedb")]
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    use ragfs_core::VectorStore;
    use ragfs_store::LanceStore;
    let path = std::env::args()
        .nth(1)
        .ok_or_else(|| anyhow::anyhow!("usage: benchmark_snapshot INDEX.LANCE"))?;
    anyhow::ensure!(
        std::path::Path::new(&path).is_dir(),
        "index must already exist"
    );
    let store = LanceStore::new(path.into(), 384).with_embedding_model("thenlper/gte-small");
    store.init().await?;
    let chunks = store.get_all_chunks().await?;
    println!("{}", serde_json::to_string(&chunks)?);
    Ok(())
}

#[cfg(not(feature = "lancedb"))]
fn main() {
    eprintln!("benchmark_snapshot requires lancedb");
    std::process::exit(1);
}
