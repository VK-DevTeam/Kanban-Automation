# Coding Prompt: Security Vulnerabilities

**Category**: Security  
**Priority**: Critical  
**Files Affected**: `app/webhook/router.py`, `app/webhook/security.py`, `app/worker/asana_client.py`, `app/worker/trello_client.py`, `app/worker/attachments.py`

## Issue Description
Multiple security vulnerabilities exist in the codebase that could lead to credential exposure, resource exhaustion, and potential attacks. These issues require immediate attention to ensure production security.

## Current Security Issues
1. **Credential Exposure**: API tokens potentially logged in error messages
2. **Resource Exhaustion**: No request size limits for webhook payloads and attachments
3. **Rate Limiting**: Missing rate limiting on webhook endpoints
4. **Input Validation**: Insufficient validation of user-provided data
5. **Information Disclosure**: Detailed error messages in API responses

## Target Implementation

### 1. Fix Credential Exposure in API Clients

**File**: `app/worker/asana_client.py` (Lines 45-65)
**Current Code**:
```python
async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.BASE_URL}/tasks/{task_gid}",
                headers=self._get_headers(),
                # ... rest of implementation
            )
    except Exception as e:
        self.logger.error("Unexpected error fetching task", error=str(e), task_gid=task_gid)
        raise
```

**Target Implementation**:
```python
import re
from typing import Dict, Any, Optional

class SecureLogger:
    """Logger wrapper that sanitizes sensitive information."""
    
    def __init__(self, logger: structlog.BoundLogger) -> None:
        self.logger = logger
        self.sensitive_patterns = [
            (re.compile(r'Bearer\s+[A-Za-z0-9_-]+'), 'Bearer [REDACTED]'),
            (re.compile(r'token["\']?\s*[:=]\s*["\']?[A-Za-z0-9_-]+'), 'token=[REDACTED]'),
            (re.compile(r'key["\']?\s*[:=]\s*["\']?[A-Za-z0-9_-]+'), 'key=[REDACTED]'),
            (re.compile(r'password["\']?\s*[:=]\s*["\']?[^"\s]+'), 'password=[REDACTED]'),
        ]
    
    def _sanitize_message(self, message: str) -> str:
        """Remove sensitive information from log messages."""
        for pattern, replacement in self.sensitive_patterns:
            message = pattern.sub(replacement, message)
        return message
    
    def error(self, message: str, **kwargs) -> None:
        """Log error with sanitized message."""
        sanitized_message = self._sanitize_message(message)
        # Sanitize kwargs as well
        sanitized_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, str):
                sanitized_kwargs[key] = self._sanitize_message(value)
            else:
                sanitized_kwargs[key] = value
        self.logger.error(sanitized_message, **sanitized_kwargs)

class AsanaClient:
    def __init__(self) -> None:
        settings: Settings = get_settings()
        self.access_token: str = settings.asana_access_token
        self.timeout: int = settings.api_timeout_seconds
        self.max_retries: int = settings.max_retry_attempts
        self.logger = SecureLogger(get_logger(__name__))

    async def get_task(self, task_gid: str) -> Optional[Dict[str, Any]]:
        """Fetch task details with secure error handling."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.BASE_URL}/tasks/{task_gid}",
                    headers=self._get_headers(),
                    params={"opt_fields": "name,notes,attachments.name,attachments.download_url,attachments.size,attachments.mime_type"},
                )

                if response.status_code == 401:
                    self.logger.error("Asana authentication failed", status=401, task_gid=task_gid)
                    raise SecurityError("Authentication failed - check credentials")
                elif response.status_code == 403:
                    self.logger.error("Asana access forbidden", status=403, task_gid=task_gid)
                    raise SecurityError("Access forbidden - insufficient permissions")
                # ... rest of implementation

        except httpx.TimeoutException:
            self.logger.error("Asana API timeout", task_gid=task_gid)
            raise
        except httpx.HTTPError as e:
            # Don't log the full exception which might contain sensitive headers
            self.logger.error("Asana API error", status_code=getattr(e.response, 'status_code', None), task_gid=task_gid)
            raise
        except Exception as e:
            # Generic error without exposing internal details
            self.logger.error("Error fetching task", task_gid=task_gid)
            raise ServiceError("Failed to fetch task data")
```

### 2. Implement Request Size Limits and Rate Limiting

**File**: `app/webhook/router.py` (Lines 1-40)
**Current Code**:
```python
from fastapi import APIRouter, Request, HTTPException, status

@router.post("/asana")
async def asana_webhook(request: Request):
    # No size limits or rate limiting
    raw_body = await request.body()
```

