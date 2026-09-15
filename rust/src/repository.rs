//! Storage contract with explicit owner scoping and optimistic concurrency.

use serde::{Deserialize, Serialize};

use crate::error::Result;

/// The purpose of an encrypted application record.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordKind {
    /// A fact, preference or piece of project context.
    Memory,
    /// The owner's constrained personality settings.
    Personality,
    /// Legacy consent records retained for stored-data compatibility.
    WisdomConsent,
    /// Sanitized, explicitly contributed guidance in the shared partition.
    SharedWisdom,
}

/// Persisted envelope; free text is inside `ciphertext`, never in index metadata.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StoredRecord {
    /// Stable identifier within the owner's partition.
    pub id: String,
    /// Server-derived immutable tenant/user key, also the Cosmos partition key.
    pub owner_id: String,
    /// Record purpose.
    pub kind: RecordKind,
    /// Application-encrypted payload.
    pub ciphertext: String,
    /// Monotonic compare-and-swap version, beginning at one.
    pub version: u64,
    /// Creation time in Unix seconds.
    pub created_at: u64,
    /// Last modification time in Unix seconds.
    pub updated_at: u64,
    /// Optional expiry, enforced before returning memories.
    pub expires_at: Option<u64>,
    /// Optional searchable embedding. Vectors are sensitive, not anonymous.
    pub embedding: Option<Vec<f32>>,
}

/// An owner-scoped repository; implementations must not silently truncate lists.
pub trait MemoryRepository {
    /// Return every record for this owner, or an explicit bounded-capacity error.
    fn list(&self, owner_id: &str) -> Result<Vec<StoredRecord>>;
    /// Read one record only from the supplied owner's partition.
    fn get(&self, owner_id: &str, id: &str) -> Result<Option<StoredRecord>>;
    /// Create without replacing; `false` means the identifier already exists.
    fn create(&mut self, record: &StoredRecord) -> Result<bool>;
    /// Replace only if the stored version is exactly `expected_version`.
    fn replace(&mut self, record: &StoredRecord, expected_version: u64) -> Result<()>;
    /// Delete only an owned record at the expected version.
    fn delete(&mut self, owner_id: &str, id: &str, expected_version: u64) -> Result<()>;
}
