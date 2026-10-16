"use client";

import type { ReactNode } from "react";

export function Card({ title, children, aside, id }: { title: string; children: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <section aria-labelledby={id} className="rounded-xl border border-line bg-panel p-5 shadow-sm">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 id={id} className="text-base font-semibold">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
  testId,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  testId?: string;
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 py-1.5">
      <span className="text-sm">{label}</span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        data-testid={testId}
        onClick={() => onChange(!checked)}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? "bg-brand" : "bg-gray-300"}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0"}`}
        />
      </button>
    </label>
  );
}

export const buttonClass =
  "inline-flex items-center justify-center rounded-lg px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
export const primaryButton = `${buttonClass} bg-brand text-brand-ink hover:bg-brand/90`;
export const secondaryButton = `${buttonClass} border border-line bg-panel hover:bg-canvas`;
export const inputClass =
  "w-full rounded-lg border border-line bg-panel px-3 py-2 text-sm placeholder:text-muted focus:border-brand";
