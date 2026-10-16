"use client";

import { createContext, useCallback, useContext, type ReactNode } from "react";
import { translate, type Locale, type MessageKey } from "./core";

export type { Locale, MessageKey } from "./core";

type T = (key: MessageKey, vars?: Record<string, string | number>) => string;
const I18nContext = createContext<{ locale: Locale; t: T } | null>(null);

export function I18nProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  const t = useCallback<T>((key, vars) => translate(locale, key, vars), [locale]);
  return <I18nContext.Provider value={{ locale, t }}>{children}</I18nContext.Provider>;
}

export function useT(): T {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useT must be used inside <I18nProvider>");
  return ctx.t;
}
