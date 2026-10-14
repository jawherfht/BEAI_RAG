# ADR 0005 — Licence policy for transitive dependencies

Status: **open question for the product owner**

Rule 4 says "only MIT or Apache-2.0 components in production". The spec's own picks pull in
permissive non-MIT/Apache transitive dependencies that cannot be avoided:

- BSD-3-Clause: `starlette` (FastAPI's core), `uvicorn`, `httpx`/`httpcore`, `click`,
  `websockets`, `python-dotenv` (pydantic-settings), `pamqp` (aio-pika), `idna`, `protobuf`
- BSD-2-Clause: `wrapt`, `Pygments`; PSF: `typing_extensions`, `aiohappyeyeballs`
- MPL-2.0: `certifi` (CA bundle, unmodified)

`make licenses` prints the full report (pip-licenses).

**Proposal.** Keep **models and chosen components** strictly MIT/Apache-2.0 (and never
CC-BY-NC / Gemma / Llama terms), and allow **permissive transitive libraries**
(BSD, ISC, PSF, and unmodified MPL-2.0). Copyleft (GPL/AGPL/LGPL) stays forbidden in anything
shipped. The Phase 7 licence gate will enforce this allow-list.
