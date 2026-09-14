//! Redacted, actionable errors shared by Elle's service boundaries.

use std::fmt;

/// An operation failed without exposing private data or upstream response bodies.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// Caller-supplied data failed validation.
    InvalidInput(&'static str),
    /// Required operator configuration is missing or invalid.
    Configuration(&'static str),
    /// Cryptographic validation or an archive-integrity check failed.
    Integrity(&'static str),
    /// The caller is not authorized for the operation.
    Unauthorized,
    /// No owned record matches the requested identifier.
    NotFound,
    /// A concurrent change or reused idempotency key prevented the operation.
    Conflict,
    /// A network operation failed.
    Transport(&'static str),
    /// A persistence operation failed.
    Storage(&'static str),
}

/// A result whose errors are safe to return across the MCP boundary.
pub type Result<T> = std::result::Result<T, Error>;

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidInput(message)
            | Self::Configuration(message)
            | Self::Integrity(message)
            | Self::Transport(message)
            | Self::Storage(message) => formatter.write_str(message),
            Self::Unauthorized => formatter.write_str("Access denied"),
            Self::NotFound => formatter.write_str("Owned record not found"),
            Self::Conflict => formatter.write_str("Record changed or request key was already used"),
        }
    }
}

impl std::error::Error for Error {}
