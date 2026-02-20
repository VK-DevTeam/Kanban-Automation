from fastapi import APIRouter, Request, HTTPException, status
from app.webhook.security import validate_webhook_signature
from app.queue.redis_queue import RedisQueue
from app.config import get_settings
from app.observability.logger import get_logger

router = APIRouter(prefix="/webhook", tags=["webhook"])
logger = get_logger(__name__)


@router.post("/asana")
async def asana_webhook(request: Request):
    """
    Receive Asana webhook events.
    
    - Validates HMAC-SHA256 signature
    - Handles handshake requests
    - Enqueues events for async processing
    """
    settings = get_settings()
    queue = RedisQueue()

    # Get raw body for signature validation
    raw_body = await request.body()

    # Check for handshake request
    if request.headers.get("X-Hook-Secret"):
        secret = request.headers.get("X-Hook-Secret")
        logger.info("Received Asana webhook handshake", secret=secret)
        # Asana expects the secret in the response headers, not body
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content={},
            headers={"X-Hook-Secret": secret}
        )

    # Validate signature
    signature = request.headers.get("X-Hook-Signature")
    if not validate_webhook_signature(settings.asana_webhook_secret, raw_body, signature):
        logger.warning("Invalid webhook signature received")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    # Parse event
    try:
        event = await request.json()
    except Exception as e:
        logger.error("Failed to parse webhook payload", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    # Enqueue event
    queue.enqueue(event)

    # Return 200 immediately
    return {"status": "received"}
