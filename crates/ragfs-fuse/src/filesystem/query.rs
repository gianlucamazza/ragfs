//! `.query` / `.search` / `.similar` and the other `.ragfs/` control files
//! (`.index`, `.config`, `.reindex`, `.help`).

use fuser::{
    Errno, FileType, INodeNo, ReplyAttr, ReplyData, ReplyDirectory, ReplyEntry, ReplyWrite,
};
use std::path::PathBuf;
use tracing::{debug, info, warn};

use super::{GENERATION, RagFs, TTL, reply_file_bytes};
use crate::inode::{
    CONFIG_FILE_INO, HELP_FILE_INO, INDEX_FILE_INO, OPS_DIR_INO, QUERY_DIR_INO, REINDEX_FILE_INO,
    SAFETY_DIR_INO, SEARCH_DIR_INO, SEMANTIC_DIR_INO, SIMILAR_DIR_INO,
};

impl RagFs {
    pub(crate) fn lookup_ragfs_dir(&self, name_str: &str, reply: ReplyEntry) {
        match name_str {
            ".query" => {
                let attr = self.make_attr(QUERY_DIR_INO, FileType::Directory, 0);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".search" => {
                let attr = self.make_attr(SEARCH_DIR_INO, FileType::Directory, 0);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".index" => {
                let content = self.get_index_status();
                let attr =
                    self.make_attr(INDEX_FILE_INO, FileType::RegularFile, content.len() as u64);
                let mut cache = self.runtime.block_on(self.content_cache.write());
                cache.insert(INDEX_FILE_INO, content);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".config" => {
                let content = self.get_config();
                let attr =
                    self.make_attr(CONFIG_FILE_INO, FileType::RegularFile, content.len() as u64);
                let mut cache = self.runtime.block_on(self.content_cache.write());
                cache.insert(CONFIG_FILE_INO, content);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".reindex" => {
                let attr = self.make_attr(REINDEX_FILE_INO, FileType::RegularFile, 0);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".similar" => {
                let attr = self.make_attr(SIMILAR_DIR_INO, FileType::Directory, 0);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".help" => {
                let content = self.get_help_content();
                let attr =
                    self.make_attr(HELP_FILE_INO, FileType::RegularFile, content.len() as u64);
                let mut cache = self.runtime.block_on(self.content_cache.write());
                cache.insert(HELP_FILE_INO, content);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".ops" => {
                let attr = self.make_attr(OPS_DIR_INO, FileType::Directory, 0);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".safety" => {
                let attr = self.make_attr(SAFETY_DIR_INO, FileType::Directory, 0);
                reply.entry(&TTL, &attr, GENERATION);
            }
            ".semantic" => {
                let attr = self.make_attr(SEMANTIC_DIR_INO, FileType::Directory, 0);
                reply.entry(&TTL, &attr, GENERATION);
            }
            _ => reply.error(Errno::ENOENT),
        }
    }

    pub(crate) fn lookup_query_dir(&self, name_str: &str, reply: ReplyEntry) {
        let query = name_str.to_string();
        let content = self.execute_query(&query);

        let mut inodes = self.runtime.block_on(self.inodes.write());
        let ino = inodes.get_or_create_query_result(QUERY_DIR_INO, query);
        drop(inodes);

        let attr = self.make_attr(ino, FileType::RegularFile, content.len() as u64);
        let mut cache = self.runtime.block_on(self.content_cache.write());
        cache.insert(ino, content);

        reply.entry(&TTL, &attr, GENERATION);
    }

    pub(crate) fn getattr_query(&self, ino: u64, reply: ReplyAttr) {
        match ino {
            QUERY_DIR_INO | SEARCH_DIR_INO | SIMILAR_DIR_INO => {
                let attr = self.make_attr(ino, FileType::Directory, 0);
                reply.attr(&TTL, &attr);
            }
            INDEX_FILE_INO => {
                let content = self.get_index_status();
                let size = content.len() as u64;
                let mut cache = self.runtime.block_on(self.content_cache.write());
                cache.insert(INDEX_FILE_INO, content);
                let attr = self.make_attr(ino, FileType::RegularFile, size);
                reply.attr(&TTL, &attr);
            }
            CONFIG_FILE_INO => {
                let content = self.get_config();
                let size = content.len() as u64;
                let mut cache = self.runtime.block_on(self.content_cache.write());
                cache.insert(CONFIG_FILE_INO, content);
                let attr = self.make_attr(ino, FileType::RegularFile, size);
                reply.attr(&TTL, &attr);
            }
            REINDEX_FILE_INO => {
                let attr = self.make_attr(ino, FileType::RegularFile, 0);
                reply.attr(&TTL, &attr);
            }
            HELP_FILE_INO => {
                let content = self.get_help_content();
                let size = content.len() as u64;
                let mut cache = self.runtime.block_on(self.content_cache.write());
                cache.insert(HELP_FILE_INO, content);
                let attr = self.make_attr(ino, FileType::RegularFile, size);
                reply.attr(&TTL, &attr);
            }
            _ => reply.error(Errno::ENOENT),
        }
    }

    pub(crate) fn read_query(&self, ino: u64, offset: u64, size: u32, reply: ReplyData) {
        match ino {
            INDEX_FILE_INO => {
                let content = self.get_index_status();
                reply_file_bytes(reply, &content, offset, size);
            }
            CONFIG_FILE_INO => {
                let content = self.get_config();
                reply_file_bytes(reply, &content, offset, size);
            }
            REINDEX_FILE_INO => {
                reply.data(&[]);
            }
            HELP_FILE_INO => {
                let content = self.get_help_content();
                reply_file_bytes(reply, &content, offset, size);
            }
            _ => reply.error(Errno::ENOENT),
        }
    }

    pub(crate) fn readdir_ragfs(&self, offset: u64, mut reply: ReplyDirectory) {
        let entries = [
            (crate::inode::RAGFS_DIR_INO, FileType::Directory, "."),
            (crate::inode::ROOT_INO, FileType::Directory, ".."),
            (QUERY_DIR_INO, FileType::Directory, ".query"),
            (SEARCH_DIR_INO, FileType::Directory, ".search"),
            (INDEX_FILE_INO, FileType::RegularFile, ".index"),
            (CONFIG_FILE_INO, FileType::RegularFile, ".config"),
            (REINDEX_FILE_INO, FileType::RegularFile, ".reindex"),
            (HELP_FILE_INO, FileType::RegularFile, ".help"),
            (SIMILAR_DIR_INO, FileType::Directory, ".similar"),
            (OPS_DIR_INO, FileType::Directory, ".ops"),
            (SAFETY_DIR_INO, FileType::Directory, ".safety"),
            (SEMANTIC_DIR_INO, FileType::Directory, ".semantic"),
        ];

        for (i, (ino, kind, name)) in entries.iter().enumerate().skip(offset as usize) {
            if reply.add(INodeNo(*ino), (i + 1) as u64, *kind, name) {
                break;
            }
        }
        reply.ok();
    }

    pub(crate) fn readdir_query(&self, ino: u64, offset: u64, mut reply: ReplyDirectory) {
        let entries = [
            (ino, FileType::Directory, "."),
            (crate::inode::RAGFS_DIR_INO, FileType::Directory, ".."),
        ];

        for (i, (entry_ino, kind, name)) in entries.iter().enumerate().skip(offset as usize) {
            if reply.add(INodeNo(*entry_ino), (i + 1) as u64, *kind, name) {
                break;
            }
        }
        reply.ok();
    }

    pub(crate) fn write_reindex(&self, data: &[u8], reply: ReplyWrite) {
        let path_str = String::from_utf8_lossy(data).trim().to_string();

        if path_str.is_empty() {
            debug!("Empty reindex request, ignoring");
            reply.written(data.len() as u32);
            return;
        }

        let path = PathBuf::from(&path_str);
        let absolute_path = match self.jail_reindex_path(&path) {
            Ok(p) => p,
            Err(e) => {
                warn!("Rejected reindex path: {e}");
                reply.error(Errno::EINVAL);
                return;
            }
        };

        info!("Reindex requested for: {:?}", absolute_path);

        if let Some(ref sender) = self.reindex_sender {
            let sender = sender.clone();
            let path_to_send = absolute_path.clone();

            self.runtime.spawn(async move {
                if let Err(e) = sender.send(path_to_send).await {
                    warn!("Failed to send reindex request: {}", e);
                }
            });

            debug!("Reindex request sent for: {:?}", absolute_path);
        } else {
            warn!("Reindex requested but no sender configured");
        }

        reply.written(data.len() as u32);
    }
}
