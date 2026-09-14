//! Passphrase-encrypted, owner-bound application snapshots.
//!
//! Version 1 uses an authenticated 84-byte header, Zstandard level 3, and
//! AES-256-GCM with PBKDF2-HMAC-SHA256 (600,000 iterations). Compressed JSON is
//! limited to 16 MiB, expanded JSON to 32 MiB, and JSON nesting to 64 levels.
//! Object keys are sorted recursively; arrays and all supplied data are preserved.

use std::collections::BTreeMap;
use std::io::{Cursor, Read, Write};
use std::num::NonZeroU32;

use ring::pbkdf2;
use serde::{ser::SerializeSeq, Deserialize, Serialize, Serializer};
use serde_json::Value;
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

use crate::encryption::{open, random_bytes, seal_with_nonce};
use crate::error::{Error, Result};

const MAGIC: &[u8; 8] = b"ELLEDAT1";
const VERSION: u8 = 1;
const ZSTD_LEVEL: i32 = 3;
const ITERATIONS: u32 = 600_000;
const HEADER_LENGTH: usize = 84;
const MAX_COMPRESSED_BYTES: usize = 16 * 1024 * 1024;
const MAX_EXPANDED_BYTES: usize = 32 * 1024 * 1024;
const MAX_DEPTH: usize = 64;

/// Stateless codec for mandatory passphrase-encrypted application snapshots.
#[derive(Debug, Clone, Copy, Default)]
pub struct ArchiveCodec;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct SnapshotRef<'a> {
    data: Canonical<'a>,
    owner_id: &'a str,
    schema_version: u32,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Snapshot {
    data: Value,
    owner_id: String,
    schema_version: u32,
}

impl ArchiveCodec {
    /// Encode a complete JSON snapshot, bound to a nonblank owner identifier.
    ///
    /// Passphrases require at least 12 Unicode scalar values and a non-whitespace
    /// character; their exact UTF-8 bytes are used without trimming or normalization.
    /// Owners are limited to 4096 bytes and passphrases to 4096 bytes.
    /// Returns an error rather than truncating data that exceeds the module limits.
    pub fn encode(owner_id: &str, data: &Value, passphrase: &str) -> Result<Vec<u8>> {
        validate_inputs(owner_id, passphrase)?;
        let json = snapshot_json(owner_id, data)?;
        let mut compressed = LimitedWriter::new(MAX_COMPRESSED_BYTES);
        {
            let mut encoder = zstd::stream::write::Encoder::new(&mut compressed, ZSTD_LEVEL)
                .map_err(|_| Error::Integrity("Archive compression failed"))?;
            encoder
                .write_all(&json)
                .map_err(|_| Error::InvalidInput("Archive exceeds compression limits"))?;
            encoder
                .finish()
                .map_err(|_| Error::InvalidInput("Archive exceeds compression limits"))?;
        }
        let salt = random_bytes::<16>()?;
        let nonce = random_bytes::<12>()?;
        let mut header = build_header(json.len(), Sha256::digest(&json).into(), salt, nonce);
        let key = derive_key(passphrase, &salt)?;
        let ciphertext = seal_with_nonce(&key, nonce, &compressed.bytes, &header)?;
        header.extend_from_slice(&ciphertext);
        Ok(header)
    }

    /// Authenticate, bound decompression, and validate an archive before returning data.
    ///
    /// Unknown formats, plaintext archives, malformed JSON, owner mismatches and
    /// any failed integrity check reject the entire snapshot; nothing is skipped.
    pub fn decode(owner_id: &str, bytes: &[u8], passphrase: &str) -> Result<Value> {
        validate_inputs(owner_id, passphrase)?;
        if bytes.len() < HEADER_LENGTH + 16
            || bytes.len() > HEADER_LENGTH + MAX_COMPRESSED_BYTES + 16
        {
            return Err(Error::Integrity("Invalid or oversized archive"));
        }
        if &bytes[..8] != MAGIC
            || bytes[8] != VERSION
            || bytes[9] != 1
            || bytes[10] != 1
            || bytes[11] != ZSTD_LEVEL as u8
            || bytes[12..16] != ITERATIONS.to_le_bytes()
        {
            return Err(Error::Integrity("Unsupported archive format"));
        }
        let expanded = u64::from_le_bytes(
            bytes[16..24]
                .try_into()
                .map_err(|_| Error::Integrity("Invalid archive header"))?,
        );
        if expanded == 0 || expanded > MAX_EXPANDED_BYTES as u64 {
            return Err(Error::Integrity("Invalid archive expanded size"));
        }
        let salt = bytes[56..72]
            .try_into()
            .map_err(|_| Error::Integrity("Invalid archive header"))?;
        let nonce = bytes[72..84]
            .try_into()
            .map_err(|_| Error::Integrity("Invalid archive header"))?;
        let key = derive_key(passphrase, &salt)?;
        let compressed = Zeroizing::new(open(
            &key,
            nonce,
            &bytes[HEADER_LENGTH..],
            &bytes[..HEADER_LENGTH],
        )?);
        let json = decompress(&compressed, expanded as usize)?;
        if Sha256::digest(&json)[..] != bytes[24..56] {
            return Err(Error::Integrity("Archive integrity check failed"));
        }
        let snapshot: Snapshot = serde_json::from_slice(&json)
            .map_err(|_| Error::Integrity("Malformed archive snapshot"))?;
        if snapshot.schema_version != 1 || snapshot.owner_id != owner_id {
            return Err(Error::Integrity("Archive owner or schema mismatch"));
        }
        // Exact canonical encoding rejects duplicate keys and noncanonical payloads.
        if *snapshot_json(owner_id, &snapshot.data)? != *json {
            return Err(Error::Integrity("Noncanonical archive snapshot"));
        }
        Ok(snapshot.data)
    }
}

