"use client";

import type { KnowledgeBaseSettings } from "@/lib/types";
import { useT } from "@/i18n";
import { Card, inputClass, Toggle } from "./ui";

/** Allowed chunk sizes: 200-1000 in steps of 50, plus the 512 default (ADR 0004). */
export const CHUNK_SIZES = [...Array.from({ length: 17 }, (_, i) => 200 + i * 50), 512].sort((a, b) => a - b);

function nearestIndex(value: number): number {
  let best = 0;
  CHUNK_SIZES.forEach((v, i) => {
    if (Math.abs(v - value) < Math.abs((CHUNK_SIZES[best] ?? 0) - value)) best = i;
  });
  return best;
}

export function RetrievalSettingsCard({
  settings,
  onChange,
  reindexing,
  saveState,
}: {
  settings: KnowledgeBaseSettings;
  onChange: (patch: Partial<KnowledgeBaseSettings>) => void;
  reindexing: boolean;
  saveState: "idle" | "saving" | "saved";
}) {
  const t = useT();
  const index = nearestIndex(settings.chunk_size);
  return (
    <Card
      id="settings-title"
      title={t("settings.title")}
      aside={
        <span className="text-xs text-muted" aria-live="polite">
          {saveState === "saving" ? t("settings.saving") : saveState === "saved" ? t("settings.saved") : ""}
        </span>
      }
    >
      <div className="space-y-5">
        <div>
          <div className="flex items-baseline justify-between">
            <label htmlFor="chunk-size" className="text-sm font-medium">
              {t("settings.chunkSize")}
            </label>
            <span data-testid="chunk-size-value" className="text-sm tabular-nums">
              {t("settings.chunkSizeValue", { value: settings.chunk_size })}
            </span>
          </div>
          <input
            id="chunk-size"
            data-testid="chunk-size"
            type="range"
            min={0}
            max={CHUNK_SIZES.length - 1}
            step={1}
            value={index}
            aria-valuetext={t("settings.chunkSizeValue", { value: settings.chunk_size })}
            onChange={(e) => onChange({ chunk_size: CHUNK_SIZES[Number(e.target.value)] ?? 512 })}
            className="mt-2 w-full accent-brand"
          />
          <div className="mt-1 flex justify-between text-xs text-muted">
            <span>200</span>
            <span>1000</span>
          </div>
          <p className="mt-1 text-xs text-muted">{t("settings.chunkHelp")}</p>
          {reindexing && (
            <p data-testid="reindexing" role="status" className="mt-1 text-xs font-medium text-brand">
              {t("settings.reindexing")}
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-4">
          <span id="topk-label" className="text-sm font-medium">
            {t("settings.topK")}
          </span>
          <div role="group" aria-labelledby="topk-label" className="flex items-center rounded-lg border border-line">
            <button
              type="button"
              className="px-3 py-1.5 text-lg leading-none disabled:opacity-40"
              aria-label={t("settings.decrease")}
              disabled={settings.top_k <= 1}
              onClick={() => onChange({ top_k: settings.top_k - 1 })}
            >
              −
            </button>
            <output data-testid="top-k" aria-live="polite" className="w-8 text-center text-sm tabular-nums">
              {settings.top_k}
            </output>
            <button
              type="button"
              className="px-3 py-1.5 text-lg leading-none disabled:opacity-40"
              aria-label={t("settings.increase")}
              disabled={settings.top_k >= 10}
              onClick={() => onChange({ top_k: settings.top_k + 1 })}
            >
              +
            </button>
          </div>
        </div>

        <label className="block">
          <span className="text-sm font-medium">{t("settings.fallback")}</span>
          <textarea
            data-testid="fallback"
            className={`${inputClass} mt-1`}
            rows={2}
            maxLength={500}
            value={settings.fallback_message}
            onChange={(e) => onChange({ fallback_message: e.target.value })}
          />
        </label>

        <div className="divide-y divide-line border-t border-line pt-2">
          <Toggle label={t("settings.hybrid")} checked={settings.hybrid_enabled} onChange={(v) => onChange({ hybrid_enabled: v })} />
          <Toggle label={t("settings.rerank")} checked={settings.rerank_enabled} onChange={(v) => onChange({ rerank_enabled: v })} />
          <Toggle label={t("settings.ragOn")} checked={settings.rag_enabled} onChange={(v) => onChange({ rag_enabled: v })} testId="rag-on" />
        </div>
      </div>
    </Card>
  );
}
