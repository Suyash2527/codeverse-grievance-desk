"use client";

/**
 * The officer queue: a ledger, not a card grid.
 *
 * Reading order is the design: reference, verdict, summary, confidence,
 * time left. An officer scanning down the column sees which cases a rule
 * has taken out of their hands before they read a single complaint.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  ConfidenceMeter,
  AiMark,
  IdentityLine,
  PriorityMark,
  SentimentMark,
  SlaMark,
  StatusMark,
  VerdictStamp,
} from "@/components/marks";
import { IncidentPanel, RiskMark } from "@/components/incidents";
import { CountUp, QueueSkeleton } from "@/components/count-up";
import { useLang } from "@/components/lang";
import { api, type Queue, type QueueRow } from "@/lib/api";

type Filter = "all" | "review" | "sensitive" | "overdue";

const FILTERS: { id: Filter; key: string }[] = [
  { id: "all", key: "queue.filter.all" },
  { id: "review", key: "queue.filter.review" },
  { id: "sensitive", key: "queue.filter.sensitive" },
  { id: "overdue", key: "queue.filter.overdue" },
];

export default function OfficerQueuePage() {
  const { t } = useLang();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await api.queue(
        filter === "review"
          ? { awaiting_review: "true" }
          : filter === "sensitive"
            ? { sensitive: "true" }
            : {},
      );
      setQueue(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "could not reach the API");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const rows = (queue?.rows ?? []).filter((row) =>
    filter === "overdue" ? row.overdue : true,
  );

  return (
    <div className="mx-auto max-w-[1180px] px-5 md:px-6 py-8 md:py-14">
      {/* Asymmetric header: heavy left, counts pushed right. */}
      <div className="flex flex-col lg:flex-row lg:items-end gap-7 lg:gap-16 mb-8">
        <div className="flex-1 min-w-0">
          <div className="eyebrow mb-3">{t("queue.eyebrow")}</div>
          <h1 className="mb-3">{t("queue.title")}</h1>
          <p className="text-ink-2 text-[16px] leading-relaxed max-w-[62ch]">
{t("queue.lead")}
          </p>
        </div>

        <dl className="grid grid-cols-3 gap-3 shrink-0 lg:w-[420px]">
          <Count label={t("queue.count.review")} value={queue?.counts.awaiting_review} />
          <Count label={t("queue.count.sensitive")} value={queue?.counts.sensitive} tone="rose" />
          <Count label={t("queue.count.overdue")} value={queue?.counts.overdue} tone="amber" />
        </dl>
      </div>

      <div className="flex items-center gap-2 mb-6 overflow-x-auto -mx-5 px-5 md:mx-0 md:px-0 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]{display:none}">
        {FILTERS.map((option) => (
          <button
            key={option.id}
            onClick={() => setFilter(option.id)}
            className={`pressable shrink-0 whitespace-nowrap px-4 py-2 rounded-chip text-[14px] font-600 border ${
              filter === option.id
                ? "border-ink bg-teal text-ink border-2 border-ink"
                : "border-line bg-surface-card text-ink-2 hover:border-line-strong hover:text-ink"
            }`}
          >
            {t(option.key)}
          </button>
        ))}
        <Link
          href="/officer/hotspots"
          className="pressable ml-auto shrink-0 whitespace-nowrap px-4 py-2 rounded-chip text-[14px] font-500 border border-line bg-surface-card text-ink-2 hover:text-ink hover:border-line-strong"
        >
          {t("queue.hotspots")}
        </Link>
        <button
          onClick={() => void load()}
          className="pressable px-4 py-2 rounded-chip text-[14px] font-500 border border-line bg-surface-card text-ink-2 hover:text-ink hover:border-line-strong"
        >
          {t("queue.refresh")}
        </button>
      </div>

      {error && (
        <div className="card bg-rose-tint border-ink p-5 text-[14px] text-rose mb-6">
          {error}
          <div className="text-ink-3 mt-1">
            Is the API running on {process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"}?
          </div>
        </div>
      )}

      {loading && !queue && <QueueSkeleton rows={3} />}

      {queue && rows.length === 0 && (
        <div className="card py-16 px-6 text-center">
          <p className="text-ink text-[17px] font-600 mb-1">{t("queue.empty.title")}</p>
          <p className="text-ink-3 text-[13px]">
            {t("queue.empty.body")}
          </p>
        </div>
      )}

      {rows.length > 0 && (
        <ul className="space-y-3">
          {rows.map((row, index) => (
            <QueueItem key={row.reference_no} row={row} index={index} />
          ))}
        </ul>
      )}

      <IncidentPanel />
    </div>
  );
}

