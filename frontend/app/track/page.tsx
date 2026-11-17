"use client";

/**
 * Tracking, and the moment that closes the loop: confirming or disputing a
 * resolution. A dispute reopens the case.
 *
 * Written for a phone first. The reference number is the thing a citizen
 * needs to keep, so it is large, selectable and copyable in one tap.
 *
 * The citizen sees their own details unmasked here. Masking protects a
 * complainant from the department, not from themselves.
 */
import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { useLang } from "@/components/lang";
import { AiMark } from "@/components/marks";
import { Reveal } from "@/components/ui";
import { api, type TrackedCase } from "@/lib/api";

function CopyRef({ reference }: { reference: string }) {
  const { t } = useLang();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked: the number is still selectable on screen */
    }
  }

  return (
    <button
      onClick={() => void copy()}
      className="pressable inline-flex items-center gap-1.5 text-[13px] font-600 text-ink px-3 py-1.5 rounded-chip bg-teal-tint"
    >
      {copied ? t("action.copied") : t("action.copy")}
    </button>
  );
}

function TrackInner() {
  const { t } = useLang();
  const params = useSearchParams();
  const [reference, setReference] = useState(params.get("ref") ?? "");
  const [tracked, setTracked] = useState<TrackedCase | null>(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (ref: string) => {
    if (!ref.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setTracked(await api.track(ref.trim()));
    } catch (err) {
      setTracked(null);
      setError(
        err instanceof Error ? err.message : "could not find that reference",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const initial = params.get("ref");
    if (initial) void load(initial);
  }, [params, load]);

  async function respond(satisfied: boolean) {
    if (!tracked) return;
    if (!note.trim()) {
      setError("Please say briefly why, so an officer can act on it.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.feedback(tracked.reference_no, {
        satisfied,
        note,
      });
      setMessage(
        result.reopened
          ? "Your case has been reopened and returned to an officer."
          : "Thank you. Your confirmation has been recorded.",
      );
      setNote("");
      await load(tracked.reference_no);
    } catch (err) {
      setError(err instanceof Error ? err.message : "that could not be recorded");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-[760px] px-5 md:px-6 py-8 md:py-14">
      <span className="eyebrow block mb-3">{t("app.name")}</span>
      <h1 className="mb-4">{t("track.title")}</h1>
      <p className="text-[17px] leading-[1.65] text-ink-2 max-w-[50ch] mb-7">
        {t("track.lead")}
      </p>

      <div className="card p-3 flex flex-col sm:flex-row gap-2 mb-8">
        <input
          value={reference}
          onChange={(event) => setReference(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && void load(reference)}
          placeholder="GRV-…"
          className="ref flex-1 bg-surface-card rounded-card px-4 py-3 text-[16px] text-ink placeholder:text-ink-3 outline-none"
        />
        <button
          onClick={() => void load(reference)}
          disabled={busy}
          className="pressable px-7 py-3 rounded-chip bg-teal text-ink border-2 border-ink text-[16px] font-700 hover:bg-teal-deep disabled:opacity-50"
        >
          {t("track.check")}
        </button>
      </div>

      {error && (
        <p className="card bg-rose-tint border-ink p-4 text-[15px] text-rose mb-6">
          {error}
        </p>
      )}
      {message && (
        <p className="card bg-teal-tint border-teal/30 p-4 text-[15px] text-ink mb-6">
          {message}
        </p>
      )}

      {tracked && (
        <article>
          {/* The reference: the one thing to keep. */}
          <Reveal>
            <div className="card p-5 mb-5 flex flex-wrap items-center gap-x-4 gap-y-3">
              <div className="min-w-0">
                <div className="text-[13px] text-ink-3 font-600 mb-1">
                  {t("app.name")}
                </div>
                <div className="ref text-[20px] md:text-[24px] font-500 text-ink select-all break-all">
                  {tracked.reference_no}
                </div>
              </div>
              <div className="ml-auto flex items-center gap-3">
                <CopyRef reference={tracked.reference_no} />
                <span className="inline-flex items-center rounded-chip bg-surface-sunk text-ink-2 px-3 py-1.5 text-[14px] font-600">
                  {tracked.status}
                </span>
              </div>
            </div>
          </Reveal>

          {tracked.ai_summary && (
            <Reveal delay={60}>
              <div className="card p-5 mb-5">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-[13px] font-700 text-ink-3">
                    {t("track.recorded")}
                  </span>
                  <AiMark model={tracked.ai_summary.model} />
                </div>
                <p className="text-[17px] leading-[1.6] text-ink">
                  {tracked.ai_summary.value}
                </p>
              </div>
            </Reveal>
          )}

          <Reveal delay={120}>
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
              {[
                [t("track.department"), tracked.department_id ?? "—"],
                [t("track.priority"), tracked.priority],
                [
                  t("track.due"),
                  tracked.sla_due_at
                    ? new Date(tracked.sla_due_at).toLocaleDateString()
                    : "—",
                ],
                [t("track.reopened"), `${tracked.reopened_count}×`],
              ].map(([label, value]) => (
                <div key={label} className="card px-4 py-3">
                  <dt className="text-[12px] text-ink-3 font-600 mb-1">
                    {label}
                  </dt>
                  <dd className="text-[15px] font-600 text-ink tabular">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </Reveal>

          {tracked.awaiting_feedback && (
            <Reveal>
              <section className="card p-6 mb-8 border-teal/30">
                <h2 className="text-[19px] font-700 mb-2">
                  {t("track.resolvedQ")}
                </h2>
                <p className="text-[15px] text-ink-2 leading-relaxed mb-4">
                  {t("track.resolvedBody")}
                </p>
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={3}
                  placeholder={t("track.placeholder")}
                  className="w-full bg-surface-sunk border-2 border-ink rounded-card p-3 text-[16px] text-ink placeholder:text-ink-3 outline-none resize-none mb-4"
                />
                <div className="flex flex-col sm:flex-row gap-3">
                  <button
                    onClick={() => void respond(true)}
                    disabled={busy}
                    className="pressable px-6 py-3.5 rounded-chip bg-teal text-ink border-2 border-ink text-[16px] font-700 hover:bg-teal-deep disabled:opacity-50"
                  >
                    {t("track.yes")}
                  </button>
                  <button
                    onClick={() => void respond(false)}
                    disabled={busy}
                    className="pressable px-6 py-3.5 rounded-chip border border-line bg-surface-card text-ink-2 text-[16px] font-600 hover:border-amber hover:bg-amber-tint hover:text-ink disabled:opacity-50"
                  >
                    {t("track.no")}
                  </button>
                </div>
              </section>
            </Reveal>
          )}

          {/* Timeline with a connector: a case is a sequence, not a list. */}
          <h2 className="text-[19px] font-700 mb-4">{t("track.timeline")}</h2>
          <ol className="relative">
            {tracked.timeline.map((entry, index) => {
              const last = index === tracked.timeline.length - 1;
              return (
                <Reveal key={index} delay={index * 50}>
                  <li className="relative pl-9 pb-5">
                    <span
                      className={`absolute left-0 top-1.5 w-3.5 h-3.5 rounded-chip border-2 ${
                        last
                          ? "bg-teal border-teal"
                          : "bg-surface-card border-line-strong"
                      }`}
                      aria-hidden
                    />
                    {!last && (
                      <span
                        className="absolute left-[6px] top-6 bottom-0 w-px bg-line"
                        aria-hidden
                      />
                    )}
                    <div className="flex flex-wrap items-baseline gap-x-3 mb-1">
                      <span className="text-[15px] font-600 text-ink capitalize">
                        {entry.action}
                      </span>
                      <span className="text-[13px] text-ink-3">{entry.by}</span>
                      <time className="text-[13px] text-ink-3 tabular ml-auto">
                        {new Date(entry.at).toLocaleDateString()}
                      </time>
                    </div>
                    <p className="text-[14px] text-ink-2 leading-relaxed">
                      {entry.detail}
                    </p>
                  </li>
                </Reveal>
              );
            })}
          </ol>
        </article>
      )}

      <div className="mt-10">
        <Link
          href="/citizen"
          className="group pressable inline-flex items-center gap-2 text-[16px] font-600 text-ink"
        >
          <span className="link-underline">{t("track.new")}</span>
          <span className="arrow-travel" aria-hidden>
            →
          </span>
        </Link>
      </div>
    </div>
  );
}

export default function TrackPage() {
  return (
    <Suspense
      fallback={
        <div className="px-5 py-16 text-ink-3">Loading…</div>
      }
    >
      <TrackInner />
    </Suspense>
  );
}
