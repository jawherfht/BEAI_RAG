import { KnowledgeBaseScreen } from "@/components/KnowledgeBaseScreen";
import { I18nProvider } from "@/i18n";
import { resolveLocale } from "@/i18n/core";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ agentId: string }>;
  searchParams: Promise<{ lang?: string; agentName?: string }>;
}) {
  const { agentId } = await params;
  const { lang, agentName } = await searchParams;
  const locale = resolveLocale(lang);
  return (
    <I18nProvider locale={locale}>
      <KnowledgeBaseScreen agentId={agentId} agentName={agentName ?? null} locale={locale} />
    </I18nProvider>
  );
}
