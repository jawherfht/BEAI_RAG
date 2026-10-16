"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { PROCESSING, type KnowledgeBaseSettings, type Source } from "@/lib/types";
import { useT, type Locale } from "@/i18n";
import { RetrievalSettingsCard } from "./RetrievalSettingsCard";
import { SourcesCard } from "./SourcesCard";
import { TestPanel } from "./TestPanel";
import { primaryButton } from "./ui";

const POLL_MS = 2000;
const SAVE_DEBOUNCE_MS = 600;

export function KnowledgeBaseScreen({ agentId, agentName, locale }: { agentId: string; agentName: string | null; locale: Locale }) {
  const t = useT();
  const router = useRouter();
  const [settings, setSettings] = useState<KnowledgeBaseSettings | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [reindexing, setReindexing] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const pending = useRef<Partial<KnowledgeBaseSettings>>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshSources = useCallback(async () => {
    const list = await api.listSources(agentId);
    setSources(list);
    if (!list.some((s) => PROCESSING.includes(s.status))) setReindexing(false);
    return list;
  }, [agentId]);

  useEffect(() => {
    void (async () => {
      const kb = await api.getKnowledgeBase(agentId);
      setSettings({
        chunk_size: kb.chunk_size,
        top_k: kb.top_k,
        fallback_message: kb.fallback_message,
        hybrid_enabled: kb.hybrid_enabled,
        rerank_enabled: kb.rerank_enabled,
        rag_enabled: kb.rag_enabled,
      });
      await refreshSources();
    })();
  }, [agentId, refreshSources]);

  const processing = sources.some((s) => PROCESSING.includes(s.status));
  useEffect(() => {
    if (!processing) return;
    const id = setInterval(() => void refreshSources(), POLL_MS);
    return () => clearInterval(id);
  }, [processing, refreshSources]);

  const flush = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    const patch = pending.current;
    pending.current = {};
    if (Object.keys(patch).length === 0) return;
    setSaveState("saving");
    const kb = await api.putKnowledgeBase(agentId, patch);
    setSaveState("saved");
    if (kb.reindexing) {
      setReindexing(true);
      await refreshSources();
    }
  }, [agentId, refreshSources]);

  const onChange = (patch: Partial<KnowledgeBaseSettings>) => {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
    pending.current = { ...pending.current, ...patch };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => void flush(), SAVE_DEBOUNCE_MS);
  };

  const saveAndContinue = async () => {
    await flush();
    router.push(`/agents/${agentId}/persona${locale === "fr" ? "?lang=fr" : ""}`);
  };

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
      <header className="mb-4">
        <h1 className="text-2xl font-semibold">{t("screen.title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("screen.subtitle", { agent: agentName ?? t("screen.defaultAgent") })}</p>
      </header>
      <div role="note" data-testid="warning-banner" className="mb-6 rounded-lg border border-amber-200 bg-warn-bg px-4 py-2.5 text-sm text-warn-ink">
        ⚠ {t("banner.warning")}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.15fr_1fr]">
        <div className="space-y-6">
          <SourcesCard agentId={agentId} sources={sources} onChanged={() => void refreshSources()} />
          {settings && (
            <RetrievalSettingsCard settings={settings} onChange={onChange} reindexing={reindexing && processing} saveState={saveState} />
          )}
        </div>
        <div className="lg:sticky lg:top-6 lg:self-start">
          <TestPanel agentId={agentId} />
        </div>
      </div>

      <footer className="mt-8 flex justify-end">
        <button type="button" data-testid="save-continue" className={primaryButton} onClick={() => void saveAndContinue()}>
          {t("footer.saveContinue")}
        </button>
      </footer>
    </main>
  );
}