function Count({
  label,
  value,
  tone = "teal",
}: {
  label: string;
  value: number | undefined;
  tone?: "teal" | "rose" | "amber";
}) {
  // A count of zero needs no attention, so it must not wear an alarm colour.
  // Red and amber here mean "look at this", not "this is the sensitive column".
  // A count of zero needs no attention, so it must not wear an alarm colour.
  const colour =
    value === 0 || value === undefined
      ? "text-ink-3"
      : tone === "rose"
        ? "text-rose"
        : tone === "amber"
          ? "text-ink decoration-amber underline decoration-4 underline-offset-4"
          : "text-ink";
  return (
    <div className="card px-4 py-4">
      <dd className={`${colour} font-display text-4xl lg:text-5xl tabular leading-none mb-2 font-800`}>
        <CountUp value={value} />
      </dd>
      <dt className="text-[13px] text-ink-3 font-500 leading-tight">{label}</dt>
    </div>
  );
}

function QueueItem({ row, index }: { row: QueueRow; index: number }) {
  const { t, ruleLabel } = useLang();
  // The spine carries the verdict in peripheral vision: an officer scanning
  // the column sees which cases a rule has taken out of their hands before
  // reading a single word.
  const spine = row.policy.sensitive
    ? "spine-sensitive"
    : row.gate?.outcome === "HUMAN_QUEUE"
      ? "bg-amber"
      : "bg-teal";

  return (
    <li
      className="rise-in"
      style={{ ["--row-index" as string]: Math.min(index, 12) }}
    >
      <Link
        href={`/officer/${row.reference_no}`}
        className="card card-interactive group block relative overflow-hidden pl-6 pr-5 py-5"
      >
        <span className={`${spine} absolute left-0 top-0 bottom-0 w-1.5`} aria-hidden />

        {/* Line 1: the verdict and the clock, the two things that decide
            whether this case is touched next. */}
        <div className="flex flex-wrap items-center gap-3 mb-3">
          <VerdictStamp
            sensitive={row.policy.sensitive}
            outcome={row.gate?.outcome}
          />
          <PriorityMark priority={row.priority} />
          <span className="ml-auto flex items-center gap-3">
            {row.sla_alerts.map((alert, i) => (
              <RiskMark key={i} risk={alert.risk} />
            ))}
            <SlaMark
              hours={row.hours_remaining}
              overdue={row.overdue}
              slaDays={row.sla_days}
            />
          </span>
        </div>

        {/* Line 2: what the case is about, at a readable size. */}
        <p className="text-[17px] leading-[1.45] text-ink mb-3 pr-4 group-hover:bg-teal-tint-deep transition-colors duration-150">
          {row.ai_summary?.value ?? row.complaint_text}
        </p>

        {/* Line 3: the supporting facts, quiet. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px] text-ink-3 mb-4">
          <span className="ref text-ink-2">{row.reference_no}</span>
          <span>{row.subcategory ?? row.category_id}</span>
          <span>{row.department_id ?? "unrouted"}</span>
          <span>{row.taluka ?? "location unknown"}</span>
          <StatusMark status={row.status} />
          <IdentityLine name={row.citizen_name} masked={row.identity_masked} />
          {row.ai_summary && <AiMark model={row.ai_summary.model} />}
          {row.reopened_count > 0 && (
            <span className="text-ink font-700 bg-amber-tint px-1.5">
              {t("queue.reopened")} ×{row.reopened_count}
            </span>
          )}
          {row.incident && (
            <span className="text-ink font-500">
              {row.incident.incident_ref} · 1 / {row.incident.member_count}{" "}
              {t("queue.reports")}
            </span>
          )}
        </div>

        {/* Line 4: why the system decided this. */}
        {row.gate && (
          <div className="flex flex-col sm:flex-row sm:items-end gap-3 sm:gap-8 pt-4 border-t border-line">
            <p className="text-[14px] text-ink-2 flex-1 min-w-0">
              {ruleLabel(row.gate.rule_applied)}
            </p>
            <div className="sm:w-[220px] shrink-0">
              <ConfidenceMeter
                confidence={row.gate.confidence}
                threshold={row.gate.confidence_threshold}
              />
            </div>
          </div>
        )}
      </Link>
    </li>
  );
}
