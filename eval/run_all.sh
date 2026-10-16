#!/usr/bin/env bash
# Full Phase 6 pass: all questions of the three KBs (one LLM call each), then the 50-candidate
# re-ranking subset. Resumable: rerun to continue after an interruption.
set -euo pipefail
cd "$(dirname "$0")"
for kb in kb1_retail kb2_saas_fr kb3_hr_ar; do
  uv run python run_eval.py --kb "$kb" ${CHUNK:+--chunk $CHUNK}
done
if [ "${RERANK_SUBSET:-1}" = "1" ]; then
  for kb in kb1_retail kb2_saas_fr kb3_hr_ar; do
    uv run python run_eval.py --kb "$kb" --rerank --subset 20
  done
fi
