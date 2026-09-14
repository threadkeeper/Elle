//! Immutable owner keys supplied by a trusted host, never by model arguments.

use crate::error::{Error, Result};

/// Canonical tenant and user UUIDs identifying one memory owner.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OwnerId(String);

impl OwnerId {
    /// Validate UUID-shaped Entra identifiers; this does not validate a token.
    ///
    /// HTTP hosts must authenticate and authorize their caller before construction.
    pub fn new(tenant_id: &str, object_id: &str) -> Result<Self> {
        for value in [tenant_id, object_id] {
            if value.len() != 36
                || !value.bytes().enumerate().all(|(index, byte)| {
                    if [8, 13, 18, 23].contains(&index) {
                        byte == b'-'
                    } else {
                        byte.is_ascii_hexdigit()
                    }
                })
                || value.bytes().all(|byte| byte == b'0' || byte == b'-')
            {
                return Err(Error::InvalidInput("Tenant and user must be nonzero UUIDs"));
            }
        }
        Ok(Self(format!(
            "{}:{}",
            tenant_id.to_ascii_lowercase(),
            object_id.to_ascii_lowercase()
        )))
    }

    /// Return the canonical owner partition.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn owner_is_canonical_and_not_an_email() {
        let owner = OwnerId::new(
            "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )
        .unwrap();
        assert!(owner.as_str().starts_with("aaaaaaaa"));
        assert!(OwnerId::new("person@example.com", "user").is_err());
        assert!(OwnerId::new(
            "00000000-0000-0000-0000-000000000000",
            "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        )
        .is_err());
    }
}
