"use client";

import { useRef, useState, type FormEvent } from "react";
import { ApiError, streamAnswer } from "@/lib/api";
import type { AnswerDone, AnswerSource, Confidence } from "@/lib/types";
import { useT, type MessageKey } from "@/i18n";
import { Card, inputClass, primaryButton } from "./ui";

const BADGE: Record<Confidence, string> = {
  high: "bg-green-50 text-green-800 border-green-200",
  medium: "bg-amber-50 text-amber-800 border-amber-200",
  low: "bg-red-50 text-red-800 border-red-200",
};

const stripMarkers = (text: string) => text.replace(/\s*\[\d{1,2}(?:\s*,\s*\d{1,2})*\]/g, "").replace(/\s+([.,;:!?])/g, "$1");

export function sourceLabel(s: AnswerSource): string {
  const name = s.file_name ?? s.url ?? "";
  return s.page != null ? `${name} p.${s.page}` : name;
}

export function TestPanel({ agentId }: { agentId: string }) {
  const t = useT();
  const [question, setQuestion] = useState("");
  const [streaming, setStreaming] = useState("");
  const [done, setDone] = useState<AnswerDone | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSource, setOpenSource] = useState<number | null>(null);
  const abort = useRef<AbortController | null>(null);

  async function ask(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || busy) return;
    abort.current?.abort();
    abort.current = new AbortController();
    setBusy(true);
    setError(null);
    setDone(null);
    setStreaming("");
    setOpenSource(null);
    try {
      await streamAnswer(
        agentId,
        question.trim(),
        { onToken: (tok) => setStreaming((prev) => prev + tok), onDone: setDone },
        abort.current.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(t("test.error", { message: err instanceof ApiError ? err.message : String(err) }));
      }
    } finally {
      setBusy(false);
    }
  }

  const answer = done?.answer ?? stripMarkers(streaming);
  const lat = done?.latency_ms ?? {};
  const retrieval = Math.round((lat.embed ?? 0) + (lat.search ?? 0) + (lat.rerank ?? 0));

  return (
    <Card id="test-title" title={t("test.title")}>
      <form onSubmit={ask} className="flex gap-2">
        <label htmlFor="test-question" className="sr-only">
          {t("test.question")}
        </label>
        <input
          id="test-question"
          data-testid="test-question"
          className={inputClass}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t("test.placeholder")}
          maxLength={1000}
        />
        <button type="submit" data-testid="ask" className={primaryButton} disabled={busy || !question.trim()}>
          {busy ? t("test.asking") : t("test.ask")}
        </button>
      </form>

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-700">
          {error}
        </p>
      )}

      {(answer || busy) && (
        <div className="mt-4 space-y-3" aria-live="polite" aria-busy={busy}>
          <p data-testid="answer" className="rounded-lg bg-canvas p-3 text-sm leading-relaxed">
            {answer || "…"}
          </p>
          {done && (
            <>
              {done.fallback && <p className="text-xs text-muted">{t("test.fallbackNote")}</p>}
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted">{t("test.source")}</span>
                {done.sources.length === 0 && <span className="text-muted">{t("test.noSource")}</span>}
                {done.sources.map((s, i) => (
                  <button
                    key={`${sourceLabel(s)}-${i}`}
                    type="button"
                    data-testid="source-chip"
                    aria-expanded={openSource === i}
                    onClick={() => setOpenSource(openSource === i ? null : i)}
                    className="rounded-full border border-line bg-panel px-2.5 py-0.5 font-mono text-xs hover:border-brand"
                  >
                    {sourceLabel(s)}
                  </button>
                ))}
                <span className="ml-auto text-muted">{t("test.confidence")}</span>
                <span data-testid="confidence" className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${BADGE[done.confidence]}`}>
                  {t(`confidence.${done.confidence}` as MessageKey)}
                </span>
              </div>
              {openSource != null && done.sources[openSource] && (
                <blockquote data-testid="source-snippet" className="border-l-4 border-brand/40 pl-3 text-xs text-muted">
                  {done.sources[openSource].section && <strong className="block text-ink">{done.sources[openSource].section}</strong>}
                  {done.sources[openSource].snippet}
                </blockquote>
              )}
              <p data-testid="latency" className="text-xs text-muted">
                {done.cache_hit
                  ? t("test.cached")
                  : t("test.latency", { retrieval, ttft: Math.round(lat.llm_ttft ?? 0), total: Math.round(lat.total ?? 0) })}
              </p>
            </>
          )}
        </div>
      )}
    </Card>
  );
}
