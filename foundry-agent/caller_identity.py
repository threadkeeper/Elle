import hashlib
import logging
import os
import re

from azure.ai.agentserver.core import get_request_context


logger = logging.getLogger(__name__)
_PROBE_NONCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


def validate_identity_binding_probe_nonce(nonce: str | None) -> str | None:
    if nonce is None:
        return None
    if not _PROBE_NONCE_PATTERN.fullmatch(nonce):
        raise ValueError(
            "ELLE_IDENTITY_BINDING_PROBE_NONCE must be 1 to 64 safe ASCII characters"
        )
    return nonce


def elle_identity_status() -> dict[str, str]:
    """Report whether this request has a stable platform caller identity."""
    user_id = get_request_context().user_id
    if not user_id:
        return {"identity": "unavailable", "binding": "unavailable"}
    nonce = validate_identity_binding_probe_nonce(
        os.environ.get("ELLE_IDENTITY_BINDING_PROBE_NONCE")
    )
    if nonce is not None:
        handle = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
        logger.warning(
            "TEMPORARY operator identity binding probe: nonce=%s handle_sha256=%s",
            nonce,
            handle,
        )
    return {"identity": "present", "binding": "unbound"}