"""Container images used by integration tests. Must match docker-compose.yml."""

IMAGES = {
    "qdrant": "qdrant/qdrant:v1.19.1",
    "postgres": "postgres:16-alpine",
    "redis": "redis:7.4-alpine",
    "rabbitmq": "rabbitmq:3.13-management-alpine",
    "minio": "pgsty/minio:RELEASE.2026-08-04T00-00-00Z",
}
