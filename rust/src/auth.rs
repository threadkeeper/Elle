//! Tenant-pinned Entra delegated access-token verification for the HTTP host.

use std::collections::BTreeSet;
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum AuthRejection {
    TokenFormatInvalid,
    HeaderRejected,
    SigningKeyUnavailable,
    SignatureInvalid,
    ClaimsShapeInvalid,
    TenantMismatch,
    OwnerNotAllowed,
    AudienceMismatch,
    IssuerMismatch,
    ScopeMissing,
    DelegatedScopePresent,
    ActorMismatch,
    ClientMismatch,
    RoleMismatch,
    VersionMismatch,
    TokenTypeInvalid,
    LifetimeInvalid,
}

impl AuthRejection {
    pub(crate) fn label(self) -> &'static str {
        match self {
            Self::TokenFormatInvalid => "token_format_invalid",
            Self::HeaderRejected => "header_rejected",
            Self::SigningKeyUnavailable => "signing_key_unavailable",
            Self::SignatureInvalid => "signature_invalid",
            Self::ClaimsShapeInvalid => "claims_shape_invalid",
            Self::TenantMismatch => "tenant_mismatch",
            Self::OwnerNotAllowed => "owner_not_allowed",
            Self::AudienceMismatch => "audience_mismatch",
            Self::IssuerMismatch => "issuer_mismatch",
            Self::ScopeMissing => "scope_missing",
            Self::DelegatedScopePresent => "delegated_scope_present",
            Self::ActorMismatch => "actor_mismatch",
            Self::ClientMismatch => "client_mismatch",
            Self::RoleMismatch => "role_mismatch",
            Self::VersionMismatch => "version_mismatch",
            Self::TokenTypeInvalid => "token_type_invalid",
            Self::LifetimeInvalid => "lifetime_invalid",
        }
    }
}

type AuthResult<T> = std::result::Result<T, AuthRejection>;

/// Verifies RS256 tokens for one configured tenant, application and owner.
///
/// No unverified claim or token-provided URL selects a key endpoint.
pub struct EntraVerifier {
    tenant_id: String,
    audience: String,
    allowed_object_ids: Option<BTreeSet<String>>,
    authority: String,
    keys: Vec<VerificationKey>,
    fetched_at: Option<Instant>,
    last_attempt: Option<Instant>,
    agent: ureq::Agent,
}

/// Verifies one tenant-pinned Entra v2 application identity and app role.
pub struct WorkloadEntraVerifier {
    verifier: EntraVerifier,
    actor_id: String,
    client_id: String,
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
struct WorkloadClaims {
    tid: String,
    oid: String,
    exp: u64,
    nbf: u64,
    iss: String,
    aud: String,
    azp: Option<String>,
    appid: Option<String>,
    roles: Vec<String>,
    ver: String,
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
        Self::configured(
            tenant_id,
            audience,
            Some(BTreeSet::from([allowed_object_id.to_owned()])),
        )
    }

    /// Verify delegated users from an explicit allow-list in one tenant.
    pub fn for_users(tenant_id: &str, audience: &str, object_ids: &[String]) -> Result<Self> {
        if object_ids.is_empty()
            || ![tenant_id, audience].iter().all(|value| valid_uuid(value))
            || object_ids.iter().any(|value| !valid_uuid(value))
        {
            return Err(Error::Configuration(
                "Entra tenant, audience and allowed object IDs must be nonzero UUIDs",
            ));
        }
        Self::configured(
            tenant_id,
            audience,
            Some(object_ids.iter().cloned().collect()),
        )
    }

    /// Verify any delegated user in one configured tenant and application.
    pub fn for_tenant_users(tenant_id: &str, audience: &str) -> Result<Self> {
        if ![tenant_id, audience].iter().all(|value| valid_uuid(value)) {
            return Err(Error::Configuration(
                "Entra tenant and audience must be nonzero UUIDs",
            ));
        }
        Self::configured(tenant_id, audience, None)
    }

