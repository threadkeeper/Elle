//! Stateless, authenticated JSON MCP over HTTP behind a trusted TLS ingress.
//!
//! This listener is not HTTPS. Deploy behind Azure Container Apps HTTPS ingress
//! with request timeouts and rate limits; tiny_http does not expose per-request
//! socket deadlines. No export or restore routes are provided.

use std::io::Read;
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::{json, Value};
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};
use zeroize::Zeroizing;

use crate::auth::EntraVerifier;
use crate::error::{Error, Result};
use crate::mcp;
use crate::service::MemoryService;

static REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(1);

/// Serve a single-owner, sequential JSON MCP endpoint until the listener fails.
///
/// `address` is the internal HTTP bind address, such as `0.0.0.0:8080`.
/// `public_origin` must be the external HTTPS origin without a path.
pub fn serve(
    address: &str,
    public_origin: &str,
    mut verifier: EntraVerifier,
    mut service: MemoryService,
    role: mcp::ServerRole,
) -> Result<()> {
    let origin = validate_origin(public_origin)?;
    let metadata_url = format!("{origin}/.well-known/oauth-protected-resource");
    let challenge = format!("Bearer resource_metadata=\"{metadata_url}\"");
    let challenge_header = header("WWW-Authenticate", &challenge)?;
    let metadata = json!({
        "resource":format!("{origin}/mcp"),
        "authorization_servers":[verifier.authority()],
        "scopes_supported":["access_as_user"],
        "bearer_methods_supported":["header"]
    })
    .to_string();
    let server =
        Server::http(address).map_err(|_| Error::Transport("Cannot bind the HTTP listener"))?;
    loop {
        let request = server
            .recv()
            .map_err(|_| Error::Transport("HTTP listener failed"))?;
        // A disconnected caller must not terminate the shared listener.
        if handle_request(
            request,
            &origin,
            &metadata,
            &challenge_header,
            &mut verifier,
            &mut service,
            role,
        )
        .is_err()
        {
            eprintln!("Elle: HTTP request failed");
        }
    }
}

