import type {
  AnswerDone,
  BusinessInfo,
  KnowledgeBase,
  KnowledgeBaseSettings,
  KnowledgeBaseStatus,
  Source,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

const base = (agentId: string) => `/api/rag/v1/agents/${encodeURIComponent(agentId)}`;

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { cache: "no-store", ...init });
  if (!res.ok) {
    let code = "error";
    let message = res.statusText;
    try {
      const body = (await res.json()) as { error?: { code?: string; message?: string } };
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "content-type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  getKnowledgeBase: (agentId: string) => call<KnowledgeBase>(`${base(agentId)}/knowledge-base`),
  putKnowledgeBase: (agentId: string, settings: Partial<KnowledgeBaseSettings>) =>
    call<KnowledgeBase>(`${base(agentId)}/knowledge-base`, json("PUT", settings)),
  getStatus: (agentId: string) => call<KnowledgeBaseStatus>(`${base(agentId)}/knowledge-base/status`),
  listSources: (agentId: string) => call<Source[]>(`${base(agentId)}/sources`),
  uploadFiles: (agentId: string, files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    return call<{ source_id: string; status: string; duplicate: boolean }[]>(`${base(agentId)}/sources/files`, {
      method: "POST",
      body: form,
    });
  },
  addUrl: (agentId: string, url: string, crawlDepth: number, maxPages: number) =>
    call(`${base(agentId)}/sources/urls`, json("POST", { url, crawl_depth: crawlDepth, max_pages: maxPages })),
  putBusinessInfo: (agentId: string, info: BusinessInfo) =>
    call(`${base(agentId)}/sources/business-info`, json("PUT", info)),
  deleteSource: (agentId: string, sourceId: string) =>
    call(`${base(agentId)}/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" }),
};

export interface StreamHandlers {
  onToken: (text: string) => void;
  onDone: (done: AnswerDone) => void;
}

/** POST /answer and parse the SSE stream (EventSource cannot POST). */
export async function streamAnswer(
  agentId: string,
  question: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${base(agentId)}/answer`, {
    ...json("POST", { question }),
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    signal,
  });
  if (!res.ok || !res.body) {
    let message = res.statusText;
    try {
      message = ((await res.json()) as { error?: { message?: string } }).error?.message ?? message;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, "answer_failed", message);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (!data) continue;
      const payload: unknown = JSON.parse(data);
      if (event === "token") handlers.onToken((payload as { text: string }).text);
      else if (event === "done") handlers.onDone(payload as AnswerDone);
    }
  }
}
