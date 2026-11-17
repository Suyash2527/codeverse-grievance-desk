"use client";

/**
 * The agent hand-off ledger.
 *
 * Reconstructed server-side from the decision, audit and dispatch records a
 * run wrote, so it works whether or not Langfuse is reachable. When a trace
 * link exists it is shown alongside rather than replaced.
 *
 * Design: a single vertical rule with each hand-off hanging off it, like
 * entries in a day book. The state mark is the only colour — teal for
 * completed, red for a refusal, muted for a stage never reached — so a
 * refused action is visible at a glance without reading a word.
 */
import { useEffect, useState } from "react";

import { API_BASE } from "@/lib/api";

type Span = {
  name: string;
  agent: string;
  state: "done" | "refused" | "not reached";
  at: string | null;
  summary: string;
  detail: Record<string, unknown>;
};

type PipelineRun = {
  reference_no: string;
  spans: Span[];
  elapsed_ms: number | null;
  trace_url: string | null;
  note: string;
};

export function PipelineLedger({ reference }: { reference: string }) {
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/grievances/${reference}/pipeline`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then(setRun)
      .catch(() => setRun(null));
  }, [reference]);

  if (!run) return null;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-4 mb-5">
        <p className="text-[13px] text-ink-3 max-w-[52ch] leading-relaxed">
          {run.note}
        </p>
        {run.trace_url ? (
          <a
            href={run.trace_url}
            target="_blank"
            rel="noreferrer"
            className="pressable text-[13px] text-ink border-b border-teal hover:border-teal shrink-0"
          >
            Open in Langfuse
          </a>
        ) : (
          <span className="text-[12px] text-ink-3 shrink-0">
            Langfuse not configured
          </span>
        )}
      </div>

      <ol className="relative border-l border-line ml-[7px]">
        {run.spans.map((span, index) => {
          const expanded = open === span.name;
          const tone =
            span.state === "refused"
              ? "bg-surface-card border-ink border-2"
              : span.state === "done"
                ? "bg-teal border-teal"
                : "bg-line border-line-strong";
          return (
            <li
              key={span.name}
              className="quiet-in relative pl-6 pb-6 last:pb-0"
              style={{ ["--delay" as string]: index * 55 }}
            >
              <span
                className={`${tone} absolute -left-[5px] top-[5px] w-[9px] h-[9px] rounded-full border`}
                aria-hidden
              />
              <button
                onClick={() => setOpen(expanded ? null : span.name)}
                className="text-left w-full group"
                aria-expanded={expanded}
              >
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-1">
                  <span className="text-[14px] text-ink">{span.agent}</span>
                  <span className="ref text-[11px] text-ink-3">{span.name}</span>
                  {span.state === "refused" && (
                    <span className="text-[10px] uppercase tracking-[0.12em] text-rose border border-ink rounded-card px-1.5 py-0.5">
                      refused
                    </span>
                  )}
                  {span.state === "not reached" && (
                    <span className="text-[10px] uppercase tracking-[0.12em] text-ink-3">
                      not reached
                    </span>
                  )}
                  <span className="ml-auto text-[11px] text-ink-3 group-hover:text-ink-2 transition-colors duration-150">
                    {expanded ? "hide" : "detail"}
                  </span>
                </div>
                <p
                  className={`text-[13px] leading-relaxed ${
                    span.state === "refused" ? "text-rose" : "text-ink-2"
                  }`}
                >
                  {span.summary}
                </p>
              </button>

              {expanded && (
                <dl className="mt-3 border border-line rounded-card p-4 space-y-1.5 text-[12px] bg-surface-card">
                  {Object.entries(span.detail).map(([key, value]) => (
                    <div
                      key={key}
                      className="flex items-baseline justify-between gap-6"
                    >
                      <dt className="text-ink-3 shrink-0">
                        {key.replaceAll("_", " ")}
                      </dt>
                      <dd className="text-ink text-right break-words min-w-0">
                        {renderValue(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          );
        })}
      </ol>

      {run.elapsed_ms !== null && (
        <p className="text-[12px] text-ink-3 mt-5 tabular">
          Intake to action: {run.elapsed_ms} ms
        </p>
      )}
    </div>
  );
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) {
    return value.length === 0
      ? "none"
      : value
          .map((item) =>
            typeof item === "object" ? JSON.stringify(item) : String(item),
          )
          .join(", ");
  }
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}