    fn configured(
        tenant_id: &str,
        audience: &str,
        allowed_object_ids: Option<BTreeSet<String>>,
    ) -> Result<Self> {
        Ok(Self {
            tenant_id: tenant_id.to_owned(),
            audience: audience.to_owned(),
            allowed_object_ids: allowed_object_ids.map(|object_ids| {
                object_ids
                    .into_iter()
                    .map(|object_id| object_id.to_ascii_lowercase())
                    .collect()
            }),
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

    /// Return the fully qualified delegated scope required by OAuth clients.
    pub fn delegated_scope(&self) -> String {
        format!("api://{}/access_as_user", self.audience)
    }

    /// Authenticate and authorize a bounded delegated JWT before constructing its owner.
    ///
    /// All failures are redacted; cached keys expire after one hour and refresh
    /// attempts, including unknown-key requests, are limited to once per minute.
    pub fn verify(&mut self, token: &str) -> Result<OwnerId> {
        self.verify_diagnostic(token)
            .map_err(|_| Error::Unauthorized)
    }

    pub(crate) fn verify_diagnostic(&mut self, token: &str) -> AuthResult<OwnerId> {
        let claims_bytes = self.verify_signed_claims(token)?;
        let claims: Claims =
            serde_json::from_slice(&claims_bytes).map_err(|_| AuthRejection::ClaimsShapeInvalid)?;
        self.validate_claims(&claims, unix_time()?)
    }

    fn verify_signed_claims(&mut self, token: &str) -> AuthResult<Vec<u8>> {
        if token.is_empty() || token.len() > MAX_TOKEN_BYTES {
            return Err(AuthRejection::TokenFormatInvalid);
        }
        let mut parts = token.split('.');
        let header_part = parts.next().ok_or(AuthRejection::TokenFormatInvalid)?;
        let claims_part = parts.next().ok_or(AuthRejection::TokenFormatInvalid)?;
        let signature_part = parts.next().ok_or(AuthRejection::TokenFormatInvalid)?;
        if parts.next().is_some()
            || [header_part, claims_part, signature_part]
                .iter()
                .any(|part| part.is_empty())
        {
            return Err(AuthRejection::TokenFormatInvalid);
        }
        let header_bytes = decode(header_part).map_err(|_| AuthRejection::TokenFormatInvalid)?;
        let header: TokenHeader =
            serde_json::from_slice(&header_bytes).map_err(|_| AuthRejection::HeaderRejected)?;
        if header.alg != "RS256"
            || !valid_kid(&header.kid)
            || !header.crit.is_empty()
            || header.b64 == Some(false)
        {
            return Err(AuthRejection::HeaderRejected);
        }
        let signature = decode(signature_part).map_err(|_| AuthRejection::TokenFormatInvalid)?;
        if !(256..=1024).contains(&signature.len()) {
            return Err(AuthRejection::TokenFormatInvalid);
        }
        let claims_bytes = decode(claims_part).map_err(|_| AuthRejection::TokenFormatInvalid)?;
        self.ensure_key(&header.kid)?;
        let key = self
            .keys
            .iter()
            .find(|key| key.kid == header.kid)
            .ok_or(AuthRejection::SigningKeyUnavailable)?;
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
        .map_err(|_| AuthRejection::SignatureInvalid)?;
        Ok(claims_bytes)
    }

    fn validate_claims(&self, claims: &Claims, now: u64) -> AuthResult<OwnerId> {
        if claims.tid != self.tenant_id {
            return Err(AuthRejection::TenantMismatch);
        }
        let owner = OwnerId::new(&claims.tid, &claims.oid)
            .map_err(|_| AuthRejection::ClaimsShapeInvalid)?;
        if self
            .allowed_object_ids
            .as_ref()
            .is_some_and(|allowed| !allowed.contains(&claims.oid.to_ascii_lowercase()))
        {
            return Err(AuthRejection::OwnerNotAllowed);
        }
        if claims.aud != self.audience {
            return Err(AuthRejection::AudienceMismatch);
        }
        if claims.iss != self.authority {
            return Err(AuthRejection::IssuerMismatch);
        }
        if !claims
            .scp
            .split_ascii_whitespace()
            .any(|scope| scope == "access_as_user")
        {
            return Err(AuthRejection::ScopeMissing);
        }
        validate_lifetime(claims.exp, claims.nbf, now)?;
        Ok(owner)
    }

    fn ensure_key(&mut self, kid: &str) -> AuthResult<()> {
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
            return Err(AuthRejection::SigningKeyUnavailable);
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
            .map_err(|_| AuthRejection::SigningKeyUnavailable)?;
        if response.status() != 200 {
            return Err(AuthRejection::SigningKeyUnavailable);
        }
        let mut bytes = Vec::new();
        response
            .into_reader()
            .take(MAX_JWKS_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| AuthRejection::SigningKeyUnavailable)?;
        if bytes.len() as u64 > MAX_JWKS_BYTES {
            return Err(AuthRejection::SigningKeyUnavailable);
        }
        let keys = parse_keys(&bytes).map_err(|_| AuthRejection::SigningKeyUnavailable)?;
        self.keys = keys;
        self.fetched_at = Some(Instant::now());
        if self.keys.iter().any(|key| key.kid == kid) {
            Ok(())
        } else {
            Err(AuthRejection::SigningKeyUnavailable)
        }
    }
}

impl WorkloadEntraVerifier {
    /// Configure a verifier for exactly one application actor and client ID.
    pub fn new(tenant_id: &str, audience: &str, actor_id: &str, client_id: &str) -> Result<Self> {
        if ![tenant_id, audience, actor_id, client_id]
            .iter()
            .all(|value| valid_uuid(value))
        {
            return Err(Error::Configuration(
                "Continuity tenant, audience, actor and client IDs must be nonzero UUIDs",
            ));
        }
        Ok(Self {
            verifier: EntraVerifier::configured(tenant_id, audience, None)?,
            actor_id: actor_id.to_ascii_lowercase(),
            client_id: client_id.to_ascii_lowercase(),
        })
    }

    #[cfg(test)]
    pub(crate) fn with_test_jwks(mut self, jwks: &[u8]) -> Result<Self> {
        self.verifier.keys = parse_keys(jwks)?;
        self.verifier.fetched_at = Some(Instant::now());
        self.verifier.last_attempt = Some(Instant::now());
        Ok(self)
    }

    /// Authenticate and authorize a bounded application JWT without deriving a user owner.
    pub(crate) fn verify_diagnostic(&mut self, token: &str) -> AuthResult<()> {
        let claims_bytes = self.verifier.verify_signed_claims(token)?;
        let value: serde_json::Value =
            serde_json::from_slice(&claims_bytes).map_err(|_| AuthRejection::ClaimsShapeInvalid)?;
        self.validate_claims_value(value, unix_time()?)
    }

    fn validate_claims_value(&self, value: serde_json::Value, now: u64) -> AuthResult<()> {
        let object = value.as_object().ok_or(AuthRejection::ClaimsShapeInvalid)?;
        if object.contains_key("scp") {
            return Err(AuthRejection::DelegatedScopePresent);
        }
        for (name, expected, rejection) in [
            (
                "appid",
                self.client_id.as_str(),
                AuthRejection::ClientMismatch,
            ),
            ("idtyp", "app", AuthRejection::TokenTypeInvalid),
        ] {
            if let Some(actual) = object.get(name) {
                if actual.as_str() != Some(expected) {
                    return Err(rejection);
                }
            }
        }
        let claims: WorkloadClaims =
            serde_json::from_value(value).map_err(|_| AuthRejection::ClaimsShapeInvalid)?;
        self.validate_claims(&claims, now)
    }

    fn validate_claims(&self, claims: &WorkloadClaims, now: u64) -> AuthResult<()> {
        if claims.tid != self.verifier.tenant_id {
            return Err(AuthRejection::TenantMismatch);
        }
        if !valid_uuid(&claims.oid) || !claims.oid.eq_ignore_ascii_case(self.actor_id.as_str()) {
            return Err(AuthRejection::ActorMismatch);
        }
        if claims.aud != self.verifier.audience {
            return Err(AuthRejection::AudienceMismatch);
        }
        if claims.iss != self.verifier.authority {
            return Err(AuthRejection::IssuerMismatch);
        }
        let client_id = claims
            .azp
            .as_deref()
            .or(claims.appid.as_deref())
            .ok_or(AuthRejection::ClientMismatch)?;
        if !valid_uuid(client_id) || !client_id.eq_ignore_ascii_case(self.client_id.as_str()) {
            return Err(AuthRejection::ClientMismatch);
        }
        if claims.roles.as_slice() != ["Continuity.Access"] {
            return Err(AuthRejection::RoleMismatch);
        }
        if claims.ver != "2.0" {
            return Err(AuthRejection::VersionMismatch);
        }
        validate_lifetime(claims.exp, claims.nbf, now)
    }
}

fn unix_time() -> AuthResult<u64> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| AuthRejection::LifetimeInvalid)
        .map(|duration| duration.as_secs())
}

fn validate_lifetime(exp: u64, nbf: u64, now: u64) -> AuthResult<()> {
    if exp <= now.saturating_sub(CLOCK_LEEWAY)
        || nbf > now.saturating_add(CLOCK_LEEWAY)
        || nbf >= exp
    {
        return Err(AuthRejection::LifetimeInvalid);
    }
    Ok(())
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

    fn valid_claims(verifier: &EntraVerifier) -> serde_json::Value {
        json!({
            "tid":TENANT,"oid":OWNER,"aud":APP,"iss":verifier.authority(),
            "exp":1100,"nbf":900,"scp":"other access_as_user"
        })
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
    fn rejection_labels_are_fixed_and_public_verify_stays_generic() {
        let labels = [
            (AuthRejection::TokenFormatInvalid, "token_format_invalid"),
            (AuthRejection::HeaderRejected, "header_rejected"),
            (
                AuthRejection::SigningKeyUnavailable,
                "signing_key_unavailable",
            ),
            (AuthRejection::SignatureInvalid, "signature_invalid"),
            (AuthRejection::ClaimsShapeInvalid, "claims_shape_invalid"),
            (AuthRejection::TenantMismatch, "tenant_mismatch"),
            (AuthRejection::OwnerNotAllowed, "owner_not_allowed"),
            (AuthRejection::AudienceMismatch, "audience_mismatch"),
            (AuthRejection::IssuerMismatch, "issuer_mismatch"),
            (AuthRejection::ScopeMissing, "scope_missing"),
            (
                AuthRejection::DelegatedScopePresent,
                "delegated_scope_present",
            ),
            (AuthRejection::ActorMismatch, "actor_mismatch"),
            (AuthRejection::ClientMismatch, "client_mismatch"),
            (AuthRejection::RoleMismatch, "role_mismatch"),
            (AuthRejection::VersionMismatch, "version_mismatch"),
            (AuthRejection::TokenTypeInvalid, "token_type_invalid"),
            (AuthRejection::LifetimeInvalid, "lifetime_invalid"),
        ];
        for (rejection, label) in labels {
            assert_eq!(rejection.label(), label);
        }

        let mut verifier = verifier();
        assert_eq!(
            verifier.verify_diagnostic("not-a-token"),
            Err(AuthRejection::TokenFormatInvalid)
        );
        assert_eq!(verifier.verify("not-a-token"), Err(Error::Unauthorized));
    }

    #[test]
    fn token_header_key_and_signature_rejections_are_distinct() {
        let mut verifier = verifier();
        let signature = URL_SAFE_NO_PAD.encode([0; 256]);
        let invalid_header = URL_SAFE_NO_PAD.encode(br#"{"alg":"none","kid":"test"}"#);
        assert_eq!(
            verifier.verify_diagnostic(&format!("{invalid_header}.e30.{signature}")),
            Err(AuthRejection::HeaderRejected)
        );

        let header = URL_SAFE_NO_PAD.encode(br#"{"alg":"RS256","kid":"test"}"#);
        verifier.last_attempt = Some(Instant::now());
        assert_eq!(
            verifier.verify_diagnostic(&format!("{header}.e30.{signature}")),
            Err(AuthRejection::SigningKeyUnavailable)
        );

        verifier.keys = parse_keys(
            &serde_json::to_vec(&json!({"keys":[{
                "kid":"test","kty":"RSA","alg":"RS256","use":"sig",
                "n":URL_SAFE_NO_PAD.encode([0xff;256]),"e":"AQAB"
            }]}))
            .unwrap(),
        )
        .unwrap();
        verifier.fetched_at = Some(Instant::now());
        assert_eq!(
            verifier.verify_diagnostic(&format!("{header}.e30.{signature}")),
            Err(AuthRejection::SignatureInvalid)
        );
    }

    #[test]
    fn claims_require_exact_owner_audience_issuer_and_scope() {
        let verifier = verifier();
        let valid = valid_claims(&verifier);
        let claims: Claims = serde_json::from_value(valid.clone()).unwrap();
        assert!(verifier.validate_claims(&claims, 1000).is_ok());
        for (field, value, expected) in [
            ("tid", json!(APP), AuthRejection::TenantMismatch),
            ("oid", json!(APP), AuthRejection::OwnerNotAllowed),
            ("aud", json!(TENANT), AuthRejection::AudienceMismatch),
            (
                "iss",
                json!("https://attacker.example/v2.0"),
                AuthRejection::IssuerMismatch,
            ),
            (
                "scp",
                json!("access_as_user_extra"),
                AuthRejection::ScopeMissing,
            ),
            ("exp", json!(970), AuthRejection::LifetimeInvalid),
            ("nbf", json!(1031), AuthRejection::LifetimeInvalid),
        ] {
            let mut invalid = valid.clone();
            invalid[field] = value;
            let claims = serde_json::from_value(invalid).unwrap();
            assert_eq!(
                verifier.validate_claims(&claims, 1000),
                Err(expected),
                "{field}"
            );
        }

        for field in ["tid", "oid", "aud", "iss", "exp", "nbf", "scp"] {
            let mut invalid = valid.clone();
            invalid.as_object_mut().unwrap().remove(field);
            assert!(serde_json::from_value::<Claims>(invalid).is_err());
        }

        let tenant_verifier = EntraVerifier::for_tenant_users(TENANT, APP).unwrap();
        let mut malformed_owner = valid;
        malformed_owner["oid"] = json!("not-an-object-id");
        let claims = serde_json::from_value(malformed_owner).unwrap();
        assert_eq!(
            tenant_verifier.validate_claims(&claims, 1000),
            Err(AuthRejection::ClaimsShapeInvalid)
        );
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
    fn explicit_user_mode_rejects_other_users_in_the_same_tenant() {
        let allowed = vec![
            OWNER.to_owned(),
            "dddddddd-dddd-dddd-dddd-dddddddddddd".to_owned(),
        ];
        let verifier = EntraVerifier::for_users(TENANT, APP, &allowed).unwrap();
        for (owner, accepted) in [
            (OWNER, true),
            ("dddddddd-dddd-dddd-dddd-dddddddddddd", true),
            ("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee", false),
        ] {
            let claims: Claims = serde_json::from_value(json!({
                "tid":TENANT,"oid":owner,"aud":APP,"iss":verifier.authority(),
                "exp":1100,"nbf":900,"scp":"access_as_user"
            }))
            .unwrap();
            assert_eq!(verifier.validate_claims(&claims, 1000).is_ok(), accepted);
        }
    }

    #[test]
    fn owner_allowlist_matching_is_case_insensitive_and_returns_canonical_owner() {
        let uppercase_owner = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC";
        let verifier = EntraVerifier::new(TENANT, APP, OWNER).unwrap();
        let uppercase_claim: Claims = serde_json::from_value(json!({
            "tid":TENANT,"oid":uppercase_owner,"aud":APP,"iss":verifier.authority(),
            "exp":1100,"nbf":900,"scp":"access_as_user"
        }))
        .unwrap();
        let owner = verifier.validate_claims(&uppercase_claim, 1000).unwrap();
        assert_eq!(owner.as_str(), format!("{TENANT}:{OWNER}"));

        let verifier =
            EntraVerifier::for_users(TENANT, APP, &[uppercase_owner.to_owned()]).unwrap();
        let lowercase_claim: Claims = serde_json::from_value(json!({
            "tid":TENANT,"oid":OWNER,"aud":APP,"iss":verifier.authority(),
            "exp":1100,"nbf":900,"scp":"access_as_user"
        }))
        .unwrap();
        let owner = verifier.validate_claims(&lowercase_claim, 1000).unwrap();
        assert_eq!(owner.as_str(), format!("{TENANT}:{OWNER}"));

        let different_claim: Claims = serde_json::from_value(json!({
            "tid":TENANT,"oid":"dddddddd-dddd-dddd-dddd-dddddddddddd","aud":APP,
            "iss":verifier.authority(),"exp":1100,"nbf":900,"scp":"access_as_user"
        }))
        .unwrap();
        assert_eq!(
            verifier.validate_claims(&different_claim, 1000),
            Err(AuthRejection::OwnerNotAllowed)
        );
    }

    #[test]
    fn delegated_scope_is_fully_qualified_for_oauth_clients() {
        assert_eq!(
            verifier().delegated_scope(),
            format!("api://{APP}/access_as_user")
        );
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
        assert_eq!(
            verifier.verify_diagnostic(&format!("{header}.e30.{signature}")),
            Err(AuthRejection::SignatureInvalid)
        );
        assert_eq!(
            verifier.verify(&format!("{header}.e30.{signature}")),
            Err(Error::Unauthorized)
        );
        assert!(verifier.ensure_key("unknown").is_err());
        verifier.fetched_at = Some(Instant::now() - CACHE_LIFETIME);
        assert!(verifier.ensure_key("test").is_err());
    }

    fn workload_verifier() -> WorkloadEntraVerifier {
        WorkloadEntraVerifier::new(TENANT, APP, OWNER, APP).unwrap()
    }

    fn valid_workload_claims(verifier: &WorkloadEntraVerifier) -> serde_json::Value {
        json!({
            "tid":TENANT,"oid":OWNER,"aud":APP,"iss":verifier.verifier.authority(),
            "exp":1100,"nbf":900,"azp":APP,"roles":["Continuity.Access"],
            "ver":"2.0","idtyp":"app","appid":APP
        })
    }

    #[test]
    fn workload_config_is_strict_and_valid_claims_are_accepted() {
        assert!(WorkloadEntraVerifier::new("common", APP, OWNER, APP).is_err());
        assert!(WorkloadEntraVerifier::new(TENANT, APP, "not-an-oid", APP).is_err());
        let verifier = workload_verifier();
        assert!(verifier
            .validate_claims_value(valid_workload_claims(&verifier), 1000)
            .is_ok());

        let mut appid_only = valid_workload_claims(&verifier);
        appid_only.as_object_mut().unwrap().remove("azp");
        assert!(verifier.validate_claims_value(appid_only, 1000).is_ok());

        let mut missing_client = valid_workload_claims(&verifier);
        missing_client.as_object_mut().unwrap().remove("azp");
        missing_client.as_object_mut().unwrap().remove("appid");
        assert_eq!(
            verifier.validate_claims_value(missing_client, 1000),
            Err(AuthRejection::ClientMismatch)
        );
    }

    #[test]
    fn workload_claim_policy_rejects_wrong_identity_role_version_and_lifetime() {
        let verifier = workload_verifier();
        let valid = valid_workload_claims(&verifier);
        for (field, value, expected) in [
            ("tid", json!(APP), AuthRejection::TenantMismatch),
            ("oid", json!(APP), AuthRejection::ActorMismatch),
            ("aud", json!(TENANT), AuthRejection::AudienceMismatch),
            (
                "iss",
                json!("https://attacker.example/v2.0"),
                AuthRejection::IssuerMismatch,
            ),
            ("azp", json!(TENANT), AuthRejection::ClientMismatch),
            ("roles", json!([]), AuthRejection::RoleMismatch),
            (
                "roles",
                json!(["Continuity.Access", "Other"]),
                AuthRejection::RoleMismatch,
            ),
            ("roles", json!(["Other"]), AuthRejection::RoleMismatch),
            ("ver", json!("1.0"), AuthRejection::VersionMismatch),
            ("appid", json!(TENANT), AuthRejection::ClientMismatch),
            ("idtyp", json!("user"), AuthRejection::TokenTypeInvalid),
            ("exp", json!(970), AuthRejection::LifetimeInvalid),
            ("nbf", json!(1031), AuthRejection::LifetimeInvalid),
        ] {
            let mut invalid = valid.clone();
            invalid[field] = value;
            assert_eq!(
                verifier.validate_claims_value(invalid, 1000),
                Err(expected),
                "{field}"
            );
        }

        for field in ["tid", "oid", "aud", "iss", "roles", "ver", "exp", "nbf"] {
            let mut invalid = valid.clone();
            invalid.as_object_mut().unwrap().remove(field);
            assert_eq!(
                verifier.validate_claims_value(invalid, 1000),
                Err(AuthRejection::ClaimsShapeInvalid),
                "{field}"
            );
        }
    }

    #[test]
    fn workload_optional_claims_are_strict_and_delegated_scope_is_forbidden() {
        let verifier = workload_verifier();
        for optional in ["appid", "idtyp"] {
            let mut claims = valid_workload_claims(&verifier);
            claims.as_object_mut().unwrap().remove(optional);
            assert!(
                verifier.validate_claims_value(claims, 1000).is_ok(),
                "{optional}"
            );
        }
        for value in [json!("access_as_user"), serde_json::Value::Null] {
            let mut claims = valid_workload_claims(&verifier);
            claims["scp"] = value;
            assert_eq!(
                verifier.validate_claims_value(claims, 1000),
                Err(AuthRejection::DelegatedScopePresent)
            );
        }
        for (field, value, expected) in [
            (
                "appid",
                serde_json::Value::Null,
                AuthRejection::ClientMismatch,
            ),
            (
                "idtyp",
                serde_json::Value::Null,
                AuthRejection::TokenTypeInvalid,
            ),
        ] {
            let mut claims = valid_workload_claims(&verifier);
            claims[field] = value;
            assert_eq!(verifier.validate_claims_value(claims, 1000), Err(expected));
        }
    }
}
