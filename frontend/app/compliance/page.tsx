"use client";

/**
 * The safety contract, proved live.
 *
 * Every row here is the result of calling the real policy module against the
 * category master loaded right now — not a screenshot of a passing test run.
 * Re-running it is the point: a judge can weaken a guard and watch a row go
 * red.
 *
 * Design: a certificate, not a dashboard. One column of rules, each with the
 * probe that was attempted and what the system did about it. The only colour
 * is the pass mark, so a single red entry is unmissable in a dark room.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useLang } from "@/components/lang";
import { API_BASE } from "@/lib/api";

type Rule = {
  id: number;
  statement: string;
  enforced_by: string;
  probe: string;
  defence_in_depth?: boolean;
  result: { passed: boolean; detail: string };
};

type Report = {
  checked_against: {
    confidence_threshold: number;
    sensitive_category_used: string | null;
    identity_hiding_category_used: string | null;
  };
  passed: number;
  total: number;
  all_passed: boolean;
  rules: Rule[];
  note: string;
};

export default function CompliancePage() {
  const { t } = useLang();
  const [report, setReport] = useState<Report | null>(null);
  const [ranAt, setRanAt] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/compliance/rules`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`${response.status}`);
      setReport(await response.json());
      setRanAt(new Date().toLocaleTimeString());
    } catch {
      setError("Could not reach the API. Is the backend running on port 8000?");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  return (
    <div className="mx-auto max-w-[880px] px-4 sm:px-8 py-10 sm:py-16">
      <div className="eyebrow mb-3">{t("rules.eyebrow")}</div>
      <h1 className="text-4xl sm:text-5xl text-ink mb-5 max-w-[18ch]">
{t("rules.title")}
      </h1>
      <p className="text-[16px] leading-[1.7] text-ink-2 max-w-[62ch] mb-8">
{t("rules.lead")}
      </p>

      <div className="flex flex-wrap items-center gap-4 mb-10 pb-6 border-b border-line">
        <button
          onClick={() => void run()}
          disabled={busy}
          className="pressable px-5 py-2.5 rounded-card bg-teal text-ink border-2 border-ink text-[14px] font-500 hover:bg-teal-deep disabled:opacity-50"
        >
          {busy ? t("rules.running") : t("rules.run")}
        </button>
        {report && (
          <div className="flex items-baseline gap-3">
            <span
              className={`font-display text-3xl tabular ${
                report.all_passed ? "text-ink" : "text-rose"
              }`}
            >
              {report.passed}/{report.total}
            </span>
            <span className="eyebrow">
              {report.all_passed ? t("rules.enforced") : t("rules.failing")}
            </span>
          </div>
        )}
        {ranAt && (
          <span className="text-[12px] text-ink-3 ml-auto tabular">
            {t("rules.lastRun")} {ranAt}
          </span>
        )}
      </div>

      {error && (
        <p className="text-[13px] text-rose border border-ink bg-rose-tint rounded-card p-4">
          {error}
        </p>
      )}

      {report && (
        <>
          <ol>
            {report.rules.map((rule, index) => (
              <li
                key={rule.id}
                className="quiet-in border-b border-surface-sunk py-6 grid grid-cols-[32px_1fr] gap-5"
                style={{ ["--delay" as string]: index * 45 }}
              >
                <span
                  className={`font-display text-[13px] tabular pt-0.5 ${
                    rule.result.passed ? "text-ink" : "text-rose"
                  }`}
                  aria-label={rule.result.passed ? "enforced" : "failing"}
                >
                  {rule.result.passed ? "✓" : "✕"}
                </span>

                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-3 mb-2">
                    <h2 className="text-[16px] text-ink leading-snug">
                      {rule.statement}
                    </h2>
                    {rule.defence_in_depth && (
                      <span className="text-[10px] uppercase tracking-[0.12em] text-ink border border-teal rounded-card px-1.5 py-0.5 whitespace-nowrap">
                        {t("rules.depth")}
                      </span>
                    )}
                  </div>

                  <dl className="space-y-1.5 text-[13px]">
                    <div className="flex gap-3">
                      <dt className="text-ink-3 w-[92px] shrink-0">{t("rules.attempted")}</dt>
                      <dd className="text-ink-2">{rule.probe}</dd>
                    </div>
                    <div className="flex gap-3">
                      <dt className="text-ink-3 w-[92px] shrink-0">{t("rules.result")}</dt>
                      <dd
                        className={
                          rule.result.passed ? "text-ink" : "text-rose"
                        }
                      >
                        {rule.result.detail}
                      </dd>
                    </div>
                    <div className="flex gap-3">
                      <dt className="text-ink-3 w-[92px] shrink-0">{t("rules.enforcedBy")}</dt>
                      <dd className="text-ink-3">{rule.enforced_by}</dd>
                    </div>
                  </dl>
                </div>
              </li>
            ))}
          </ol>

          <div className="mt-10 text-[12px] text-ink-3 leading-relaxed border-l-2 border-line pl-4 space-y-2">
            <p>{report.note}</p>
            <p className="tabular">
              Tested against {report.checked_against.sensitive_category_used} as
              the sensitive category and{" "}
              {report.checked_against.identity_hiding_category_used} as the
              identity-hiding one, both read from the current CSV — swap the
              file and these probes test whatever it says instead. Confidence
              threshold {report.checked_against.confidence_threshold}.
            </p>
          </div>
        </>
      )}

      <div className="mt-12 flex gap-6">
        <Link
          href="/officer"
          className="pressable text-[14px] text-ink-2 hover:text-ink border-b border-line-strong"
        >
          Officer queue →
        </Link>
        <Link
          href="/citizen"
          className="pressable text-[14px] text-ink-2 hover:text-ink border-b border-line-strong"
        >
          Citizen desk →
        </Link>
      </div>
    </div>
  );
}
