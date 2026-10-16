export type SourceStatus = "queued" | "parsing" | "chunking" | "embedding" | "ready" | "error" | "deleting";
export type SourceType = "file" | "url" | "business_info";
export type Confidence = "high" | "medium" | "low";

export interface Source {
  id: string;
  type: SourceType;
  status: SourceStatus;
  file_name: string | null;
  url: string | null;
  title: string | null;
  pages: number | null;
  chunks: number | null;
  error: string | null;
}

export interface KnowledgeBase {
  agent_id: string;
  status: "empty" | "indexing" | "ready" | "error";
  rag_enabled: boolean;
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  fallback_message: string;
  hybrid_enabled: boolean;
  rerank_enabled: boolean;
  kb_version: number;
  counts: { files: number; urls: number; business_info: number };
  reindexing?: boolean;
}

export type KnowledgeBaseSettings = Pick<
  KnowledgeBase,
  "chunk_size" | "top_k" | "fallback_message" | "hybrid_enabled" | "rerank_enabled" | "rag_enabled"
>;

export interface KnowledgeBaseStatus {
  files: number;
  urls: number;
  rag_enabled: boolean;
  status: KnowledgeBase["status"];
  label: string;
}

export interface AnswerSource {
  file_name: string | null;
  page: number | null;
  section: string | null;
  url: string | null;
  snippet: string;
  score: number;
}

export interface AnswerDone {
  answer: string;
  spoken_text: string;
  sources: AnswerSource[];
  confidence: Confidence;
  fallback: boolean;
  latency_ms: Record<string, number>;
  cache_hit: boolean;
  error: string | null;
}

export interface BusinessInfo {
  company_name: string;
  hours: string;
  address: string;
  contact: string;
  faq: { question: string; answer: string }[];
}

export const PROCESSING: SourceStatus[] = ["queued", "parsing", "chunking", "embedding", "deleting"];
