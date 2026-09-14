//! Server-held field encryption with owner-derived keys and authenticated record binding.
//!
//! This protects stored fields, not against an operator who holds the master key.

use std::collections::BTreeMap;

use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine as _,
};
use ring::{aead, hkdf, rand::SecureRandom};
use zeroize::{Zeroize, Zeroizing};

use crate::error::{Error, Result};

const PREFIX: &str = "elle-field-v1:";
const OWNER_KEY_SALT: &[u8] = b"elle/field-encryption/owner-key/v1";
const MAX_FIELD_BYTES: usize = 32 * 1024 * 1024;
const MAX_ID_BYTES: usize = 4096;

/// AES-256-GCM field encryption using an operator-held, zeroized-on-drop master key.
pub struct FieldCipher {
    master_key: [u8; 32],
}

impl Drop for FieldCipher {
    fn drop(&mut self) {
        self.master_key.zeroize();
    }
}

impl std::fmt::Debug for FieldCipher {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("FieldCipher")
            .finish_non_exhaustive()
    }
}

impl FieldCipher {
    /// Construct a cipher from a 32-byte master key supplied by the operator.
    pub fn new(master_key: [u8; 32]) -> Self {
        Self { master_key }
    }

    /// Decode exactly 32 bytes from standard, padded base64; missing keys fail closed.
    pub fn from_base64(encoded: &str) -> Result<Self> {
        if encoded.len() != 44 {
            return Err(Error::Configuration("Invalid field encryption master key"));
        }
        let mut decoded = Zeroizing::new([0_u8; 33]);
        let size = STANDARD
            .decode_slice(encoded, &mut decoded[..])
            .map_err(|_| Error::Configuration("Invalid field encryption master key"))?;
        if size != 32 {
            return Err(Error::Configuration("Invalid field encryption master key"));
        }
        let mut master_key = Zeroizing::new([0_u8; 32]);
        master_key.copy_from_slice(&decoded[..32]);
        Ok(Self::new(*master_key))
    }

    /// Encrypt up to 32 MiB with a fresh 96-bit nonce, binding owner, record and format.
    ///
    /// The format is `elle-field-v1:` followed by unpadded base64url of nonce,
    /// ciphertext and the 16-byte authentication tag. Identifiers must be nonblank
    /// and at most 4096 UTF-8 bytes; they are bound exactly, without normalization.
    pub fn encrypt(&self, owner_id: &str, record_id: &str, plaintext: &[u8]) -> Result<String> {
        let aad = field_aad(owner_id, record_id)?;
        if plaintext.len() > MAX_FIELD_BYTES {
            return Err(Error::InvalidInput("Field exceeds the size limit"));
        }
        let key = self.owner_key(owner_id)?;
        let nonce = random_bytes::<12>()?;
        let ciphertext = seal_with_nonce(&key, nonce, plaintext, &aad)?;
        let mut blob = Vec::with_capacity(12 + ciphertext.len());
        blob.extend_from_slice(&nonce);
        blob.extend_from_slice(&ciphertext);
        Ok(format!("{PREFIX}{}", URL_SAFE_NO_PAD.encode(blob)))
    }

    /// Authenticate and decrypt a supported field envelope; never accept plaintext.
    pub fn decrypt(&self, owner_id: &str, record_id: &str, ciphertext: &str) -> Result<Vec<u8>> {
        let aad = field_aad(owner_id, record_id)?;
        let encoded = ciphertext
            .strip_prefix(PREFIX)
            .ok_or(Error::Integrity("Unsupported field encryption format"))?;
        if encoded.len() > (MAX_FIELD_BYTES + 28).div_ceil(3) * 4 {
            return Err(Error::Integrity("Field exceeds the size limit"));
        }
        let blob = URL_SAFE_NO_PAD
            .decode(encoded)
            .map_err(|_| Error::Integrity("Invalid field encryption envelope"))?;
        if blob.len() < 28 || blob.len() > MAX_FIELD_BYTES + 28 {
            return Err(Error::Integrity("Invalid field encryption envelope"));
        }
        let nonce = blob[..12]
            .try_into()
            .map_err(|_| Error::Integrity("Invalid field encryption envelope"))?;
        let key = self.owner_key(owner_id)?;
        open(&key, nonce, &blob[12..], &aad)
    }

    fn owner_key(&self, owner_id: &str) -> Result<Zeroizing<[u8; 32]>> {
        let salt = hkdf::Salt::new(hkdf::HKDF_SHA256, OWNER_KEY_SALT);
        let prk = salt.extract(&self.master_key);
        let info = [
            b"elle/field-encryption/v1/owner/".as_slice(),
            owner_id.as_bytes(),
        ];
        let output = prk
            .expand(&info, hkdf::HKDF_SHA256)
            .map_err(|_| Error::Configuration("Field key derivation failed"))?;
        let mut key = Zeroizing::new([0_u8; 32]);
        output
            .fill(&mut key[..])
            .map_err(|_| Error::Configuration("Field key derivation failed"))?;
        Ok(key)
    }
}

