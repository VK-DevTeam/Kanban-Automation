from fastapi import FastAPI
from app.config import get_settings
from app.observability.logger import setup_logging
from app.webhook.router import router as webhook_router

# Setup logging
setup_logging()

# Initialize FastAPI app
app = FastAPI(
    title="Asana → Trello Automation",
    description="Event-driven automation service",
    version="1.0.0",
)

# Include webhook router
app.include_router(webhook_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.on_event("startup")
async def startup_event():
    """Validate configuration on startup."""
    settings = get_settings()
    print(f"Starting Asana → Trello Automation Service")
    print(f"Asana Project GID: {settings.asana_project_gid}")
    print(f"Trigger Section: {settings.asana_trigger_section_name}")
    print(f"Trello Target List: {settings.trello_target_list_id}")
