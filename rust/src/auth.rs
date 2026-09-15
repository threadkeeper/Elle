//! Tenant-pinned Entra delegated access-token verification for the HTTP host.

use std::io::Read;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use ring::signature::{RsaPublicKeyComponents, RSA_PKCS1_2048_8192_SHA256};
use serde::Deserialize;

use crate::error::{Error, Result};
use crate::identity::OwnerId;

const MAX_TOKEN_BYTES: usize = 16 * 1024;
const MAX_JWKS_BYTES: u64 = 256 * 1024;
const CACHE_LIFETIME: Duration = Duration::from_secs(3600);
const REFRESH_INTERVAL: Duration = Duration::from_secs(60);
const CLOCK_LEEWAY: u64 = 30;

/// Verifies RS256 tokens for one configured tenant, application and owner.
///
/// No unverified claim or token-provided URL selects a key endpoint.
pub struct EntraVerifier {
    tenant_id: String,
    audience: String,
    allowed_object_id: Option<String>,
    authority: String,
    keys: Vec<VerificationKey>,
    fetched_at: Option<Instant>,
    last_attempt: Option<Instant>,
    agent: ureq::Agent,
}

struct VerificationKey {
    kid: String,
    modulus: Vec<u8>,
    exponent: Vec<u8>,
}

#[derive(Deserialize)]
struct TokenHeader {
    alg: String,
    kid: String,
    #[serde(default)]
    crit: Vec<String>,
    b64: Option<bool>,
}

#[derive(Deserialize)]
struct Claims {
    tid: String,
    oid: String,
    exp: u64,
    nbf: u64,
    iss: String,
    aud: String,
    scp: String,
}

#[derive(Deserialize)]
struct KeySet {
    keys: Vec<Jwk>,
}

#[derive(Deserialize)]
struct Jwk {
    kid: String,
    kty: String,
    n: Option<String>,
    e: Option<String>,
    alg: Option<String>,
    #[serde(rename = "use")]
    usage: Option<String>,
}

impl EntraVerifier {
    /// Validate UUID configuration without performing network or credential reads.
    pub fn new(tenant_id: &str, audience: &str, allowed_object_id: &str) -> Result<Self> {
        if ![tenant_id, audience, allowed_object_id]
            .iter()
            .all(|value| valid_uuid(value))
        {
            return Err(Error::Configuration(
                "Entra tenant, audience and allowed object ID must be nonzero UUIDs",
            ));
        }
        Ok(Self {
            tenant_id: tenant_id.to_owned(),
            audience: audience.to_owned(),
            allowed_object_id: Some(allowed_object_id.to_owned()),
            authority: format!("https://login.microsoftonline.com/{tenant_id}/v2.0"),
            keys: Vec::new(),
            fetched_at: None,
            last_attempt: None,
            agent: ureq::AgentBuilder::new()
                .timeout(Duration::from_secs(10))
                .redirects(0)
                .build(),
        })
    }

    /// Verify any delegated user in one configured tenant and application.
    pub fn for_tenant_users(tenant_id: &str, audience: &str) -> Result<Self> {
        if ![tenant_id, audience].iter().all(|value| valid_uuid(value)) {
            return Err(Error::Configuration(
                "Entra tenant and audience must be nonzero UUIDs",
            ));
        }
        Ok(Self {
            tenant_id: tenant_id.to_owned(),
            audience: audience.to_owned(),
            allowed_object_id: None,
            authority: format!("https://login.microsoftonline.com/{tenant_id}/v2.0"),
            keys: Vec::new(),
            fetched_at: None,
            last_attempt: None,
            agent: ureq::AgentBuilder::new()
                .timeout(Duration::from_secs(10))
                .redirects(0)
                .build(),
        })
    }

    /// Return the operator-pinned authorization-server issuer for discovery.
    pub fn authority(&self) -> &str {
        &self.authority
    }