fn field_aad(owner_id: &str, record_id: &str) -> Result<Vec<u8>> {
    if [owner_id, record_id]
        .iter()
        .any(|id| id.trim().is_empty() || id.len() > MAX_ID_BYTES)
    {
        return Err(Error::InvalidInput("Invalid encryption binding identifier"));
    }
    let fields = BTreeMap::from([
        ("format", PREFIX),
        ("ownerId", owner_id),
        ("recordId", record_id),
    ]);
    serde_json::to_vec(&fields)
        .map_err(|_| Error::InvalidInput("Invalid encryption binding identifier"))
}

/// Obtain a fixed-size buffer from the operating system random source.
pub(crate) fn random_bytes<const N: usize>() -> Result<[u8; N]> {
    let mut bytes = [0_u8; N];
    ring::rand::SystemRandom::new()
        .fill(&mut bytes)
        .map_err(|_| Error::Configuration("Cryptographic randomness unavailable"))?;
    Ok(bytes)
}

/// Seal with AES-256-GCM; the caller must supply a fresh nonce for this key.
pub(crate) fn seal_with_nonce(
    key: &[u8; 32],
    nonce: [u8; 12],
    plaintext: &[u8],
    aad: &[u8],
) -> Result<Vec<u8>> {
    let unbound = aead::UnboundKey::new(&aead::AES_256_GCM, key)
        .map_err(|_| Error::Configuration("Encryption initialization failed"))?;
    let key = aead::LessSafeKey::new(unbound);
    let mut buffer = Zeroizing::new(plaintext.to_vec());
    key.seal_in_place_append_tag(
        aead::Nonce::assume_unique_for_key(nonce),
        aead::Aad::from(aad),
        &mut *buffer,
    )
    .map_err(|_| Error::Integrity("Encryption failed"))?;
    Ok(std::mem::take(&mut *buffer))
}

/// Authenticate and decrypt an AES-256-GCM ciphertext and appended tag.
pub(crate) fn open(
    key: &[u8; 32],
    nonce: [u8; 12],
    ciphertext: &[u8],
    aad: &[u8],
) -> Result<Vec<u8>> {
    let unbound = aead::UnboundKey::new(&aead::AES_256_GCM, key)
        .map_err(|_| Error::Configuration("Encryption initialization failed"))?;
    let key = aead::LessSafeKey::new(unbound);
    let mut buffer = Zeroizing::new(ciphertext.to_vec());
    let size = key
        .open_in_place(
            aead::Nonce::assume_unique_for_key(nonce),
            aead::Aad::from(aad),
            &mut buffer,
        )
        .map_err(|_| Error::Integrity("Encrypted data authentication failed"))?
        .len();
    buffer.truncate(size);
    Ok(std::mem::take(&mut *buffer))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_binary_empty_and_randomized_ciphertext() {
        let cipher = FieldCipher::new([7; 32]);
        for plaintext in [b"\0\xffprivate data".as_slice(), b""] {
            let first = cipher.encrypt("owner-a", "record-a", plaintext).unwrap();
            let second = cipher.encrypt("owner-a", "record-a", plaintext).unwrap();
            assert_ne!(first, second);
            assert_eq!(
                cipher.decrypt("owner-a", "record-a", &first).unwrap(),
                plaintext
            );
        }
        assert_eq!(format!("{cipher:?}"), "FieldCipher { .. }");
    }

    #[test]
    fn rejects_wrong_key_owner_record_and_tampering() {
        let cipher = FieldCipher::new([7; 32]);
        let text = cipher.encrypt("owner-a", "record-a", b"private").unwrap();
        assert!(cipher.decrypt("owner-b", "record-a", &text).is_err());
        assert!(cipher.decrypt("owner-a", "record-b", &text).is_err());
        assert!(FieldCipher::new([8; 32])
            .decrypt("owner-a", "record-a", &text)
            .is_err());
        let original = URL_SAFE_NO_PAD
            .decode(text.strip_prefix(PREFIX).unwrap())
            .unwrap();
        for index in [0, 12, original.len() - 1] {
            let mut altered = original.clone();
            altered[index] ^= 1;
            let altered = format!("{PREFIX}{}", URL_SAFE_NO_PAD.encode(altered));
            assert!(cipher.decrypt("owner-a", "record-a", &altered).is_err());
        }
    }

    #[test]
    fn rejects_invalid_keys_envelopes_and_ambiguous_bindings() {
        for encoded in [
            "",
            "not base64",
            &STANDARD.encode([1; 31]),
            &STANDARD.encode([1; 33]),
        ] {
            assert!(FieldCipher::from_base64(encoded).is_err());
        }
        let cipher = FieldCipher::from_base64(&STANDARD.encode([1; 32])).unwrap();
        for encoded in [
            "plaintext",
            "elle-field-v2:AAAA",
            "elle-field-v1:!!!!",
            "elle-field-v1:AA",
        ] {
            assert!(cipher.decrypt("owner-a", "record-a", encoded).is_err());
        }
        assert!(cipher.encrypt("", "record-a", b"").is_err());
        let first = field_aad("a", "b:c").unwrap();
        let second = field_aad("a:b", "c").unwrap();
        assert_ne!(first, second);
    }
}
