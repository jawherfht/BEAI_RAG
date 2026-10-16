"use client";

import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import type { BusinessInfo, Source, SourceStatus } from "@/lib/types";
import { useT, type MessageKey } from "@/i18n";
import { Card, inputClass, primaryButton, secondaryButton } from "./ui";

const ACCEPT = ".pdf,.docx,.pptx,.txt,.md,.markdown,.html,.htm";

const PILL: Record<SourceStatus, string> = {
  queued: "bg-gray-100 text-gray-700",
  parsing: "bg-blue-50 text-blue-800",
  chunking: "bg-blue-50 text-blue-800",
  embedding: "bg-indigo-50 text-indigo-800",
  ready: "bg-green-50 text-green-800",
  error: "bg-red-50 text-red-800",
  deleting: "bg-gray-100 text-gray-600",
};

function StatusPill({ status }: { status: SourceStatus }) {
  const t = useT();
  return (
    <span data-testid="source-status" className={`rounded-full px-2 py-0.5 text-xs font-medium ${PILL[status]}`}>
      {t(`status.${status}` as MessageKey)}
    </span>
  );
}

function icon(source: Source): string {
  if (source.type === "url") return "🌐";
  if (source.type === "business_info") return "🏢";
  const ext = (source.file_name ?? "").split(".").pop()?.toLowerCase();
  return ext === "pdf" ? "📕" : ext === "docx" ? "📘" : ext === "pptx" ? "📙" : "📄";
}