    /// Authenticate and authorize a bounded delegated JWT before constructing its owner.
    ///
    /// All failures are redacted; cached keys expire after one hour and refresh
    /// attempts, including unknown-key requests, are limited to once per minute.
    pub fn verify(&mut self, token: &str) -> Result<OwnerId> {
        if token.is_empty() || token.len() > MAX_TOKEN_BYTES {
            return Err(Error::Unauthorized);
        }
        let mut parts = token.split('.');
        let header_part = parts.next().ok_or(Error::Unauthorized)?;
        let claims_part = parts.next().ok_or(Error::Unauthorized)?;
        let signature_part = parts.next().ok_or(Error::Unauthorized)?;
        if parts.next().is_some()
            || [header_part, claims_part, signature_part]
                .iter()
                .any(|part| part.is_empty())
        {
            return Err(Error::Unauthorized);
        }
        let header: TokenHeader =
            serde_json::from_slice(&decode(header_part)?).map_err(|_| Error::Unauthorized)?;
        if header.alg != "RS256"
            || !valid_kid(&header.kid)
            || !header.crit.is_empty()
            || header.b64 == Some(false)
        {
            return Err(Error::Unauthorized);
        }
        let signature = decode(signature_part)?;
        if !(256..=1024).contains(&signature.len()) {
            return Err(Error::Unauthorized);
        }
        let claims_bytes = decode(claims_part)?;
        self.ensure_key(&header.kid)?;
        let key = self
            .keys
            .iter()
            .find(|key| key.kid == header.kid)
            .ok_or(Error::Unauthorized)?;
        let signed_length = header_part.len() + 1 + claims_part.len();
        RsaPublicKeyComponents {
            n: key.modulus.as_slice(),
            e: key.exponent.as_slice(),
        }
        .verify(
            &RSA_PKCS1_2048_8192_SHA256,
            &token.as_bytes()[..signed_length],
            &signature,
        )
        .map_err(|_| Error::Unauthorized)?;
        // Claims are interpreted only after authenticating their exact encoded bytes.
        let claims: Claims =
            serde_json::from_slice(&claims_bytes).map_err(|_| Error::Unauthorized)?;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| Error::Unauthorized)?
            .as_secs();
        self.validate_claims(&claims, now)
    }

    fn validate_claims(&self, claims: &Claims, now: u64) -> Result<OwnerId> {
        if claims.tid != self.tenant_id
            || self
                .allowed_object_id
                .as_ref()
                .is_some_and(|allowed| claims.oid != *allowed)
            || claims.aud != self.audience
            || claims.iss != self.authority
            || !claims
                .scp
                .split_ascii_whitespace()
                .any(|s| s == "access_as_user")
            || claims.exp <= now.saturating_sub(CLOCK_LEEWAY)
            || claims.nbf > now.saturating_add(CLOCK_LEEWAY)
            || claims.nbf >= claims.exp
        {
            return Err(Error::Unauthorized);
        }
        OwnerId::new(&claims.tid, &claims.oid).map_err(|_| Error::Unauthorized)
    }

    fn ensure_key(&mut self, kid: &str) -> Result<()> {
        let now = Instant::now();
        let fresh = self
            .fetched_at
            .is_some_and(|fetched| now.duration_since(fetched) < CACHE_LIFETIME);
        if fresh && self.keys.iter().any(|key| key.kid == kid) {
            return Ok(());
        }
        if self
            .last_attempt
            .is_some_and(|attempt| now.duration_since(attempt) < REFRESH_INTERVAL)
        {
            return Err(Error::Unauthorized);
        }
        self.last_attempt = Some(now);
        let endpoint = format!(
            "https://login.microsoftonline.com/{}/discovery/v2.0/keys",
            self.tenant_id
        );
        let response = self
            .agent
            .get(&endpoint)
            .call()
            .map_err(|_| Error::Unauthorized)?;
        if response.status() != 200 {
            return Err(Error::Unauthorized);
        }
        let mut bytes = Vec::new();
        response
            .into_reader()
            .take(MAX_JWKS_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| Error::Unauthorized)?;
        if bytes.len() as u64 > MAX_JWKS_BYTES {
            return Err(Error::Unauthorized);
        }
        let keys = parse_keys(&bytes)?;
        self.keys = keys;
        self.fetched_at = Some(Instant::now());
        if self.keys.iter().any(|key| key.kid == kid) {
            Ok(())
        } else {
            Err(Error::Unauthorized)
        }
    }
}

fn decode(value: &str) -> Result<Vec<u8>> {
    URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| Error::Unauthorized)
}

fn valid_uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit()
            }
        })
        && value.bytes().any(|byte| byte != b'0' && byte != b'-')
}

fn valid_kid(kid: &str) -> bool {
    !kid.is_empty() && kid.len() <= 256 && kid.bytes().all(|byte| byte.is_ascii_graphic())
}