**Target Implementation**:
```python
from fastapi import APIRouter, Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import time
from typing import Dict, Any

# Rate limiting setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security configuration
MAX_PAYLOAD_SIZE = 1024 * 1024  # 1MB
MAX_REQUESTS_PER_MINUTE = 60

class PayloadSizeValidator:
    """Validates request payload size."""
    
    def __init__(self, max_size: int = MAX_PAYLOAD_SIZE):
        self.max_size = max_size
    
    async def __call__(self, request: Request) -> Request:
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > self.max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Payload too large. Maximum size: {self.max_size} bytes"
            )
        return request

payload_validator = PayloadSizeValidator()

@router.post("/asana")
@limiter.limit(f"{MAX_REQUESTS_PER_MINUTE}/minute")
async def asana_webhook(
    request: Request,
    validated_request: Request = Depends(payload_validator)
):
    """
    Receive Asana webhook events with security controls.
    
    - Rate limited to prevent abuse
    - Payload size limited to prevent resource exhaustion
    - Validates HMAC-SHA256 signature
    - Handles handshake requests
    - Sanitizes error responses
    """
    settings = get_settings()
    queue = RedisQueue()
    
    try:
        # Get raw body with size validation
        raw_body = await request.body()
        
        # Additional runtime size check
        if len(raw_body) > MAX_PAYLOAD_SIZE:
            logger.warning("Oversized payload rejected", size=len(raw_body))
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Payload too large"
            )

        # Check for handshake request
        hook_secret = request.headers.get("X-Hook-Secret")
        if hook_secret:
            logger.info("Received Asana webhook handshake")
            return {"X-Hook-Secret": hook_secret}

        # Validate signature
        signature = request.headers.get("X-Hook-Signature")
        if not validate_webhook_signature(settings.asana_webhook_secret, raw_body, signature):
            logger.warning(
                "Invalid webhook signature",
                remote_addr=get_remote_address(request),
                user_agent=request.headers.get("user-agent", "unknown")
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature"
            )

        # Parse and validate event structure
        try:
            event = await request.json()
            if not isinstance(event, dict):
                raise ValueError("Event must be a JSON object")
            
            # Basic structure validation
            if "events" not in event or not isinstance(event["events"], list):
                raise ValueError("Invalid event structure")
                
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Invalid webhook payload", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )

        # Enqueue event
        if not queue.enqueue(event):
            logger.error("Failed to enqueue event", event_id=event.get("id"))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process event"
            )

        return {"status": "received"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error in webhook handler", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
```

### 3. Secure Attachment Processing

**File**: `app/worker/attachments.py` (Lines 80-120)
**Current Code**:
```python
async def _download_attachment(self, download_url: str) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=self.attachment_timeout) as client:
            response = await client.get(download_url, follow_redirects=True)
            response.raise_for_status()
            return response.content
```

