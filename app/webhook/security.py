import hmac
import hashlib
from typing import Optional


def validate_webhook_signature(
    secret: str, request_body: bytes, signature_header: Optional[str]
) -> bool:
    """
    Validate HMAC-SHA256 signature using constant-time comparison.
    
    Args:
        secret: The webhook secret
        request_body: Raw request body bytes
        signature_header: The X-Hook-Signature header value
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not signature_header:
        return False

    # Compute expected signature
    expected_signature = hmac.new(
        secret.encode(), request_body, hashlib.sha256
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature_header)
