#!/usr/bin/env bash
# 50-candidate re-ranking on a stratified subset (20 per KB = 60), retrieval signals only.
set -euo pipefail
cd "$(dirname "$0")"
for kb in kb1_retail kb2_saas_fr kb3_hr_ar; do
  uv run python run_eval.py --kb "$kb" --rerank --subset 20 --no-llm
done