**Target Implementation**:
```python
import mimetypes
from urllib.parse import urlparse
from typing import Set

class SecureAttachmentProcessor:
    """Secure attachment processor with validation and limits."""
    
    # Security limits
    MAX_ATTACHMENT_SIZE = 250 * 1024 * 1024  # 250MB
    MAX_DOWNLOAD_TIME = 300  # 5 minutes
    ALLOWED_DOMAINS = {"files.asana.com", "s3.amazonaws.com"}  # Whitelist
    BLOCKED_MIME_TYPES = {
        "application/x-executable",
        "application/x-msdownload", 
        "application/x-msdos-program",
        "application/x-sh",
        "text/x-shellscript"
    }
    
    def __init__(self, is_premium: bool = False):
        settings = get_settings()
        self.attachment_timeout = min(settings.attachment_timeout_seconds, self.MAX_DOWNLOAD_TIME)
        self.trello_client = TrelloClient()
        self.logger = SecureLogger(get_logger(__name__))
        self.size_limit = min(
            self.TRELLO_PREMIUM_LIMIT if is_premium else self.TRELLO_FREE_LIMIT,
            self.MAX_ATTACHMENT_SIZE
        )

    def _validate_download_url(self, url: str) -> bool:
        """Validate download URL for security."""
        try:
            parsed = urlparse(url)
            
            # Check protocol
            if parsed.scheme not in ('https',):
                self.logger.warning("Insecure protocol in download URL", scheme=parsed.scheme)
                return False
            
            # Check domain whitelist
            if parsed.netloc not in self.ALLOWED_DOMAINS:
                self.logger.warning("Untrusted domain in download URL", domain=parsed.netloc)
                return False
            
            return True
            
        except Exception as e:
            self.logger.error("Error validating download URL", error=str(e))
            return False

    def _validate_mime_type(self, mime_type: str, filename: str) -> bool:
        """Validate MIME type for security."""
        # Check blocked MIME types
        if mime_type in self.BLOCKED_MIME_TYPES:
            return False
        
        # Validate MIME type matches file extension
        guessed_type, _ = mimetypes.guess_type(filename)
        if guessed_type and guessed_type != mime_type:
            self.logger.warning(
                "MIME type mismatch",
                declared=mime_type,
                guessed=guessed_type,
                filename=filename
            )
            # Allow but log the mismatch
        
        return True

    async def _download_attachment_securely(self, download_url: str, expected_size: int) -> bytes:
        """Download attachment with security validations."""
        
        # Validate URL
        if not self._validate_download_url(download_url):
            raise SecurityError("Invalid or untrusted download URL")
        
        # Size pre-check
        if expected_size > self.size_limit:
            raise SecurityError(f"Attachment too large: {expected_size} bytes")
        
        try:
            async with httpx.AsyncClient(
                timeout=self.attachment_timeout,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2)
            ) as client:
                
                # Stream download with size validation
                downloaded_size = 0
                content = bytearray()
                
                async with client.stream('GET', download_url, follow_redirects=True) as response:
                    response.raise_for_status()
                    
                    # Validate content-length header
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > self.size_limit:
                        raise SecurityError("Attachment exceeds size limit")
                    
                    # Stream with size monitoring
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        downloaded_size += len(chunk)
                        if downloaded_size > self.size_limit:
                            raise SecurityError("Attachment exceeds size limit during download")
                        content.extend(chunk)
                
                return bytes(content)
                
        except httpx.TimeoutException:
            self.logger.error("Attachment download timeout")
            raise SecurityError("Download timeout")
        except httpx.HTTPError as e:
            self.logger.error("Attachment download failed", status_code=getattr(e.response, 'status_code', None))
            raise SecurityError("Download failed")

    async def _process_single_attachment(
        self,
        attachment: Dict[str, Any],
        card_id: str,
        task_gid: str,
    ) -> Dict[str, Any]:
        """Process single attachment with security validations."""
        filename = attachment.get("name", "attachment")
        size = attachment.get("size", 0)
        download_url = attachment.get("download_url")
        mime_type = attachment.get("mime_type", "application/octet-stream")

        # Security validations
        if not self._validate_mime_type(mime_type, filename):
            self.logger.warning("Blocked MIME type", mime_type=mime_type, filename=filename)
            return {"status": "blocked", "filename": filename}

        # Size validation
        if size > self.size_limit:
            self.logger.warning("Attachment exceeds size limit", filename=filename, size=size)
            return {"status": "oversized", "filename": filename}

        if not download_url:
            self.logger.warning("Missing download URL", filename=filename)
            return {"status": "failed", "filename": filename}

        try:
            # Secure download
            file_bytes = await self._download_attachment_securely(download_url, size)
            
            # Upload to Trello
            await self.trello_client.upload_attachment(card_id, filename, file_bytes, mime_type)
            
            self.logger.info("Attachment processed securely", filename=filename, task_gid=task_gid)
            return {"status": "success", "filename": filename}

        except SecurityError as e:
            self.logger.warning("Security validation failed", error=str(e), filename=filename)
            return {"status": "blocked", "filename": filename}
        except Exception as e:
            self.logger.error("Failed to process attachment", filename=filename, task_gid=task_gid)
            return {"status": "failed", "filename": filename}
```

### 4. Add Custom Security Exceptions

**File**: `app/exceptions.py` (New File)
**Target Implementation**:
```python
"""Custom security and application exceptions."""

class SecurityError(Exception):
    """Raised when security validation fails."""
    pass

class ServiceError(Exception):
    """Raised when external service calls fail."""
    pass

class ValidationError(Exception):
    """Raised when input validation fails."""
    pass
```

## Implementation Instructions

1. **Install Security Dependencies**:
   ```bash
   pip install slowapi python-multipart
   ```

2. **Create Security Configuration**: Add security settings to config.py
3. **Implement Secure Logging**: Create logger wrapper that sanitizes sensitive data
4. **Add Rate Limiting**: Implement rate limiting middleware for webhook endpoints
5. **Validate Input**: Add comprehensive input validation for all user data
6. **Secure File Processing**: Implement secure attachment download with validation
7. **Add Security Headers**: Implement security headers middleware
8. **Create Security Tests**: Add tests for security validations

## Success Criteria
- [ ] No credentials exposed in logs or error messages
- [ ] Request size limits enforced on all endpoints
- [ ] Rate limiting active on webhook endpoints
- [ ] Input validation prevents malicious payloads
- [ ] Attachment downloads validated for security
- [ ] Error messages don't expose internal details
- [ ] Security headers added to all responses
- [ ] Security tests pass with 100% coverage

## Related Files
- `app/config.py` - Add security configuration settings
- `app/main.py` - Add security middleware
- `requirements.txt` - Add security dependencies
- `tests/test_security.py` - Create security test suite

## Rationale
Security improvements provide:
- **Data Protection**: Prevents credential exposure and data leaks
- **Resource Protection**: Prevents resource exhaustion attacks
- **Access Control**: Ensures only authorized requests are processed
- **Audit Trail**: Secure logging for security monitoring
- **Compliance**: Meets security standards for production systems

These security fixes are critical for production deployment and must be implemented before any public exposure.