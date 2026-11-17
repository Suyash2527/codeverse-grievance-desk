"use client";

/**
 * Language state for the whole site.
 *
 * Three things matter here beyond storing a string:
 *
 *  - the choice persists, because a citizen who picked Marathi should not
 *    have to pick it again on the tracking page;
 *  - `document.documentElement.lang` is updated, which is what drives the
 *    Devanagari line-height rules and tells a screen reader which language
 *    it is reading;
 *  - the first render matches the server (English), then the stored choice
 *    is applied on mount, so there is no hydration mismatch.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  DEFAULT_LANG,
  LANGUAGES,
  RULE_KEYS,
  translate,
  type Lang,
} from "@/lib/i18n";

const STORAGE_KEY = "grievance-desk.lang";

type Ctx = {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: string) => string;
  ruleLabel: (rule: string | null | undefined) => string;
};

const LanguageContext = createContext<Ctx | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>(DEFAULT_LANG);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY) as Lang | null;
      if (stored && LANGUAGES.some((l) => l.code === stored)) {
        setLangState(stored);
      }
    } catch {
      /* private mode: fall back to English */
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* nothing to do - the choice simply will not persist */
    }
  }, []);

  const value = useMemo<Ctx>(
    () => ({
      lang,
      setLang,
      t: (key: string) => translate(lang, key),
      ruleLabel: (rule) => {
        if (!rule) return translate(lang, "rule.none");
        const key = RULE_KEYS[rule];
        return key
          ? translate(lang, key)
          : rule.replaceAll("_", " ").toLowerCase();
      },
    }),
    [lang, setLang],
  );

  return (
    <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
  );
}

export function useLang(): Ctx {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    // A component outside the provider still renders readable English rather
    // than crashing the page.
    return {
      lang: DEFAULT_LANG,
      setLang: () => {},
      t: (key: string) => translate(DEFAULT_LANG, key),
      ruleLabel: (rule) =>
        rule ? rule.replaceAll("_", " ").toLowerCase() : "No decision recorded",
    };
  }
  return ctx;
}

/**
 * The language switch.
 *
 * Each option is written in its own script, never translated into the
 * current one: someone who reads only Marathi needs to find "मराठी".
 */
export function LanguageSwitch({
  size = "md",
}: {
  size?: "sm" | "md";
}) {
  const { lang, setLang, t } = useLang();
  const pad = size === "sm" ? "px-3 py-1.5 text-[14px]" : "px-4 py-2 text-[15px]";

  return (
    <div
      className="flex items-center gap-1 rounded-chip border-2 border-ink bg-surface-card p-1"
      role="group"
      aria-label={t("nav.language")}
    >
      {LANGUAGES.map((option) => {
        const active = lang === option.code;
        return (
          <button
            key={option.code}
            onClick={() => setLang(option.code)}
            aria-pressed={active}
            lang={option.code}
            className={`pressable ${pad} rounded-chip font-600 whitespace-nowrap transition-colors duration-150 ${
              active
                ? "bg-teal text-ink border-2 border-ink"
                : "text-ink-3 hover:text-ink"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
