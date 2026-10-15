# ADR 0003 — Dev infrastructure images and integration testing

Status: accepted (Phase 1)

| Service | Image | Notes |
|---|---|---|
| Qdrant | `qdrant/qdrant:v1.19.1` | Apache-2.0. API key required (`QDRANT__SERVICE__API_KEY`). Client `qdrant-client` 1.19.1. |
| PostgreSQL | `postgres:16-alpine` | |
| Redis | `redis:7.4-alpine` | |
| RabbitMQ | `rabbitmq:3.13-management-alpine` | MPL-2.0 server (not linked; network service). |
| Object storage (S3) | `chrislusf/seaweedfs:4.47` | **SeaweedFS instead of MinIO** (product-owner decision, 2026-10-15), see below. |

**Object storage.** The spec names MinIO for dev. The official `minio/minio` images are no
longer published on Docker Hub, and MinIO is AGPL-3.0. Decision (2026-10-15): use
**SeaweedFS** (Apache-2.0) as the dev S3 server. Prod still uses any S3-compatible storage;
the code only speaks the S3 API (aiobotocore), so nothing else changes. Dev credentials live in
`deploy/dev/seaweedfs-s3.json` and must match `S3_ACCESS_KEY` / `S3_SECRET_KEY`. The host port
stays 9000 (`S3_ENDPOINT=http://localhost:9000`); inside compose it is `http://seaweedfs:8333`.

**Integration tests** use testcontainers with the same images (`tests/integration/images.py`,
kept in sync with `docker-compose.yml` by `tests/unit/test_compose.py`), so `make test` is
hermetic and works in CI. The RabbitMQ readiness probe uses an AMQP handshake rather than
`docker exec rabbitmq-diagnostics`, which (run as root before boot) creates a root-owned
Erlang cookie and crashes the broker.
