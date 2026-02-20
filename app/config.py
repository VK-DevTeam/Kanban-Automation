from pydantic_settings import BaseSettings
from pydantic import Field, validator


class Settings(BaseSettings):
    # Asana Configuration
    asana_access_token: str = Field(..., alias="ASANA_ACCESS_TOKEN")
    asana_project_gid: str = Field(..., alias="ASANA_PROJECT_GID")
    asana_trigger_section_name: str = Field(
        default="VK-Allocate Rjob", alias="ASANA_TRIGGER_SECTION_NAME"
    )
    asana_webhook_secret: str = Field(..., alias="ASANA_WEBHOOK_SECRET")

    # Trello Configuration
    trello_api_key: str = Field(..., alias="TRELLO_API_KEY")
    trello_token: str = Field(..., alias="TRELLO_TOKEN")
    trello_target_list_id: str = Field(..., alias="TRELLO_TARGET_LIST_ID")

    # Redis Configuration
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Retry Configuration
    max_retry_attempts: int = Field(default=3, alias="MAX_RETRY_ATTEMPTS")
    retry_base_delay_seconds: int = Field(default=5, alias="RETRY_BASE_DELAY_SECONDS")

    # Timeout Configuration
    api_timeout_seconds: int = Field(default=30, alias="API_TIMEOUT_SECONDS")
    attachment_timeout_seconds: int = Field(
        default=300, alias="ATTACHMENT_TIMEOUT_SECONDS"
    )

    # Alerting
    dlq_alert_webhook_url: str = Field(default="", alias="DLQ_ALERT_WEBHOOK_URL")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    class Config:
        env_file = ".env"
        case_sensitive = False

    @validator("asana_trigger_section_name")
    def validate_section_name(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError("asana_trigger_section_name must be a non-empty string")
        return v


def get_settings() -> Settings:
    return Settings()
