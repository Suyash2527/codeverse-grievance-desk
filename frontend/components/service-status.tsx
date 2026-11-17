"use client";

/**
 * One honest answer to "is the service up".
 *
 * Without this, a stopped backend shows a different red box on every screen
 * and reads as "the app is broken". A single banner says what is actually
 * wrong and offers the one useful action.
 *
 * It only appears when something is wrong: a healthy service shows nothing.
 */
import { useCallback, useEffect, useState } from "react";

import { useLang } from "@/components/lang";
import { API_BASE } from "@/lib/api";

const POLL_MS = 20000;

export function ServiceStatus() {
  const { t } = useLang();
  const [online, setOnline] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(false);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const response = await fetch(`${API_BASE}/api/health`, {
        cache: "no-store",
      });
      setOnline(response.ok);
    } catch {
      setOnline(false);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void check();
    const id = setInterval(() => void check(), POLL_MS);
    return () => clearInterval(id);
  }, [check]);

  if (online !== false) return null;

  return (
    <div
      role="status"
      className="bg-surface-card text-rose border-b-2 border-ink px-5 py-2.5 text-[14px] flex flex-wrap items-center gap-x-4 gap-y-1 justify-center text-center"
    >
      <span className="font-600">{t("api.offline")}</span>
      <button
        onClick={() => void check()}
        disabled={checking}
        className="pressable underline underline-offset-2 font-600 disabled:opacity-60"
      >
        {checking ? "…" : t("action.retry")}
      </button>
    </div>
  );
}
