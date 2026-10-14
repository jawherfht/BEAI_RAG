# ADR 0003 — Dev infrastructure images and integration testing

Status: accepted (Phase 1)

| Service | Image | Notes |
|---|---|---|
| Qdrant | `qdrant/qdrant:v1.19.1` | Apache-2.0. API key required (`QDRANT__SERVICE__API_KEY`). Client `qdrant-client` 1.19.1. |
| PostgreSQL | `postgres:16-alpine` | |
| Redis | `redis:7.4-alpine` | |
| RabbitMQ | `rabbitmq:3.13-management-alpine` | MPL-2.0 server (not linked; network service). |
| MinIO | `pgsty/minio:RELEASE.2026-08-04T00-00-00Z` | **Changed source image**, see below. |

**MinIO.** The official `minio/minio` images are no longer published on Docker Hub (pull
returns "repository does not exist"), and `quay.io` is not reachable from the build
environment. `pgsty/minio` is a maintained build of the same MinIO server with the same
entrypoint (`minio server /data`). MinIO is **AGPL-3.0**; it is used only as the dev stand-in
for S3 (spec section 2: "MinIO in dev; S3-compatible object storage in prod"), accessed over
the S3 API, never linked or shipped. If AGPL is unacceptable even in dev, SeaweedFS
(Apache-2.0, `chrislusf/seaweedfs`) is a drop-in S3 alternative — a compose change only.

**Integration tests** use testcontainers with the same images (`tests/integration/images.py`,
kept in sync with `docker-compose.yml` by `tests/unit/test_compose.py`), so `make test` is
hermetic and works in CI. The RabbitMQ readiness probe uses an AMQP handshake rather than
`docker exec rabbitmq-diagnostics`, which (run as root before boot) creates a root-owned
Erlang cookie and crashes the broker.
