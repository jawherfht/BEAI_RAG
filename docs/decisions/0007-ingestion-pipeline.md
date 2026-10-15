# ADR 0007 — Ingestion pipeline design (Phase 2)

Status: accepted (Phase 2)

## Flow
`POST /sources/*` validates, stores the file under
`tenants/{tenant}/agents/{agent}/sources/{source}/…`, inserts `sources` (status `queued`) and an
`ingestion_jobs` row, **commits, then publishes** `IngestJob` and returns 202. If the broker is
down the job is marked failed, the source shows "Could not queue…", and the API returns 503.

Worker: `parsing → chunking → embedding → ready`, each status in its own short transaction.

## Queue topology (RabbitMQ)
- `beai.ingest` (direct) → `ingest.index|reindex|delete|recrawl`; each queue dead-letters to
  `beai.ingest.dlx` → `ingest.dead` (malformed messages are rejected there).
- Retries: transient failure → republish to `beai.ingest.retry.<n>.<delay>ms` (TTL queue that
  dead-letters back to `beai.ingest`). Delays 2 s / 8 s / 32 s (`RETRY_BASE_MS`). After 3 retries
  → `ingest.dead`, source `error` with a human-readable message. The delay is in the queue name
  so changing the config never clashes with existing queues; only the worker declares them.
- **Permanent errors skip retries** (unreadable document, blocked URL, no text): retrying
  cannot help, and the user gets the message immediately. Model-download / network failures
  inside the parser are classified as transient (`ModelUnavailableError`), never blamed on the
  document.

## Blue/green re-indexing
Point id = `uuid5(source_id, chunk_index, kb_version)` where `kb_version` is read when the job
starts. A settings change (e.g. chunk size) bumps `kb_version` first, so re-indexing writes a
new set of ids; after the upsert, `delete_stale_points` removes the source's points whose ids
are not in the new set. Answers never go empty during a re-index.

## Parsed-document cache
The parse result is stored as `_parsed.json` next to the file. `reindex` jobs (slider change,
manual reindex) re-chunk from the cache instead of re-running Docling or re-crawling.

## Deletion while indexing
Every status update re-reads the source row under a lock; if it is gone or `deleting`, the job
stops and deletes any points it already wrote.

## Re-crawl
The worker schedules `ingest.recrawl` for URL sources whose `recrawl_interval_hours` elapsed.
`sources.sha256` holds the crawl's content hash for URL sources; unchanged content skips
re-embedding.

## Chunking
Structure-aware, token-based (embedding tokenizer). See `worker/chunking/chunker.py`
docstring. Sections never mix, sentences are never cut (except a single run-on "sentence"
longer than 2× chunk size), tables stay whole up to 2× chunk size, otherwise split by rows with
the header repeated. Overlap = trailing whole sentences ≤ `chunk_overlap` tokens.

## Language detection
`lingua-language-detector` (Apache-2.0), low-accuracy mode (fast, ~75 languages). fastText
`lid.176` was rejected: its model is CC-BY-SA.

## Deferred
- Embedding-model change ("bi-directional embedding updates", section 5) is not in the Phase 2
  scope; `kb_version`/`embed_model_version` already support it. Planned with MLOps in Phase 7.
- Sandboxed parsing with resource limits (section 9) is Phase 7 hardening; today Docling runs in
  a worker thread with page and size limits, no macro execution.
- DNS-rebinding: the crawler checks resolved IPs before every request and redirect hop, but
  httpx resolves again when connecting. Pinning the connection to the checked IP is Phase 7.