export function SourcesCard({
  agentId,
  sources,
  onChanged,
}: {
  agentId: string;
  sources: Source[];
  onChanged: () => void;
}) {
  const t = useT();
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showUrl, setShowUrl] = useState(false);
  const bizDialog = useRef<HTMLDialogElement>(null);
  const files = sources.filter((s) => s.type === "file").length;
  const urls = sources.filter((s) => s.type === "url").length;

  async function upload(list: FileList | File[]) {
    const items = Array.from(list);
    if (!items.length) return;
    setUploading(true);
    setError(null);
    try {
      await api.uploadFiles(agentId, items);
      onChanged();
    } catch (e) {
      setError(t("sources.uploadFailed", { message: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      setUploading(false);
    }
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    void upload(e.dataTransfer.files);
  }

  return (
    <Card
      id="sources-title"
      title={t("sources.title")}
      aside={
        <span data-testid="sources-summary" className="text-sm text-muted">
          {t(files === 1 ? "sources.summaryOne" : "sources.summary", { files, urls })}
        </span>
      }
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`rounded-lg border-2 border-dashed p-5 text-center text-sm transition-colors ${dragging ? "border-brand bg-brand/5" : "border-line"}`}
      >
        <p>
          {t("sources.dropzone")}{" "}
          <label className="cursor-pointer font-medium text-brand underline">
            {t("sources.browse")}
            <input
              data-testid="file-input"
              type="file"
              multiple
              accept={ACCEPT}
              className="sr-only"
              onChange={(e) => {
                if (e.target.files) void upload(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
        </p>
        <p className="mt-1 text-xs text-muted">{uploading ? t("sources.uploading") : t("sources.dropzoneHint")}</p>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={secondaryButton} onClick={() => setShowUrl((v) => !v)} aria-expanded={showUrl}>
          {t("sources.addUrl")}
        </button>
        <button type="button" className={secondaryButton} onClick={() => bizDialog.current?.showModal()}>
          {t("sources.businessInfo")}
        </button>
      </div>
      {showUrl && (
        <AddUrlForm
          agentId={agentId}
          onDone={() => {
            setShowUrl(false);
            onChanged();
          }}
          onCancel={() => setShowUrl(false)}
        />
      )}

      <ul className="mt-4 divide-y divide-line" aria-label={t("sources.title")}>
        {sources.length === 0 && <li className="py-3 text-sm text-muted">{t("sources.empty")}</li>}
        {sources.map((s) => {
          const name = s.type === "url" ? (s.url ?? "") : (s.file_name ?? s.title ?? "");
          return (
            <li key={s.id} data-testid="source-row" className="flex items-center gap-3 py-2.5">
              <span aria-hidden className="text-lg">
                {icon(s)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium" title={name}>
                  {name}
                </p>
                <p className="text-xs text-muted">
                  {[s.pages != null && t("sources.pages", { count: s.pages }), s.chunks != null && t(s.chunks === 1 ? "sources.chunksOne" : "sources.chunks", { count: s.chunks })]
                    .filter(Boolean)
                    .join(" · ")}
                  {s.status === "error" && s.error && <span className="text-red-700"> {s.error}</span>}
                </p>
              </div>
              <StatusPill status={s.status} />
              <button
                type="button"
                className="rounded p-1 text-sm text-muted hover:text-red-700 disabled:opacity-40"
                aria-label={t("sources.deleteLabel", { name })}
                disabled={s.status === "deleting"}
                onClick={async () => {
                  await api.deleteSource(agentId, s.id);
                  onChanged();
                }}
              >
                ✕
              </button>
            </li>
          );
        })}
      </ul>
      <BusinessInfoDialog ref={bizDialog} agentId={agentId} onSaved={onChanged} />
    </Card>
  );
}

function AddUrlForm({ agentId, onDone, onCancel }: { agentId: string; onDone: () => void; onCancel: () => void }) {
  const t = useT();
  const [url, setUrl] = useState("");
  const [depth, setDepth] = useState(1);
  const [maxPages, setMaxPages] = useState(50);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!/^https?:\/\/\S+\.\S+/.test(url)) {
      setError(t("url.invalid"));
      return;
    }
    try {
      await api.addUrl(agentId, url, depth, maxPages);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <form onSubmit={submit} className="mt-3 grid gap-2 rounded-lg border border-line p-3 sm:grid-cols-[1fr_auto_auto_auto]" aria-label={t("url.title")}>
      <label className="text-xs text-muted">
        {t("url.url")}
        <input className={inputClass} type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" required />
      </label>
      <label className="text-xs text-muted">
        {t("url.depth")}
        <input className={`${inputClass} w-20`} type="number" min={0} max={3} value={depth} onChange={(e) => setDepth(Number(e.target.value))} />
      </label>
      <label className="text-xs text-muted">
        {t("url.maxPages")}
        <input className={`${inputClass} w-24`} type="number" min={1} max={500} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} />
      </label>
      <div className="flex items-end gap-2">
        <button type="submit" className={primaryButton}>
          {t("url.add")}
        </button>
        <button type="button" className={secondaryButton} onClick={onCancel}>
          {t("url.cancel")}
        </button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-red-700 sm:col-span-4">
          {error}
        </p>
      )}
    </form>
  );
}

const EMPTY_INFO: BusinessInfo = { company_name: "", hours: "", address: "", contact: "", faq: [] };

function BusinessInfoDialog({
  ref,
  agentId,
  onSaved,
}: {
  ref: React.RefObject<HTMLDialogElement | null>;
  agentId: string;
  onSaved: () => void;
}) {
  const t = useT();
  const [info, setInfo] = useState<BusinessInfo>(EMPTY_INFO);
  const [error, setError] = useState<string | null>(null);
  const field = (key: "company_name" | "hours" | "address" | "contact", label: MessageKey) => (
    <label className="block text-xs text-muted">
      {t(label)}
      <input className={inputClass} value={info[key]} onChange={(e) => setInfo({ ...info, [key]: e.target.value })} />
    </label>
  );

  return (
    <dialog ref={ref} aria-label={t("biz.title")} className="m-auto w-full max-w-lg rounded-xl border border-line p-0 backdrop:bg-black/30">
      <form
        method="dialog"
        className="space-y-3 p-5"
        onSubmit={async (e) => {
          e.preventDefault();
          try {
            await api.putBusinessInfo(agentId, {
              ...info,
              faq: info.faq.filter((f) => f.question.trim() && f.answer.trim()),
            });
            ref.current?.close();
            onSaved();
          } catch (err) {
            setError(err instanceof ApiError ? err.message : String(err));
          }
        }}
      >
        <h3 className="text-base font-semibold">{t("biz.title")}</h3>
        {field("company_name", "biz.companyName")}
        {field("hours", "biz.hours")}
        {field("address", "biz.address")}
        {field("contact", "biz.contact")}
        <fieldset className="space-y-2">
          <legend className="text-xs text-muted">{t("biz.faq")}</legend>
          {info.faq.map((f, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-2">
              <input
                aria-label={t("biz.question")}
                placeholder={t("biz.question")}
                className={inputClass}
                value={f.question}
                onChange={(e) => setInfo({ ...info, faq: info.faq.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)) })}
              />
              <input
                aria-label={t("biz.answer")}
                placeholder={t("biz.answer")}
                className={inputClass}
                value={f.answer}
                onChange={(e) => setInfo({ ...info, faq: info.faq.map((x, j) => (j === i ? { ...x, answer: e.target.value } : x)) })}
              />
            </div>
          ))}
          <button type="button" className={secondaryButton} onClick={() => setInfo({ ...info, faq: [...info.faq, { question: "", answer: "" }] })}>
            {t("biz.addFaq")}
          </button>
        </fieldset>
        {error && (
          <p role="alert" className="text-sm text-red-700">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className={secondaryButton} onClick={() => ref.current?.close()}>
            {t("biz.close")}
          </button>
          <button type="submit" className={primaryButton}>
            {t("biz.save")}
          </button>
        </div>
      </form>
    </dialog>
  );
}
