/** Server-safe i18n helpers (no React). Every UI string lives in en.json / fr.json. */
import en from "./en.json";
import fr from "./fr.json";

export type MessageKey = keyof typeof en;
export type Locale = "en" | "fr";

const catalogs: Record<Locale, Record<MessageKey, string>> = { en, fr };

export function resolveLocale(value: string | null | undefined): Locale {
  return value === "fr" ? "fr" : "en";
}

export function translate(
  locale: Locale,
  key: MessageKey,
  vars: Record<string, string | number> = {},
): string {
  const template = catalogs[locale][key] ?? en[key];
  return template.replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? `{${name}}`));
}
