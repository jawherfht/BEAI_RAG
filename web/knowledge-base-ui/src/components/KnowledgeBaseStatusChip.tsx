"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { KnowledgeBaseStatus } from "@/lib/types";
import { useT } from "@/i18n";

/** Persona Builder (screen 4) chip: "Knowledge base: 3 files, RAG on". */
export function KnowledgeBaseStatusChip({ agentId }: { agentId: string }) {
  const t = useT();
  const [status, setStatus] = useState<KnowledgeBaseStatus | null>(null);

  useEffect(() => {
    let active = true;
    const load = () =>
      api
        .getStatus(agentId)
        .then((s) => active && setStatus(s))
        .catch(() => undefined);
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [agentId]);

  if (!status) return null;
  const state = t(status.rag_enabled ? "chip.on" : "chip.off");
  const label = t(status.files === 1 ? "chip.labelOne" : "chip.label", { files: status.files, state });
  return (
    <span
      data-testid="kb-status-chip"
      className="rounded-full border border-brand/30 bg-brand/10 px-3 py-1 text-sm font-medium text-brand"
    >
      {label}
    </span>
  );
}
