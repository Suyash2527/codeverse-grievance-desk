"use client";

/**
 * Incident groups and SLA alerts.
 *
 * The incident panel deliberately lists every member reference with its own
 * status and deadline rather than collapsing them into a count. The rule is
 * that nothing is merged, so the interface should make it obvious that three
 * reports are still three grievances.
 */
import { useEffect, useState } from "react";

import { useLang } from "@/components/lang";
import { api, type Incident, type SlaAlert } from "@/lib/api";

const OFFICER_ID = "officer-demo-01";

/** Risk marks: amber for time pressure, deeper amber once past the deadline. */
export function RiskMark({ risk }: { risk: string }) {
  const { t } = useLang();
  const tone =
    risk === "OVERDUE"
      ? "border-amber bg-amber-tint text-ink"
      : risk === "BREACH_LIKELY"
        ? "border-amber bg-amber-tint text-ink"
        : risk === "AT_RISK"
          ? "border-amber bg-amber-tint text-ink"
          : risk === "INSUFFICIENT_HISTORY"
            ? "border-line-strong text-ink-3"
            : "border-line-strong text-ink-2";
  return (
    <span
      className={`${tone} border rounded-card px-2 py-0.5 text-[10px] uppercase tracking-[0.1em] whitespace-nowrap`}
    >
      {t(`risk.${risk}`)}
    </span>
  );
}

/** One alert, always shown with the evidence base behind it. */
export function AlertLine({ alert }: { alert: SlaAlert }) {
  return (
    <div className="flex items-start gap-3">
      <RiskMark risk={alert.risk} />
      <div className="min-w-0">
        <p className="text-[12px] text-ink-2 leading-relaxed">{alert.reason}</p>
        <p className="text-[11px] text-ink-3 mt-1 tabular">
          {alert.sample_size > 0
            ? `based on ${alert.sample_size} comparable closed case(s)`
            : "no comparable history"}
          {alert.historical_p80_days !== null
            ? ` · p80 ${alert.historical_p80_days}d`
            : ""}
        </p>
      </div>
    </div>
  );
}

export function IncidentPanel() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function load() {
    setIncidents(await api.incidents().catch(() => []));
  }

  useEffect(() => {
    void load();
  }, []);

  async function regroup() {
    setBusy(true);
    try {
      await api.groupDuplicates();
      await load();
      setNote("Grouping re-run. No grievance was merged or closed.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm(incident: Incident) {
    await api.confirmIncident(incident.id, {
      officer_id: OFFICER_ID,
      note: "Confirmed as one incident during triage.",
    });
    await load();
  }

  if (!incidents) return null;

  return (
    <section className="mt-16">
      <div className="flex items-end justify-between gap-6 mb-4">
        <div>
          <div className="eyebrow mb-2">Suggested incident groups</div>
          <p className="text-[13px] text-ink-3 max-w-[62ch]">
            Reports of the same issue, same place, same week. Grouping is for
            coordination only — every grievance below keeps its own reference
            number, status, deadline and notifications.
          </p>
        </div>
        <button
          onClick={() => void regroup()}
          disabled={busy}
          className="pressable shrink-0 px-3 py-1.5 rounded-card text-[13px] border border-line-strong text-ink-2 hover:text-ink disabled:opacity-50"
        >
          {busy ? "Grouping…" : "Re-run grouping"}
        </button>
      </div>
      <div className="h-px bg-line mb-6" />

      {note && <p className="text-[12px] text-ink mb-4">{note}</p>}

      {incidents.length === 0 ? (
        <p className="text-[13px] text-ink-3">
          No duplicate groups detected in the current window.
        </p>
      ) : (
        <ul className="space-y-4">
          {incidents.map((incident, index) => (
            <li
              key={incident.incident_ref}
              className="quiet-in border border-line rounded-card p-5"
              style={{ ["--delay" as string]: index * 60 }}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-4 mb-4">
                <div>
                  <span className="ref text-[13px] text-ink">
                    {incident.incident_ref}
                  </span>
                  <span className="text-[13px] text-ink-2 ml-3">
                    {incident.member_count} separate grievances ·{" "}
                    {incident.locality ?? incident.taluka ?? "location unknown"}
                  </span>
                </div>
                {incident.confirmed_by ? (
                  <span className="text-[11px] text-ink uppercase tracking-[0.1em]">
                    confirmed by {incident.confirmed_by}
                  </span>
                ) : (
                  <button
                    onClick={() => void confirm(incident)}
                    className="pressable px-3 py-1 rounded-card text-[12px] border border-teal text-ink hover:bg-teal-tint"
                  >
                    Confirm grouping
                  </button>
                )}
              </div>

              <ul className="divide-y divide-line-soft border-t border-line">
                {incident.members.map((member) => (
                  <li
                    key={member.reference_no}
                    className="py-2.5 grid grid-cols-[1fr_auto_auto] gap-4 items-baseline text-[12px]"
                  >
                    <span className="ref text-ink">{member.reference_no}</span>
                    <span className="text-ink-2">{member.status}</span>
                    <span className="text-ink-3 tabular">
                      due{" "}
                      {member.sla_due_at
                        ? new Date(member.sla_due_at).toLocaleDateString()
                        : "—"}
                    </span>
                  </li>
                ))}
              </ul>

              <p className="text-[11px] text-ink-3 mt-3">{incident.note}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
