# RAGFS MCP Server

MCP (Model Context Protocol) server that exposes RAGFS semantic filesystem capabilities to AI assistants like Claude.

## Installation

`ragfs-mcp` is **not yet published on PyPI**. Do not install a package with
this name from PyPI — the name is unclaimed and could be registered by anyone.

`ragfs` is not on PyPI; install ragfs-python first so pip doesn't look for it there.

```bash
# From a clone of this repository
pip install ./crates/ragfs-python
pip install ./crates/ragfs-mcp
# or editable (ragfs-python first, same command):
pip install -e ./crates/ragfs-python -e ./crates/ragfs-mcp

# Without cloning (ragfs-python first)
pip install 'git+https://github.com/gianlucamazza/ragfs#subdirectory=crates/ragfs-python'
pip install 'git+https://github.com/gianlucamazza/ragfs#subdirectory=crates/ragfs-mcp'
```

## Usage

```bash
# Run the server
ragfs-mcp

# Or as a Python module
python -m ragfs_mcp
```

## Claude Desktop Configuration

Add to your Claude Desktop config. Set `RAGFS_SOURCE_PATH` to the same directory you indexed with `ragfs index` — MCP hashes that canonical path (blake3, first 16 hex chars) and opens `~/.local/share/ragfs/indices/{16hex}/index.lance`, matching the CLI.

Mutating tools are off unless `RAGFS_MCP_ALLOW_WRITES=1`. Jail roots are `RAGFS_SOURCE_PATH` plus optional `RAGFS_ALLOWED_ROOTS` (`os.pathsep`-separated), resolved with `realpath`. Hex index ids use that index's recorded source; they do not fall back to `RAGFS_SOURCE_PATH` or cwd.

```json
{
  "mcpServers": {
    "ragfs": {
      "command": "ragfs-mcp",
      "env": {
        "RAGFS_SOURCE_PATH": "/path/to/project",
        "RAGFS_MCP_ALLOW_WRITES": "1"
      }
    }
  }
}
```

## Documentation

See [MCP.md](../../docs/MCP.md) for full documentation.

## License

MIT OR Apache-2.0