fn handle_request(
    mut request: Request,
    origin: &str,
    metadata: &str,
    challenge: &Header,
    verifier: &mut EntraVerifier,
    service: &mut MemoryService,
    role: mcp::ServerRole,
) -> Result<()> {
    let request_id = REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let method = format!("{:?}", request.method());
    let path = request.url().split('?').next().unwrap_or("");
    eprintln!(
        "Elle diagnostic: request_id={request_id} role={} method={method} path={path} event=request_started",
        role.name()
    );
    match single_header(&request, "Origin") {
        Ok(None) => {}
        Ok(Some(value)) if value == origin => {}
        _ => {
            eprintln!(
                "Elle diagnostic: request_id={request_id} role={} status=403 error=forbidden_origin",
                role.name()
            );
            return reply(request, 403, r#"{"error":"Forbidden origin"}"#, None);
        }
    }
    match (request.method(), request.url()) {
        (&Method::Get, "/healthz") => {
            return reply(request, 200, r#"{"status":"ok"}"#, None);
        }
        (&Method::Get, "/.well-known/oauth-protected-resource") => {
            return reply(request, 200, metadata, None);
        }
        (&Method::Get, "/mcp") => {
            return reply(
                request,
                405,
                r#"{"error":"JSON POST required; SSE is not available"}"#,
                Some(header("Allow", "POST")?),
            );
        }
        (&Method::Post, "/mcp") => {}
        _ => return reply(request, 404, r#"{"error":"Not found"}"#, None),
    }

    let token = match single_header(&request, "Authorization") {
        Ok(Some(value)) => match bearer(value) {
            Some(token) => token,
            None => {
                eprintln!(
                    "Elle diagnostic: request_id={request_id} role={} status=401 error=malformed_bearer",
                    role.name()
                );
                return reply(
                    request,
                    401,
                    r#"{"error":"Unauthorized"}"#,
                    Some(challenge.clone()),
                );
            }
        },
        _ => {
            eprintln!(
                "Elle diagnostic: request_id={request_id} role={} status=401 error=missing_authorization",
                role.name()
            );
            return reply(
                request,
                401,
                r#"{"error":"Unauthorized"}"#,
                Some(challenge.clone()),
            );
        }
    };
    let owner = match verifier.verify(token) {
        Ok(owner) => owner,
        Err(error) => {
            eprintln!(
                "Elle diagnostic: request_id={request_id} role={} status=401 error=token_rejected detail={}",
                role.name(),
                log_value(&error.to_string())
            );
            return reply(
                request,
                401,
                r#"{"error":"Unauthorized"}"#,
                Some(challenge.clone()),
            );
        }
    };
    if !matches!(
        single_header(&request, "Content-Type"),
        Ok(Some(value)) if is_json(value)
    ) {
        return reply(
            request,
            415,
            r#"{"error":"JSON content type required"}"#,
            None,
        );
    }
    if !matches!(single_header(&request, "Accept"), Ok(None) | Ok(Some("")))
        && !matches!(
            single_header(&request, "Accept"),
            Ok(Some(value)) if accepts_json(value)
        )
    {
        return reply(request, 406, r#"{"error":"JSON response required"}"#, None);
    }
    // Explicit framing keeps the accepted body bounded and rejects chunked uploads.
    let length = match single_header(&request, "Content-Length") {
        Ok(Some(value)) if !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit()) => {
            match value.parse::<usize>() {
                Ok(length) => length,
                Err(_) => return reply(request, 413, r#"{"error":"Request too large"}"#, None),
            }
        }
        _ => return reply(request, 411, r#"{"error":"Content-Length required"}"#, None),
    };
    if single_header(&request, "Transfer-Encoding") != Ok(None) {
        return reply(
            request,
            400,
            r#"{"error":"Unsupported request framing"}"#,
            None,
        );
    }
    if length > mcp::MAX_MESSAGE_BYTES {
        return reply(request, 413, r#"{"error":"Request too large"}"#, None);
    }
    let mut body = Zeroizing::new(Vec::new());
    if request
        .as_reader()
        .take(mcp::MAX_MESSAGE_BYTES as u64 + 1)
        .read_to_end(&mut body)
        .is_err()
        || body.len() != length
    {
        return reply(request, 400, r#"{"error":"Invalid request body"}"#, None);
    }
    if body.len() > mcp::MAX_MESSAGE_BYTES {
        return reply(request, 413, r#"{"error":"Request too large"}"#, None);
    }
    let (rpc_method, tool_name) = request_summary(&body);
    match mcp::handle_for_role(&body, &owner, service, role) {
        Some(response) => {
            let error = response_error(&response);
            eprintln!(
                "Elle diagnostic: request_id={request_id} role={} rpc_method={} tool={} status=200 result={}{}",
                role.name(),
                rpc_method,
                tool_name,
                if error.is_some() { "error" } else { "ok" },
                error
                    .map(|detail| format!(" detail={detail}"))
                    .unwrap_or_default()
            );
            reply(request, 200, &response.to_string(), None)
        }
        None => {
            eprintln!(
                "Elle diagnostic: request_id={request_id} role={} rpc_method={} tool={} status=202 result=notification_accepted",
                role.name(),
                rpc_method,
                tool_name
            );
            reply(request, 202, "", None)
        }
    }
}

fn request_summary(body: &[u8]) -> (String, String) {
    let Ok(value) = serde_json::from_slice::<Value>(body) else {
        return ("invalid_json".to_owned(), "none".to_owned());
    };
    let method = value
        .get("method")
        .and_then(Value::as_str)
        .map(log_value)
        .unwrap_or_else(|| "missing".to_owned());
    let tool = value
        .pointer("/params/name")
        .and_then(Value::as_str)
        .map(log_value)
        .unwrap_or_else(|| "none".to_owned());
    (method, tool)
}

fn response_error(response: &Value) -> Option<String> {
    if let Some(error) = response.pointer("/error/message").and_then(Value::as_str) {
        return Some(log_value(error));
    }
    if response.pointer("/result/isError").and_then(Value::as_bool) != Some(true) {
        return None;
    }
    let text = response
        .pointer("/result/content/0/text")
        .and_then(Value::as_str)?;
    let detail = serde_json::from_str::<Value>(text)
        .ok()
        .and_then(|value| value.get("error").and_then(Value::as_str).map(log_value));
    Some(detail.unwrap_or_else(|| "tool_error".to_owned()))
}

fn log_value(value: &str) -> String {
    let sanitized = value
        .chars()
        .take(160)
        .map(|character| {
            if character.is_ascii_alphanumeric()
                || matches!(character, '_' | '-' | '/' | '.' | ':' | ' ')
            {
                character
            } else {
                '_'
            }
        })
        .collect::<String>();
    if sanitized.is_empty() {
        "unspecified".to_owned()
    } else {
        sanitized
    }
}

fn header(name: &str, value: &str) -> Result<Header> {
    Header::from_bytes(name.as_bytes(), value.as_bytes())
        .map_err(|_| Error::Configuration("Invalid HTTP response header"))
}

fn reply(request: Request, status: u16, body: &str, extra: Option<Header>) -> Result<()> {
    let mut response = Response::from_string(body)
        .with_status_code(StatusCode(status))
        .with_header(header("Content-Type", "application/json")?)
        .with_header(header("Cache-Control", "no-store")?)
        .with_header(header("X-Content-Type-Options", "nosniff")?);
    if let Some(extra) = extra {
        response.add_header(extra);
    }
    request
        .respond(response)
        .map_err(|_| Error::Transport("Cannot send the HTTP response"))
}

fn single_header<'a>(request: &'a Request, name: &str) -> Result<Option<&'a str>> {
    let mut matches = request
        .headers()
        .iter()
        .filter(|header| header.field.as_str().as_str().eq_ignore_ascii_case(name));
    let value = matches.next().map(|header| header.value.as_str());
    if matches.next().is_some() {
        return Err(Error::InvalidInput("Duplicate request header"));
    }
    Ok(value)
}

fn bearer(value: &str) -> Option<&str> {
    let (scheme, token) = value.split_once(' ')?;
    if !scheme.eq_ignore_ascii_case("Bearer")
        || token.is_empty()
        || token.bytes().any(|byte| byte.is_ascii_whitespace())
    {
        return None;
    }
    Some(token)
}

fn is_json(value: &str) -> bool {
    value
        .split(';')
        .next()
        .is_some_and(|media| media.trim().eq_ignore_ascii_case("application/json"))
}

fn accepts_json(value: &str) -> bool {
    value.split(',').any(|range| {
        let mut parts = range.trim().split(';');
        let media = parts.next().unwrap_or("").trim();
        let mut quality = 1.0_f32;
        for parameter in parts {
            if let Some((name, value)) = parameter.trim().split_once('=') {
                if name.trim().eq_ignore_ascii_case("q") {
                    quality = value.trim().parse::<f32>().unwrap_or(0.0);
                }
            }
        }
        (media.eq_ignore_ascii_case("application/json")
            || media.eq_ignore_ascii_case("application/*")
            || media == "*/*")
            && quality > 0.0
            && quality <= 1.0
    })
}

fn validate_origin(value: &str) -> Result<String> {
    let origin = value.strip_suffix('/').unwrap_or(value);
    let host = origin
        .strip_prefix("https://")
        .ok_or(Error::Configuration("Public origin must use HTTPS"))?;
    if origin.len() > 2048
        || host.is_empty()
        || !host
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b':'))
    {
        return Err(Error::Configuration(
            "Public origin must contain only an HTTPS hostname and optional port",
        ));
    }
    let mut pieces = host.split(':');
    let hostname = pieces.next().unwrap_or("");
    if hostname.is_empty()
        || hostname.split('.').any(|label| {
            label.is_empty() || label.len() > 63 || label.starts_with('-') || label.ends_with('-')
        })
        || pieces
            .next()
            .is_some_and(|port| port.parse::<u16>().map_or(true, |port| port == 0))
        || pieces.next().is_some()
    {
        return Err(Error::Configuration(
            "Public origin hostname or port is invalid",
        ));
    }
    Ok(origin.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_origin_cannot_inject_headers_or_urls() {
        assert_eq!(
            validate_origin("https://elle.example.com/").unwrap(),
            "https://elle.example.com"
        );
        assert!(validate_origin("https://localhost:8443").is_ok());
        for value in [
            "http://elle.example.com",
            "https://elle.example.com/mcp",
            "https://user@elle.example.com",
            "https://elle.example.com?query",
            "https://elle.example.com#fragment",
            "https://elle.example.com\"\r\nInjected: yes",
            "https://",
            "https://elle.example.com:0",
            "https://elle.example.com:65536",
        ] {
            assert!(validate_origin(value).is_err(), "{value}");
        }
    }

    #[test]
    fn request_media_and_bearer_are_checked() {
        assert!(is_json("application/json; charset=utf-8"));
        assert!(!is_json("text/plain"));
        assert!(accepts_json("application/json, text/event-stream"));
        assert!(accepts_json("*/*"));
        assert!(!accepts_json("text/event-stream"));
        assert!(!accepts_json("application/json;q=0"));
        assert!(!accepts_json("application/json;q=NaN"));
        assert_eq!(bearer("Bearer a.b.c"), Some("a.b.c"));
        assert_eq!(bearer("bearer a.b.c"), Some("a.b.c"));
        assert_eq!(bearer("Basic a.b.c"), None);
        assert_eq!(bearer("Bearer a.b.c extra"), None);
        assert_eq!(bearer("Bearer "), None);
    }
}
