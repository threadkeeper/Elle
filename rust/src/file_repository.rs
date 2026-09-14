//! Encrypted-record local store with a single-process lock and atomic snapshots.
//!
//! A stale lock after a crash must be removed by the operator only after checking
//! that no Elle process is using this data directory.

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use crate::error::{Error, Result};
use crate::repository::{MemoryRepository, StoredRecord};

const MAX_STORE_BYTES: u64 = 32 * 1024 * 1024;
const MAX_OWNER_RECORDS: usize = 1000;

/// Local persistence for development; all record payloads must already be encrypted.
pub struct FileRepository {
    path: PathBuf,
    lock_path: PathBuf,
    records: BTreeMap<String, StoredRecord>,
    lock: Option<File>,
}

impl FileRepository {
    /// Open a data directory and hold its exclusive lock for this instance.
    pub fn open(directory: &Path) -> Result<Self> {
        fs::create_dir_all(directory)
            .map_err(|_| Error::Storage("Cannot create the local data directory"))?;
        let lock_path = directory.join("store.lock");
        let lock = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|_| Error::Storage("Local store is locked or inaccessible"))?;
        let mut repository = Self {
            path: directory.join("records.json"),
            lock_path,
            records: BTreeMap::new(),
            lock: Some(lock),
        };
        if repository.path.exists() {
            let file = File::open(&repository.path)
                .map_err(|_| Error::Storage("Cannot open the local store"))?;
            let mut bytes = Vec::new();
            file.take(MAX_STORE_BYTES + 1)
                .read_to_end(&mut bytes)
                .map_err(|_| Error::Storage("Cannot read the local store"))?;
            if bytes.len() as u64 > MAX_STORE_BYTES {
                return Err(Error::Storage("Local store exceeds its size limit"));
            }
            repository.records = serde_json::from_slice(&bytes)
                .map_err(|_| Error::Integrity("Invalid local store format"))?;
            for (key, record) in &repository.records {
                validate_record(record)?;
                if *key != record_key(&record.owner_id, &record.id) {
                    return Err(Error::Integrity(
                        "Local store ownership metadata is invalid",
                    ));
                }
            }
        }
        Ok(repository)
    }

    fn persist(&mut self, next: BTreeMap<String, StoredRecord>) -> Result<()> {
        let bytes = serde_json::to_vec(&next)
            .map_err(|_| Error::Storage("Cannot serialize the local store"))?;
        if bytes.len() as u64 > MAX_STORE_BYTES {
            return Err(Error::Storage("Local store exceeds its size limit"));
        }
        let temporary = self.path.with_extension("pending");
        let result = (|| {
            let mut file = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temporary)
                .map_err(|_| Error::Storage("Pending store snapshot exists or is inaccessible"))?;
            file.write_all(&bytes)
                .and_then(|()| file.sync_all())
                .map_err(|_| Error::Storage("Cannot persist the local store snapshot"))?;
            drop(file);
            fs::rename(&temporary, &self.path)
                .map_err(|_| Error::Storage("Cannot atomically replace the local store"))?;
            Ok(())
        })();
        if result.is_ok() {
            self.records = next;
        }
        result
    }
}

impl Drop for FileRepository {
    fn drop(&mut self) {
        drop(self.lock.take());
        if let Err(error) = fs::remove_file(&self.lock_path) {
            eprintln!(
                "Elle: failed to release local store lock ({:?})",
                error.kind()
            );
        }
    }
}

impl MemoryRepository for FileRepository {
    fn list(&self, owner_id: &str) -> Result<Vec<StoredRecord>> {
        let records: Vec<_> = self
            .records
            .values()
            .filter(|record| record.owner_id == owner_id)
            .cloned()
            .collect();
        if records.len() > MAX_OWNER_RECORDS {
            return Err(Error::Storage("Owner record limit exceeded"));
        }
        Ok(records)
    }

    fn get(&self, owner_id: &str, id: &str) -> Result<Option<StoredRecord>> {
        Ok(self.records.get(&record_key(owner_id, id)).cloned())
    }

    fn create(&mut self, record: &StoredRecord) -> Result<bool> {
        validate_record(record)?;
        let key = record_key(&record.owner_id, &record.id);
        if self.records.contains_key(&key) {
            return Ok(false);
        }
        if self.list(&record.owner_id)?.len() >= MAX_OWNER_RECORDS {
            return Err(Error::Storage("Owner record limit reached"));
        }
        let mut next = self.records.clone();
        next.insert(key, record.clone());
        self.persist(next)?;
        Ok(true)
    }

    fn replace(&mut self, record: &StoredRecord, expected_version: u64) -> Result<()> {
        validate_record(record)?;
        let key = record_key(&record.owner_id, &record.id);
        let current = self.records.get(&key).ok_or(Error::NotFound)?;
        if current.version != expected_version
            || expected_version.checked_add(1) != Some(record.version)
        {
            return Err(Error::Conflict);
        }
        let mut next = self.records.clone();
        next.insert(key, record.clone());
        self.persist(next)
    }

    fn delete(&mut self, owner_id: &str, id: &str, expected_version: u64) -> Result<()> {
        let key = record_key(owner_id, id);
        let current = self.records.get(&key).ok_or(Error::NotFound)?;
        if current.version != expected_version {
            return Err(Error::Conflict);
        }
        let mut next = self.records.clone();
        next.remove(&key);
        self.persist(next)
    }
}

fn record_key(owner_id: &str, id: &str) -> String {
    format!("{owner_id}\0{id}")
}

fn validate_record(record: &StoredRecord) -> Result<()> {
    if record.owner_id.is_empty()
        || record.owner_id.contains('\0')
        || record.id.is_empty()
        || record.id.contains('\0')
        || record.ciphertext.is_empty()
        || record.version == 0
    {
        return Err(Error::Integrity("Invalid stored record metadata"));
    }
    Ok(())
}
