# ADR 0004 — Chunk-size default (512) vs. slider step (50)

Status: **open question for the product owner** (interim decision in place)

The spec says: chunk size slider 200–1000, **step 50**, **default 512**. 512 is not on the
step-50 grid, so a strict validator would reject the default.

**Interim decision.** Accept multiples of 50 in [200, 1000] **plus exactly 512**
(`beai_rag_core.kb_rules.validate_chunk_size`, DB check constraint
`ck_knowledge_bases_chunk_size_range`). Overlap = round(12.5% × chunk_size) → 64 at 512.

**Options to close it.** (a) keep as is; (b) default 500 (on-grid, overlap 62);
(c) step 1 or step 8/16/32 so 512 is reachable from the slider.
