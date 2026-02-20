# Asana → Trello Automation System

Event-driven automation service that monitors an Asana project and automatically creates identical cards in Trello when tasks are moved into a designated section.

## Features

- **Event-Driven**: Responds to Asana webhook events in real-time
- **Idempotent**: Distributed locking and deduplication prevent duplicate cards
- **Reliable**: Retry logic with exponential backoff for transient failures
- **Complete**: Transfers task name, description, and all attachments verbatim
- **Observable**: Structured JSON logging and DLQ alerting
- **Containerized**: Docker and docker-compose for easy deployment

## Prerequisites

- Docker and Docker Compose
- Asana Personal Access Token (read-only)
- Trello API Key and Token (write-only to target board)
- Redis (included in docker-compose)

## Setup

### 1. Clone and Configure

```bash
git clone <repo>
cd asana-trello-automation
cp .env.example .env
```

### 2. Populate .env

```env
ASANA_ACCESS_TOKEN=your_asana_pat
ASANA_PROJECT_GID=your_project_gid
ASANA_TRIGGER_SECTION_NAME=VK-Allocate Rjob
ASANA_WEBHOOK_SECRET=your_webhook_secret

TRELLO_API_KEY=your_trello_key
TRELLO_TOKEN=your_trello_token
TRELLO_TARGET_LIST_ID=your_list_id

REDIS_URL=redis://redis:6379/0

DLQ_ALERT_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
LOG_LEVEL=INFO
```

### 3. Get Asana Project GID

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://app.asana.com/api/1.0/projects?opt_fields=gid,name
```

### 4. Get Trello List ID

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  "https://api.trello.com/1/boards/YOUR_BOARD_ID/lists?key=YOUR_KEY"
```

### 5. Create Asana Webhook

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "resource": "YOUR_PROJECT_GID",
      "target": "https://your-domain.com/webhook/asana"
    }
  }' \
  https://app.asana.com/api/1.0/webhooks
```

## Deployment

### Local Development

```bash
docker-compose up
```

The webhook will be available at `http://localhost:8000/webhook/asana`.

### Production

1. Update docker-compose.yml with your domain
2. Configure Redis persistence and authentication
3. Set up SSL/TLS reverse proxy (nginx/traefik)
4. Configure DLQ alert webhook (Slack)
5. Deploy:

```bash
docker-compose -f docker-compose.yml up -d
```

## Architecture

### Components

- **Webhook Server** (FastAPI): Receives Asana events, validates HMAC signatures, enqueues to Redis
- **Worker Consumer** (asyncio): Dequeues events, processes with retry logic, handles attachments
- **Redis Queue**: Durable event queue with dead-letter queue (DLQ)
- **Deduplication**: Distributed locks and task-to-card mappings prevent duplicates

### Event Flow

```
Asana Event
    ↓
Webhook (HMAC validation)
    ↓
Redis Queue
    ↓
Worker (dedup check)
    ↓
Asana API (fetch task)
    ↓
Trello API (create card)
    ↓
Attachment Pipeline
    ↓
Redis Mapping Store
```

## Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_processor.py

# Run with coverage
pytest --cov=app tests/
```

## Monitoring

### Health Check

```bash
curl http://localhost:8000/health
```

### Logs

```bash
docker-compose logs -f webhook
docker-compose logs -f worker
docker-compose logs -f redis
```

### DLQ Monitoring

Events that fail after max retries are pushed to the DLQ and an alert is sent to the configured Slack webhook.

## Error Handling

| Error | Behavior |
|-------|----------|
| Transient (5xx, 429, timeout) | Retry with exponential backoff (max 3x) |
| Permanent (401, 403) | Log, alert ops, push to DLQ |
| Task not found (404) | Push to DLQ |
| Attachment oversized | Log, append notice to card, continue |
| Attachment upload failed | Log as partial failure, continue |
| Concurrent processing | Distributed lock ensures single card |

## Security

- ✅ HMAC-SHA256 signature validation on every webhook
- ✅ Constant-time comparison to prevent timing attacks
- ✅ No credentials in source code or logs
- ✅ HTTPS-only for all outbound requests
- ✅ Least-privilege API tokens
- ✅ Temp attachment buffers cleared immediately

## Edge Cases Handled

- Task moved in → out → back in: Only one card created (dedup)
- Asana API down: Event retried with backoff
- Trello API down: Event retried, no partial card
- Section renamed: Alert to ops, event discarded
- Concurrent workers: Distributed lock ensures single card
- Oversized attachment: Card created, notice appended
- Task deleted: 404 → DLQ
- Duplicate webhook delivery: Event-level dedup
- Zero attachments: Card created normally
- Unicode/emoji in task name: Transferred verbatim

## Development

### Project Structure

```
asana-trello-automation/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Env var validation
│   ├── webhook/
│   │   ├── router.py        # POST /webhook endpoint
│   │   └── security.py      # HMAC validation
│   ├── queue/
│   │   └── redis_queue.py   # Event queue + DLQ
│   ├── worker/
│   │   ├── worker.py        # Consumer loop
│   │   ├── processor.py     # Core orchestrator
│   │   ├── deduplication.py # Locks + mappings
│   │   ├── asana_client.py  # Asana API
│   │   ├── trello_client.py # Trello API
│   │   └── attachments.py   # Download/upload
│   └── observability/
│       └── logger.py        # Structured logging
└── tests/
    ├── test_webhook.py
    ├── test_processor.py
    ├── test_deduplication.py
    └── test_attachments.py
```

### Adding Features

1. Update config.py with new env vars
2. Implement feature in appropriate module
3. Add tests in tests/
4. Update this README

## Troubleshooting

### Webhook not receiving events

1. Verify webhook URL is publicly accessible
2. Check HMAC secret matches Asana configuration
3. Verify Asana project GID is correct
4. Check logs: `docker-compose logs webhook`

### Cards not being created

1. Verify section name matches exactly (case + whitespace)
2. Check Trello API key and token
3. Verify target list ID is correct
4. Check worker logs: `docker-compose logs worker`
5. Check Redis queue: `redis-cli LLEN asana_trello:queue`

### High DLQ rate

1. Check API credentials
2. Verify rate limits not exceeded
3. Check network connectivity
4. Review error logs for patterns

## License

Internal Confidential - February 2026
