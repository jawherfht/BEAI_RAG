# ADR 0005 — Licence policy for transitive dependencies

Status: **accepted** (product owner, 2026-10-15)

Rule 4 says "only MIT or Apache-2.0 components in production". The spec's own picks pull in
permissive non-MIT/Apache transitive dependencies that cannot be avoided:

- BSD-3-Clause: `starlette` (FastAPI's core), `uvicorn`, `httpx`/`httpcore`, `click`,
  `websockets`, `python-dotenv` (pydantic-settings), `pamqp` (aio-pika), `idna`, `protobuf`
- BSD-2-Clause: `wrapt`, `Pygments`; PSF: `typing_extensions`, `aiohappyeyeballs`
- MPL-2.0: `certifi` (CA bundle, unmodified)

`make licenses` prints the full report (pip-licenses).

**Decision.** Keep **models and chosen components** strictly MIT/Apache-2.0 (and never
CC-BY-NC / Gemma / Llama terms), and allow **permissive transitive libraries**
(BSD, ISC, PSF, and unmodified MPL-2.0). Copyleft (GPL/AGPL/LGPL) stays forbidden in anything
shipped. The Phase 7 licence gate will enforce this allow-list.

## Findings after Phase 2 dependencies (2026-10-15)

`make licenses` over 192 packages:

Decisions (product owner, 2026-10-15): **CPU-only torch** for the worker (no NVIDIA wheels);
**`tld` accepted, unmodified, under MPL-1.1**.

1. **NVIDIA CUDA runtime wheels** (`nvidia-cublas`, `nvidia-cudnn-cu13`, … — NVIDIA proprietary,
   redistributable) arrive because Docling depends on `torch`, and the default PyPI `torch`
   wheel for Linux bundles CUDA. Options: (a) accept them in the GPU worker image only (they are
   the standard NVIDIA runtime, like the GPU drivers); (b) install CPU-only `torch` from the
   PyTorch CPU index for the worker (no NVIDIA packages; Docling then runs on CPU — must be
   checked against the "50-page PDF ready in ≤ 2 min" target).
2. **`tld`** (via Trafilatura → courlan) is tri-licensed `MPL-1.1 OR GPL-2.0 OR LGPL-2.1+`; we
   would use it under MPL-1.1, unmodified — consistent with the MPL rule above if MPL-1.1 is
   accepted alongside MPL-2.0.
3. `torch` includes `BSL-1.0` = Boost Software License (permissive) — fine.
4. `py_rust_stemmers` (FastEmbed BM25 stemmer) has no licence metadata; the upstream project
   states MIT — to confirm before production.

Status of the CPU-only torch switch: **done (2026-10-15)**. The workspace resolves `torch` and
`torchvision` from the explicit `pytorch-cpu` uv index (`torch 2.14.1+cpu`); `make licenses`
lists no NVIDIA packages. Resolution is limited to linux x86_64/aarch64 and macOS.

## Frontend (Phase 5, 2026-10-16) — one item to confirm
- `@img/sharp-libvips-*` (LGPL-3.0): optional Next.js image optimiser. Not used
  (`images.unoptimized`), removed from the Docker image; dev-only install.
- `caniuse-lite` (CC-BY-4.0): browser support *data* used by browserslist at build time.
  CC-BY allows commercial use with attribution (it is not the forbidden NC variant); attribution
  in `web/knowledge-base-ui/THIRD_PARTY_NOTICES.md`. **Accepted by the product owner (2026-10-16).**
