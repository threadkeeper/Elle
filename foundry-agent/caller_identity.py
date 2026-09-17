import hashlib
import logging

from azure.ai.agentserver.core import get_request_context


logger = logging.getLogger(__name__)


def elle_identity_status() -> dict[str, str]:
    """Report whether this request has a stable platform caller identity."""
    user_id = get_request_context().user_id
    if not user_id:
        return {"identity": "unavailable", "binding": "unavailable"}
    fingerprint = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16]
    logger.info("Elle identity probe: fingerprint=%s", fingerprint)
    return {"identity": "present", "binding": "unbound"}