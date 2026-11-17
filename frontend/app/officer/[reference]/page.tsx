"use client";

/**
 * One case, with everything needed to agree or disagree with the system.
 *
 * Layout is asymmetric on purpose: the complaint and the evidence occupy the
 * wide left column, and the policy verdict sits in a narrow sticky rail on
 * the right, because the verdict is the thing an officer must not lose sight
 * of while reading the evidence.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AlertLine } from "@/components/incidents";
import { PipelineLedger } from "@/components/pipeline";
import {
  AiMark,
  ConfidenceMeter,
  IdentityLine,
  PriorityMark,
  SectionRule,
  SentimentMark,
  SlaMark,
  VerdictStamp,
} from "@/components/marks";
import {
  ApiError,
  api,
  ruleLabel,
  type AuditEntry,
  type Explanation,
  type QueueRow,
} from "@/lib/api";

const OFFICER_ID = "officer-demo-01";

export default function CasePage() {
  const params = useParams<{ reference: string }>();
  const reference = params.reference;

  const [row, setRow] = useState<QueueRow | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<
    { tone: "ok" | "refused" | "error"; text: string; rule?: string } | null
  >(null);

  const load = useCallback(async () => {
    const [caseRow, explain, entries] = await Promise.all([
      api.case(reference),
      api.explain(reference).catch(() => null),
      api.audit(reference).catch(() => []),
    ]);
    setRow(caseRow);
    setExplanation(explain);
    setAudit(entries);
  }, [reference]);

  useEffect(() => {
    void load().catch((err) =>
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "could not load the case",
      }),
    );
  }, [load]);

  async function act(kind: "approve" | "override") {
    if (!note.trim()) {
      setMessage({ tone: "error", text: "A note is required to record either action." });
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      if (kind === "approve") {
        await api.approve(reference, { officer_id: OFFICER_ID, note });
        setMessage({ tone: "ok", text: "Approved and closed under your officer ID." });
      } else {
        await api.override(reference, {
          officer_id: OFFICER_ID,
          note,
          status: "In Progress",
          priority: "CRITICAL",
        });
        setMessage({
          tone: "ok",
          text: "Override recorded: priority raised to CRITICAL, case kept open.",
        });
      }
      setNote("");
      await load();
    } catch (err) {
      if (err instanceof ApiError) {
        setMessage({ tone: "refused", text: err.message, rule: err.rule });
      } else {
        setMessage({
          tone: "error",
          text: err instanceof Error ? err.message : "the action failed",
        });
      }
    } finally {
      setBusy(false);
    }
  }

  if (!row) {
    return (
      <div className="mx-auto max-w-[1400px] px-4 sm:px-8 py-16 text-ink-3 text-[13px]">
        {message?.text ?? "Loading the case…"}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] px-4 sm:px-8 py-10 sm:py-14">
      <Link
        href="/officer"
        className="eyebrow hover:text-ink transition-colors duration-150 inline-block mb-8"
      >
        ← Back to queue
      </Link>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-10 lg:gap-16">
        {/* ---------------- left: the case and its evidence ------------- */}
        <div className="min-w-0 order-2 lg:order-1">
          <div className="ref text-[13px] text-ink mb-3">
            {row.reference_no}
          </div>
          {/* The headline is a fact from the category master, not AI output:
              anything set at this size reads as verified. */}
          <h1 className="text-3xl sm:text-4xl text-ink mb-3 max-w-[22ch]">
            {row.subcategory ?? row.category ?? "Grievance detail"}
          </h1>
          <div className="text-[14px] text-ink-3 mb-6">
            {row.category ?? row.category_id}
          </div>
          <div className="flex flex-wrap items-center gap-4 mb-10">
            <PriorityMark priority={row.priority} />
            <span className="text-[12px] text-ink-3">{row.status}</span>
            <SentimentMark sentiment={row.ai_sentiment} />
          </div>

          {row.ai_summary && (
            <div className="border-l-2 border-teal pl-5 py-1 mb-10">
              <div className="flex items-center gap-3 mb-2">
                <span className="eyebrow">Summary for triage</span>
                <AiMark model={row.ai_summary.model} />
              </div>
              <p className="text-[16px] leading-[1.6] text-ink max-w-[62ch]">
                {row.ai_summary.value}
              </p>
            </div>
          )}

          <section className="mb-12">
            <SectionRule label="As the citizen reported it" />
            <p className="text-[16px] leading-[1.7] text-ink max-w-[68ch]">
              {row.complaint_text}
            </p>
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-6 mt-8">
              <Field label="Category" value={row.category_id} mono />
              <Field label="Department" value={row.department_id ?? "unrouted"} mono />
              <Field label="Taluka" value={row.taluka ?? "—"} />
              <Field label="Language" value={row.complaint_language} />
            </dl>
            <div className="mt-6 flex items-center gap-3">
              <span className="eyebrow">Complainant</span>
              <IdentityLine name={row.citizen_name} masked={row.identity_masked} />
            </div>
          </section>

          {/* The explainability panel the brief asks for. */}
          <section className="mb-12">
            <SectionRule label="Why the system decided this" />

            {explanation?.decision ? (
              <>
                <div className="border border-line rounded-card p-5 mb-6 bg-surface-card">
                  <div className="eyebrow mb-2">Policy rule applied</div>
                  <div className="text-[15px] text-ink mb-1">
                    {ruleLabel(explanation.decision.policy_rule_applied)}
                  </div>
                  <div className="ref text-[11px] text-ink-3 mb-4">
                    {explanation.decision.policy_rule_applied}
                  </div>
                  <p className="text-[14px] text-ink-2 leading-relaxed mb-5">
                    {explanation.decision.policy_reason}
                  </p>
                  <ConfidenceMeter
                    confidence={explanation.decision.confidence}
                    threshold={explanation.decision.confidence_threshold}
                    animate
                  />
                </div>

                <div className="mb-6">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="eyebrow">Decision rationale</span>
                    <AiMark model={explanation.decision.model} />
                  </div>
                  <p className="text-[14px] text-ink-2 leading-relaxed max-w-[68ch]">
                    {explanation.decision.rationale.value}
                  </p>
                </div>

                {explanation.decision.trace_url && (
                  <a
                    href={explanation.decision.trace_url}
                    target="_blank"
                    rel="noreferrer"
                    className="pressable inline-block text-[13px] text-ink border-b border-teal hover:border-teal"
                  >
                    Open the full trace
                  </a>
                )}
              </>
            ) : (
              <p className="text-[13px] text-ink-3">
                No decision has been recorded for this case yet.
              </p>
            )}
          </section>

          <section className="mb-12">
            <SectionRule label="How the agents handled it" />
            <PipelineLedger reference={reference} />
          </section>

          <section className="mb-12">
            <SectionRule label="Past cases retrieved as evidence" />
            <p className="text-[13px] text-ink-3 mb-5 max-w-[68ch]">
              {explanation?.evidence_note ??
                "Retrieved cases are supporting evidence only."}
            </p>
            {explanation && explanation.retrieved_cases.length > 0 ? (
              <ul>
                {explanation.retrieved_cases.map((past, index) => (
                  <li
                    key={past.grievance_id}
                    className="quiet-in border-b border-surface-sunk py-4 grid grid-cols-[88px_1fr_auto] gap-5 items-baseline"
                    style={{ ["--delay" as string]: index * 50 }}
                  >
                    <span className="ref text-[12px] text-ink-3">
                      {past.grievance_id}
                    </span>
                    <span className="text-[13px] text-ink-2 leading-snug">
                      {past.complaint_text ?? "—"}
                    </span>
                    <span className="text-[12px] text-ink-3 tabular whitespace-nowrap">
                      {past.status}
                      {past.resolution_days !== null
                        ? ` · ${past.resolution_days}d`
                        : ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[13px] text-ink-3">
                No sufficiently similar past case was retrieved.
              </p>
            )}
          </section>

          <section>
            <SectionRule label="Audit trail" />
            <ul className="space-y-3">
              {audit.map((entry) => (
                <li
                  key={entry.id}
                  className="grid grid-cols-[92px_1fr] gap-5 text-[12px] border-b border-line pb-3"
                >
                  <span
                    className={
                      entry.actor === "AI_SYSTEM"
                        ? "text-ink"
                        : "text-ink-2"
                    }
                  >
                    {entry.actor === "AI_SYSTEM" ? "AI" : entry.actor_id ?? entry.actor}
                  </span>
                  <div>
                    <div
                      className={`mb-1 ${entry.action.startsWith("REFUSED_") ? "text-rose" : "text-ink"}`}
                    >
                      {entry.action.replaceAll("_", " ").toLowerCase()}
                      {entry.confidence !== null && (
                        <span className="text-ink-3 tabular">
                          {" "}
                          · confidence {entry.confidence}
                        </span>
                      )}
                      {entry.model && (
                        <span className="text-ink-3"> · {entry.model}</span>
                      )}
                    </div>
                    <div className="text-ink-3 leading-relaxed">
                      {entry.reasoning}
                    </div>
                  </div>
                </li>
              ))}
              {audit.length === 0 && (
                <li className="text-[13px] text-ink-3">No entries yet.</li>
              )}
            </ul>
          </section>
        </div>

        {/* ---------------- right: the verdict and the actions ----------- */}
        <aside className="order-1 lg:order-2">
          <div className="lg:sticky lg:top-20 space-y-6">
            <div className="border border-line rounded-card p-5 bg-surface-card">
              <div className="eyebrow mb-4">Policy verdict</div>
              <VerdictStamp
                sensitive={row.policy.sensitive}
                outcome={row.gate?.outcome}
                animate
              />
              {row.policy.policy_note && (
                <p className="text-[13px] text-ink-2 leading-relaxed mt-5">
                  {row.policy.policy_note}
                </p>
              )}
              <dl className="mt-5 space-y-2.5 text-[12px]">
                <Flag label="Sensitive" on={row.policy.sensitive} tone="rose" />
                <Flag
                  label="Identity hiding"
                  on={row.policy.identity_hiding}
                  tone="rose"
                />
                <Flag
                  label="Automation allowed"
                  on={row.policy.auto_resolution_allowed}
                  tone="teal"
                />
              </dl>
            </div>

            <div className="border border-line rounded-card p-5">
              <div className="eyebrow mb-3">Deadline</div>
              <SlaMark
                hours={row.hours_remaining}
                overdue={row.overdue}
                slaDays={row.sla_days}
              />
              <p className="text-[12px] text-ink-3 mt-3">
                {row.sla_days}-day SLA from the category master.
              </p>

              {row.sla_alerts.length > 0 && (
                <div className="mt-5 pt-5 border-t border-surface-sunk space-y-4">
                  {row.sla_alerts.map((alert, index) => (
                    <AlertLine key={index} alert={alert} />
                  ))}
                </div>
              )}
            </div>

            {row.incident && (
              <div className="border border-line rounded-card p-5">
                <div className="eyebrow mb-3">Incident group</div>
                <div className="ref text-[13px] text-ink mb-2">
                  {row.incident.incident_ref}
                </div>
                <p className="text-[12px] text-ink-2 leading-relaxed">
                  Grouped with {row.incident.member_count - 1} other report(s)
                  of the same issue
                  {row.incident.similarity !== null
                    ? ` (similarity ${row.incident.similarity.toFixed(2)})`
                    : ""}
                  . This grievance keeps its own reference number, status,
                  deadline and notifications.
                </p>
                <p className="text-[11px] text-ink-3 mt-3">
                  {row.incident.confirmed_by
                    ? `Confirmed by ${row.incident.confirmed_by}.`
                    : "Suggested grouping, not yet confirmed by an officer."}
                </p>
              </div>
            )}

            <div className="border border-line rounded-card p-5">
              <div className="eyebrow mb-3">Your decision</div>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={3}
                placeholder="Record why. This is stored under your officer ID."
                className="w-full bg-surface-page border border-line-strong rounded-card p-3 text-[13px] text-ink placeholder:text-ink-3 focus:border-teal outline-none transition-colors duration-150 resize-none mb-3"
              />
              <div className="flex flex-col gap-2">
                <button
                  disabled={busy}
                  onClick={() => void act("approve")}
                  className="pressable w-full px-4 py-2.5 rounded-card bg-teal text-ink border-2 border-ink text-[13px] font-500 hover:bg-teal-deep disabled:opacity-50"
                >
                  Approve and resolve
                </button>
                <button
                  disabled={busy}
                  onClick={() => void act("override")}
                  className="pressable w-full px-4 py-2.5 rounded-card border border-line-strong text-ink-2 text-[13px] hover:border-amber hover:bg-amber-tint hover:text-ink disabled:opacity-50"
                >
                  Override: escalate, keep open
                </button>
              </div>
              <p className="text-[11px] text-ink-3 leading-relaxed mt-3">
                You act as {OFFICER_ID}. Officers may close cases the AI is
                forbidden to close; both outcomes are audited.
              </p>

              {message && (
                <div
                  className={`mt-4 rounded-card border p-3 text-[12px] leading-relaxed ${
                    message.tone === "ok"
                      ? "border-ink bg-teal-tint text-ink border border-ink"
                      : message.tone === "refused"
                        ? "border-ink bg-rose-tint text-rose"
                        : "border-amber bg-amber-tint text-ink border border-amber"
                  }`}
                >
                  {message.text}
                  {message.rule && (
                    <div className="ref text-[10px] mt-1.5 opacity-80">
                      {message.rule}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="eyebrow mb-1.5">{label}</dt>
      <dd className={`text-[13px] text-ink ${mono ? "ref" : ""}`}>{value}</dd>
    </div>
  );
}

function Flag({
  label,
  on,
  tone,
}: {
  label: string;
  on: boolean;
  tone: "rose" | "teal";
}) {
  const colour = on
    ? tone === "rose"
      ? "text-rose"
      : "text-ink"
    : "text-ink-3";
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-ink-3">{label}</dt>
      <dd className={`${colour} uppercase tracking-[0.08em] text-[11px]`}>
        {on ? "yes" : "no"}
      </dd>
    </div>
  );
}