fn parse_keys(bytes: &[u8]) -> Result<Vec<VerificationKey>> {
    let set: KeySet = serde_json::from_slice(bytes).map_err(|_| Error::Unauthorized)?;
    if set.keys.len() > 100 {
        return Err(Error::Unauthorized);
    }
    let mut keys = Vec::new();
    for key in set.keys {
        if key.kty != "RSA"
            || !valid_kid(&key.kid)
            || key.alg.as_deref().is_some_and(|alg| alg != "RS256")
            || key.usage.as_deref().is_some_and(|usage| usage != "sig")
        {
            continue;
        }
        let (Some(n), Some(e)) = (key.n, key.e) else {
            continue;
        };
        let modulus = decode(&n)?;
        let exponent = decode(&e)?;
        if !(256..=1024).contains(&modulus.len()) || !(1..=8).contains(&exponent.len()) {
            continue;
        }
        if keys
            .iter()
            .any(|existing: &VerificationKey| existing.kid == key.kid)
        {
            return Err(Error::Unauthorized);
        }
        keys.push(VerificationKey {
            kid: key.kid,
            modulus,
            exponent,
        });
    }
    if keys.is_empty() {
        return Err(Error::Unauthorized);
    }
    Ok(keys)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const TENANT: &str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    const APP: &str = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
    const OWNER: &str = "cccccccc-cccc-cccc-cccc-cccccccccccc";

    fn verifier() -> EntraVerifier {
        EntraVerifier::new(TENANT, APP, OWNER).unwrap()
    }

    #[test]
    fn config_is_pinned_and_checked_offline() {
        assert!(EntraVerifier::new("common", APP, OWNER).is_err());
        assert!(EntraVerifier::new(TENANT, "api://app", OWNER).is_err());
        assert!(EntraVerifier::new(TENANT, APP, "00000000-0000-0000-0000-000000000000").is_err());
        assert_eq!(
            verifier().authority(),
            "https://login.microsoftonline.com/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/v2.0"
        );
    }

    #[test]
    fn malformed_tokens_never_fetch_keys() {
        let mut verifier = verifier();
        for token in ["", "a", "a.b", "a.b.c.d", "..", "%%.a.a", "e30.e30.AA"] {
            assert_eq!(verifier.verify(token), Err(Error::Unauthorized));
        }
        let header = URL_SAFE_NO_PAD.encode(br#"{"alg":"none","kid":"example"}"#);
        assert!(verifier.verify(&format!("{header}.e30.AA")).is_err());
        assert!(verifier.verify(&"a".repeat(MAX_TOKEN_BYTES + 1)).is_err());
        assert!(verifier.last_attempt.is_none());
    }

    #[test]
    fn claims_require_exact_owner_audience_issuer_and_scope() {
        let verifier = verifier();
        let valid = json!({
            "tid":TENANT,"oid":OWNER,"aud":APP,"iss":verifier.authority(),
            "exp":1100,"nbf":900,"scp":"other access_as_user"
        });
        let claims: Claims = serde_json::from_value(valid.clone()).unwrap();
        assert!(verifier.validate_claims(&claims, 1000).is_ok());
        for (field, value) in [
            ("tid", json!(APP)),
            ("oid", json!(APP)),
            ("aud", json!(TENANT)),
            ("iss", json!("https://attacker.example/v2.0")),
            ("scp", json!("access_as_user_extra")),
            ("exp", json!(970)),
            ("nbf", json!(1031)),
        ] {
            let mut invalid = valid.clone();
            invalid[field] = value;
            let claims = serde_json::from_value(invalid).unwrap();
            assert!(verifier.validate_claims(&claims, 1000).is_err(), "{field}");
        }

        for field in ["tid", "oid", "aud", "iss", "exp", "nbf", "scp"] {
            let mut invalid = valid.clone();
            invalid.as_object_mut().unwrap().remove(field);
            assert!(serde_json::from_value::<Claims>(invalid).is_err());
        }
    }

    #[test]
    fn tenant_user_mode_accepts_distinct_delegated_users_in_the_same_tenant() {
        let verifier = EntraVerifier::for_tenant_users(TENANT, APP).unwrap();
        for owner in [OWNER, "dddddddd-dddd-dddd-dddd-dddddddddddd"] {
            let claims: Claims = serde_json::from_value(json!({
                "tid":TENANT,"oid":owner,"aud":APP,"iss":verifier.authority(),
                "exp":1100,"nbf":900,"scp":"access_as_user"
            }))
            .unwrap();
            let identity = verifier.validate_claims(&claims, 1000).unwrap();
            assert!(identity.as_str().ends_with(owner));
        }
        let wrong_tenant: Claims = serde_json::from_value(json!({
            "tid":APP,"oid":OWNER,"aud":APP,"iss":verifier.authority(),
            "exp":1100,"nbf":900,"scp":"access_as_user"
        }))
        .unwrap();
        assert!(verifier.validate_claims(&wrong_tenant, 1000).is_err());
    }

    #[test]
    fn cached_keys_reject_bad_signatures_and_rate_limit_unknown_kids_offline() {
        let mut verifier = verifier();
        verifier.keys = parse_keys(
            &serde_json::to_vec(&json!({"keys":[{
                "kid":"test","kty":"RSA","alg":"RS256","use":"sig",
                "n":URL_SAFE_NO_PAD.encode([0xff;256]),"e":"AQAB"
            }]}))
            .unwrap(),
        )
        .unwrap();
        verifier.fetched_at = Some(Instant::now());
        verifier.last_attempt = Some(Instant::now());
        let header = URL_SAFE_NO_PAD.encode(br#"{"alg":"RS256","kid":"test"}"#);
        let signature = URL_SAFE_NO_PAD.encode([0; 256]);
        assert!(verifier
            .verify(&format!("{header}.e30.{signature}"))
            .is_err());
        assert!(verifier.ensure_key("unknown").is_err());
        verifier.fetched_at = Some(Instant::now() - CACHE_LIFETIME);
        assert!(verifier.ensure_key("test").is_err());
    }
}
