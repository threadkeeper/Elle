//! Validated memory payloads and their user-visible provenance.

use serde::{Deserialize, Serialize};

use crate::error::{Error, Result};

/// Classification used to explain what Elle has remembered.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Category {
    /// A user-provided fact.
    Fact,
    /// A user preference.
    Preference,
    /// Ongoing project context.
    Project,
}

/// Private fields encrypted together before persistence.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryPayload {
    /// The explicitly saved text.
    pub content: String,
    /// Meaning of the saved text.
    pub category: Category,
    /// User-supplied provenance; untrusted data, not verified evidence.
    pub source: String,
}

impl MemoryPayload {
    /// Enforce bounded text before embedding, encryption or restore.
    pub fn validate(&self) -> Result<()> {
        if self.content.trim().is_empty() || self.content.len() > 16_384 {
            return Err(Error::InvalidInput(
                "Memory text must contain 1 to 16384 bytes",
            ));
        }
        if self.source.trim().is_empty() || self.source.len() > 1024 {
            return Err(Error::InvalidInput(
                "Memory source must contain 1 to 1024 bytes",
            ));
        }
        Ok(())
    }
}

/// A decrypted memory returned only to its owner.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Memory {
    /// Stable identifier for review, correction and deletion.
    pub id: String,
    /// Saved text and provenance.
    pub payload: MemoryPayload,
    /// Monotonic version for intentional updates.
    pub version: u64,
    /// Creation time in Unix seconds.
    pub created_at: u64,
    /// Last change time in Unix seconds.
    pub updated_at: u64,
    /// Optional expiry in Unix seconds.
    pub expires_at: Option<u64>,
}

/// A request to save one durable memory.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RememberRequest {
    /// Text and user-supplied provenance.
    pub payload: MemoryPayload,
    /// Caller-generated key reused only for an identical retry.
    pub idempotency_key: String,
    /// Optional expiry in Unix seconds.
    pub expires_at: Option<u64>,
}

/// A recall result includes the ranking mode, never an unsupported quality claim.
#[derive(Debug, Clone, Serialize)]
pub struct RecallResult {
    /// Either `semantic` or `keyword`.
    pub mode: &'static str,
    /// Relevant user-owned records.
    pub memories: Vec<Memory>,
}