fn validate_inputs(owner_id: &str, passphrase: &str) -> Result<()> {
    if owner_id.trim().is_empty() || owner_id.len() > 4096 {
        return Err(Error::InvalidInput("Invalid archive owner"));
    }
    if passphrase.len() > 4096 || passphrase.chars().count() < 12 || passphrase.trim().is_empty() {
        return Err(Error::InvalidInput(
            "Archive passphrase requires at least 12 characters",
        ));
    }
    Ok(())
}

fn derive_key(passphrase: &str, salt: &[u8; 16]) -> Result<Zeroizing<[u8; 32]>> {
    let iterations = NonZeroU32::new(ITERATIONS).ok_or(Error::Configuration(
        "Invalid archive key derivation configuration",
    ))?;
    let mut key = Zeroizing::new([0_u8; 32]);
    pbkdf2::derive(
        pbkdf2::PBKDF2_HMAC_SHA256,
        iterations,
        salt,
        passphrase.as_bytes(),
        &mut key[..],
    );
    Ok(key)
}

fn build_header(expanded: usize, digest: [u8; 32], salt: [u8; 16], nonce: [u8; 12]) -> Vec<u8> {
    let mut header = Vec::with_capacity(HEADER_LENGTH);
    header.extend_from_slice(MAGIC);
    header.extend_from_slice(&[VERSION, 1, 1, ZSTD_LEVEL as u8]);
    header.extend_from_slice(&ITERATIONS.to_le_bytes());
    header.extend_from_slice(&(expanded as u64).to_le_bytes());
    header.extend_from_slice(&digest);
    header.extend_from_slice(&salt);
    header.extend_from_slice(&nonce);
    header
}

fn decompress(compressed: &[u8], expanded: usize) -> Result<Zeroizing<Vec<u8>>> {
    let mut decoder = zstd::stream::read::Decoder::with_buffer(Cursor::new(compressed))
        .map_err(|_| Error::Integrity("Invalid archive compression"))?
        .single_frame();
    decoder
        .window_log_max(25)
        .map_err(|_| Error::Integrity("Invalid archive compression window"))?;
    let mut json = Zeroizing::new(Vec::new());
    decoder
        .by_ref()
        .take(expanded as u64 + 1)
        .read_to_end(&mut json)
        .map_err(|_| Error::Integrity("Invalid archive compressed payload"))?;
    if json.len() != expanded || decoder.finish().position() != compressed.len() as u64 {
        return Err(Error::Integrity(
            "Archive expanded size or framing mismatch",
        ));
    }
    Ok(json)
}

fn snapshot_json(owner_id: &str, data: &Value) -> Result<Zeroizing<Vec<u8>>> {
    let mut output = LimitedWriter::new(MAX_EXPANDED_BYTES);
    serde_json::to_writer(
        &mut output,
        &SnapshotRef {
            data: Canonical {
                value: data,
                depth: 0,
            },
            owner_id,
            schema_version: 1,
        },
    )
    .map_err(|_| Error::InvalidInput("Archive exceeds JSON size or nesting limits"))?;
    Ok(output.bytes)
}

struct Canonical<'a> {
    value: &'a Value,
    depth: usize,
}

impl Serialize for Canonical<'_> {
    fn serialize<S: Serializer>(&self, serializer: S) -> std::result::Result<S::Ok, S::Error> {
        if self.depth > MAX_DEPTH {
            return Err(serde::ser::Error::custom("JSON nesting limit exceeded"));
        }
        match self.value {
            Value::Object(object) => {
                let sorted: BTreeMap<_, _> = object
                    .iter()
                    .map(|(key, value)| {
                        (
                            key,
                            Canonical {
                                value,
                                depth: self.depth + 1,
                            },
                        )
                    })
                    .collect();
                sorted.serialize(serializer)
            }
            Value::Array(array) => {
                let mut sequence = serializer.serialize_seq(Some(array.len()))?;
                for value in array {
                    sequence.serialize_element(&Canonical {
                        value,
                        depth: self.depth + 1,
                    })?;
                }
                sequence.end()
            }
            value => value.serialize(serializer),
        }
    }
}

