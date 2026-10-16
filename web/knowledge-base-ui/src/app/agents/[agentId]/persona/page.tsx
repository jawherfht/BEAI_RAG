import Link from "next/link";
import { KnowledgeBaseStatusChip } from "@/components/KnowledgeBaseStatusChip";
import { I18nProvider } from "@/i18n";
import { resolveLocale, translate } from "@/i18n/core";

/** Minimal stand-in for screen 4 (Persona Builder), to show where screen B merges back. */
export default async function PersonaBuilder({
  params,
  searchParams,
}: {
  params: Promise<{ agentId: string }>;
  searchParams: Promise<{ lang?: string }>;
}) {
  const { agentId } = await params;
  const locale = resolveLocale((await searchParams).lang);
  return (
    <I18nProvider locale={locale}>
      <main className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-2xl font-semibold">{translate(locale, "persona.title")}</h1>
        <div className="mt-6 flex flex-wrap items-center gap-2" aria-live="polite">
          <span className="rounded-full border border-line bg-panel px-3 py-1 text-sm">
            {translate(locale, "persona.avatarLinked")}
          </span>
          <KnowledgeBaseStatusChip agentId={agentId} />
        </div>
        <Link
          className="mt-8 inline-block text-sm text-brand underline"
          href={`/agents/${agentId}/knowledge-base${locale === "fr" ? "?lang=fr" : ""}`}
        >
          {translate(locale, "persona.back")}
        </Link>
      </main>
    </I18nProvider>
  );
}