struct LimitedWriter {
    bytes: Zeroizing<Vec<u8>>,
    limit: usize,
}

impl LimitedWriter {
    fn new(limit: usize) -> Self {
        Self {
            bytes: Zeroizing::new(Vec::new()),
            limit,
        }
    }
}

impl Write for LimitedWriter {
    fn write(&mut self, buffer: &[u8]) -> std::io::Result<usize> {
        if buffer.len() > self.limit.saturating_sub(self.bytes.len()) {
            return Err(std::io::Error::other("Archive size limit exceeded"));
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::OnceLock;

    const PASSWORD: &str = "twelve or more characters";

    fn data() -> Value {
        serde_json::json!({
            "settings": {"enabled": true, "label": "日本語"},
            "records": [null, 7, {"arbitrary": ["keep", "all", "data"]}],
            "other": "repeated payload ".repeat(1000)
        })
    }

    fn encoded() -> &'static Vec<u8> {
        static ARCHIVE: OnceLock<Vec<u8>> = OnceLock::new();
        ARCHIVE.get_or_init(|| ArchiveCodec::encode("owner-a", &data(), PASSWORD).unwrap())
    }

    #[test]
    fn round_trip_preserves_every_value_and_randomizes_archives() {
        let bytes = encoded();
        assert_eq!(
            ArchiveCodec::decode("owner-a", bytes, PASSWORD).unwrap(),
            data()
        );
        assert!(bytes.len() < serde_json::to_vec(&data()).unwrap().len() / 5);
        let other = ArchiveCodec::encode("owner-a", &data(), PASSWORD).unwrap();
        assert_ne!(bytes, &other);
        assert_ne!(&bytes[56..84], &other[56..84]);
    }

    #[test]
    fn wrong_owner_and_password_fail() {
        assert!(ArchiveCodec::decode("owner-b", encoded(), PASSWORD).is_err());
        assert!(ArchiveCodec::decode("owner-a", encoded(), "different long password").is_err());
    }

    #[test]
    fn header_and_ciphertext_are_authenticated() {
        for index in [24, HEADER_LENGTH, encoded().len() - 1] {
            let mut altered = encoded().clone();
            altered[index] ^= 1;
            assert!(ArchiveCodec::decode("owner-a", &altered, PASSWORD).is_err());
        }
    }

    #[test]
    fn unsupported_formats_and_declared_bounds_fail_before_derivation() {
        let base = build_header(1, [0; 32], [0; 16], [0; 12]);
        let mut base = [base, vec![0; 16]].concat();
        for index in [0, 8, 9, 10, 11, 12] {
            let mut altered = base.clone();
            altered[index] ^= 3;
            assert!(ArchiveCodec::decode("owner-a", &altered, PASSWORD).is_err());
        }
        base[16..24].copy_from_slice(&(MAX_EXPANDED_BYTES as u64 + 1).to_le_bytes());
        assert!(ArchiveCodec::decode("owner-a", &base, PASSWORD).is_err());
        assert!(ArchiveCodec::decode("owner-a", &[0; 83], PASSWORD).is_err());
        let oversized = vec![0; HEADER_LENGTH + MAX_COMPRESSED_BYTES + 17];
        assert!(ArchiveCodec::decode("owner-a", &oversized, PASSWORD).is_err());
    }

    #[test]
    fn passwords_count_unicode_characters_without_trimming() {
        for password in ["", "short", "éééééé", "            "] {
            assert!(ArchiveCodec::encode("owner-a", &Value::Null, password).is_err());
            assert!(ArchiveCodec::decode("owner-a", &[], password).is_err());
        }
        assert!(validate_inputs("owner-a", "é".repeat(12).as_str()).is_ok());
        assert!(validate_inputs("owner-a", " 1234567890 ").is_ok());
    }

    #[test]
    fn bounded_serialization_and_decompression_reject_partial_data() {
        let mut writer = LimitedWriter::new(3);
        writer.write_all(b"abc").unwrap();
        assert!(writer.write_all(b"d").is_err());
        let large = Value::String("x".repeat(MAX_EXPANDED_BYTES));
        assert!(ArchiveCodec::encode("owner-a", &large, PASSWORD).is_err());
        let mut nested = Value::Null;
        for _ in 0..MAX_DEPTH + 2 {
            nested = Value::Array(vec![nested]);
        }
        assert!(snapshot_json("owner-a", &nested).is_err());
        let compressed = zstd::stream::encode_all(Cursor::new(b"abcdef"), 3).unwrap();
        assert_eq!(&*decompress(&compressed, 6).unwrap(), b"abcdef");
        assert!(decompress(&compressed, 5).is_err());
        assert!(decompress(&compressed[..compressed.len() - 1], 6).is_err());
        let appended = [compressed.clone(), compressed].concat();
        assert!(decompress(&appended, 6).is_err());
    }
}
