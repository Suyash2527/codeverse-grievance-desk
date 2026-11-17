"use client";

/**
 * Taluka hotspot ledger.
 *
 * Deliberately NOT a geographic map: a choropleth of Nanded's talukas needs
 * real boundary data, and inventing coordinates would be fabricating
 * geography in a government-facing tool. Ranked magnitude bars answer the
 * actual question — which places are worst, and where does the district miss
 * its own deadlines — without pretending to cartography.
 *
 * Encoding rules followed here:
 *   one measure per chart (never a dual axis),
 *   one colour for every bar, because talukas are nominal categories and a
 *     darker-where-bigger ramp would double-encode the bar length,
 *   amber reserved for time pressure, rose for a policy rule,
 *   a value label on every bar, plus a table view of the same figures.
 *
 * Detail opens on tap, not hover: a hover-only tooltip is unusable on the
 * phone this is mostly read on.
 */
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useLang } from "@/components/lang";
import { Figure, Reveal } from "@/components/ui";
import { API_BASE } from "@/lib/api";
import type { MapRow } from "@/components/taluka-map";

// Leaflet touches window on import, so the map is client-only.
const TalukaMap = dynamic(() => import("@/components/taluka-map"), {
  ssr: false,
  loading: () => (
    <div className="card skeleton" style={{ height: 420 }} aria-hidden />
  ),
});

type TopCategory = {
  category_id: string;
  label: string;
  count: number | string;
  suppressed: boolean;
};

type TalukaRow = {
  taluka: string;
  live_open: number;
  live_overdue: number;
  live_total: number;
  historical_total: number;
  historical_breached: number;
  historical_breach_rate: number | null;
  top_categories: TopCategory[];
  sensitive_cases: number | string;
  recurring_categories: string[];
};

type Hotspots = {
  generated_at: string;
  talukas: TalukaRow[];
  district: {
    talukas_covered: number;
    historical_closed: number;
    historical_breached: number;
    historical_breach_rate: number | null;
    live_open: number;
  };
  privacy: { granularity: string; min_cell_size: number; note: string };
};

type Measure = "volume" | "breach";
type View = "map" | "list";

export default function HotspotsPage() {
  const { t } = useLang();
  const [data, setData] = useState<Hotspots | null>(null);
  const [measure, setMeasure] = useState<Measure>("volume");
  const [open, setOpen] = useState<string | null>(null);
  const [view, setView] = useState<View>("map");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/api/analytics/hotspots`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then(setData)
      .catch(() => setError("Could not load analytics. Is the API running?"));
  }, []);

  const rows = useMemo(() => {
    if (!data) return [];
    const copy = [...data.talukas];
    copy.sort((a, b) =>
      measure === "volume"
        ? b.historical_total + b.live_total - (a.historical_total + a.live_total)
        : (b.historical_breach_rate ?? 0) - (a.historical_breach_rate ?? 0),
    );
    return copy;
  }, [data, measure]);

  const valueOf = (row: TalukaRow) =>
    measure === "volume"
      ? row.historical_total + row.live_total
      : (row.historical_breach_rate ?? 0) * 100;

  const max = rows.length ? Math.max(...rows.map(valueOf)) : 0;

  const mapRows: MapRow[] = rows.map((row) => ({
    taluka: row.taluka,
    value: valueOf(row),
    recorded: row.historical_total + row.live_total,
    open: row.live_open,
    overdue: row.live_overdue,
    breachRate: row.historical_breach_rate,
  }));

  return (
    <div className="mx-auto max-w-[1000px] px-5 md:px-6 py-8 md:py-14">
      <Link
        href="/officer"
        className="group pressable inline-flex items-center gap-2 text-[15px] font-600 text-ink-2 hover:text-ink mb-7"
      >
        <span aria-hidden>←</span>
        <span className="link-underline">{t("nav.queue")}</span>
      </Link>

      <div className="flex flex-col lg:flex-row lg:items-end gap-7 lg:gap-14 mb-8">
        <div className="flex-1">
          <span className="eyebrow block mb-3">{t("hot.eyebrow")}</span>
          <h1 className="mb-4">{t("hot.title")}</h1>
          <p className="text-[16px] leading-relaxed text-ink-2 max-w-[58ch]">
            {t("hot.lead")}
          </p>
        </div>
        {data && (
          <dl className="grid grid-cols-3 gap-3 shrink-0 lg:w-[400px]">
            <div className="card px-4 py-4">
              <Figure
                value={data.district.talukas_covered}
                label={t("hot.talukas")}
              />
            </div>
            <div className="card px-4 py-4">
              <Figure
                value={
                  data.district.historical_breach_rate !== null
                    ? `${Math.round(data.district.historical_breach_rate * 100)}%`
                    : "–"
                }
                label={t("hot.pastSla")}
                tone="amber"
              />
            </div>
            <div className="card px-4 py-4">
              <Figure value={data.district.live_open} label={t("hot.openNow")} />
            </div>
          </dl>
        )}
      </div>

      {/* One measure at a time: two scales on one chart would mislead. */}
      <div className="flex items-center gap-2 mb-3 overflow-x-auto -mx-5 px-5 md:mx-0 md:px-0 pb-1">
        {(["volume", "breach"] as Measure[]).map((option) => (
          <button
            key={option}
            onClick={() => setMeasure(option)}
            className={`pressable shrink-0 whitespace-nowrap px-4 py-2 rounded-chip text-[14px] font-600 border ${
              measure === option
                ? "border-ink bg-teal text-ink border-2 border-ink"
                : "border-line bg-surface-card text-ink-2 hover:border-line-strong hover:text-ink"
            }`}
          >
            {t(`hot.measure.${option}`)}
          </button>
        ))}
      </div>
      <p className="text-[14px] text-ink-3 mb-2">
        {t(`hot.caption.${measure}`)}
      </p>
      <div className="flex items-center gap-2 mb-6">
        {(["map", "list"] as View[]).map((option) => (
          <button
            key={option}
            onClick={() => setView(option)}
            className={`pressable shrink-0 whitespace-nowrap px-4 py-2 rounded-chip text-[14px] font-600 border ${
              view === option
                ? "border-ink bg-teal-tint text-ink border border-ink"
                : "border-line bg-surface-card text-ink-2 hover:border-line-strong hover:text-ink"
            }`}
          >
            {t(`hot.view.${option}`)}
          </button>
        ))}
        {view === "list" && (
          <span className="text-[13px] text-ink-3 ml-1">
            {t("hot.tapDetail")}
          </span>
        )}
      </div>

      {view === "map" && rows.length > 0 && (
        <div className="mb-10">
          <TalukaMap rows={mapRows} measure={measure} />
        </div>
      )}

      {error && (
        <p className="card bg-rose-tint border-ink p-4 text-[15px] text-rose">
          {error}
        </p>
      )}

      {view === "list" && rows.length > 0 && (
        <div className="card overflow-hidden mb-10">
          <ul className="divide-y divide-line-soft">
            {rows.map((row, index) => {
              const value = valueOf(row);
              const width = max > 0 ? (value / max) * 100 : 0;
              const expanded = open === row.taluka;
              return (
                <li key={row.taluka}>
                  <button
                    onClick={() => setOpen(expanded ? null : row.taluka)}
                    aria-expanded={expanded}
                    className="w-full text-left px-4 py-3 hover:bg-surface-sunk transition-colors duration-150"
                  >
                    <div className="flex items-center justify-between gap-3 mb-2">
                      <span className="text-[15px] font-600 text-ink">
                        {row.taluka}
                      </span>
                      <span className="flex items-center gap-3">
                        {row.live_overdue > 0 && (
                          <span className="inline-flex items-center rounded-chip bg-amber-tint text-ink border border-amber px-2 py-0.5 text-[12px] font-600">
                            {row.live_overdue} {t("hot.overdue")}
                          </span>
                        )}
                        <span className="text-[15px] font-700 text-ink tabular w-14 text-right">
                          {measure === "volume" ? value : `${Math.round(value)}%`}
                        </span>
                      </span>
                    </div>
                    <div className="h-2.5 bg-surface-sunk rounded-chip overflow-hidden">
                      <div
                        className="h-full rounded-chip bg-rose transition-[width] duration-500"
                        style={{
                          width: `${Math.max(width, 1.5)}%`,
                          transitionTimingFunction: "cubic-bezier(0.16,1,0.3,1)",
                          transitionDelay: `${Math.min(index, 10) * 30}ms`,
                        }}
                      />
                    </div>
                  </button>

                  {expanded && (
                    <div className="px-4 pb-4 pt-1 bg-surface-sunk">
                      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                        <Cell
                          label={t("hot.recorded")}
                          value={row.historical_total + row.live_total}
                        />
                        <Cell label={t("hot.openNow")} value={row.live_open} />
                        <Cell
                          label={t("hot.overdue")}
                          value={row.live_overdue}
                          tone={row.live_overdue > 0 ? "amber" : undefined}
                        />
                        <Cell
                          label={t("hot.sensitive")}
                          value={row.sensitive_cases}
                          tone={
                            typeof row.sensitive_cases === "string"
                              ? "rose"
                              : undefined
                          }
                        />
                      </dl>
                      <div className="text-[12px] font-700 text-ink-3 mb-2">
                        {t("hot.mostReported")}
                      </div>
                      <ul className="space-y-1">
                        {row.top_categories.map((category, i) => (
                          <li
                            key={i}
                            className={`text-[14px] ${
                              category.suppressed ? "text-rose" : "text-ink-2"
                            }`}
                          >
                            <span className="tabular font-600">
                              {category.count}
                            </span>{" "}
                            · {category.label}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {/* Table view: the exact figures, and identity is never colour-alone. */}
      {rows.length > 0 && (
        <Reveal>
          <h2 className="text-[19px] font-700 mb-4">{t("hot.table")}</h2>
          <div className="card overflow-x-auto">
            <table className="w-full text-[14px] border-collapse min-w-[560px]">
              <thead>
                <tr className="border-b border-line">
                  <th className="text-left py-3 px-4 text-[12px] font-700 text-ink-3 uppercase tracking-[0.06em]">
                    {t("hot.col.taluka")}
                  </th>
                  {[
                    t("hot.recorded"),
                    t("hot.openNow"),
                    t("hot.overdue"),
                    t("hot.pastSla"),
                    t("hot.sensitive"),
                  ].map((head) => (
                    <th
                      key={head}
                      className="text-right py-3 px-4 text-[12px] font-700 text-ink-3 uppercase tracking-[0.06em] whitespace-nowrap"
                    >
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.taluka} className="border-b border-line-soft last:border-0">
                    <td className="py-3 px-4 font-600 text-ink">{row.taluka}</td>
                    <td className="py-3 px-4 text-right text-ink-2 tabular">
                      {row.historical_total + row.live_total}
                    </td>
                    <td className="py-3 px-4 text-right text-ink-2 tabular">
                      {row.live_open}
                    </td>
                    <td
                      className={`py-3 px-4 text-right tabular ${row.live_overdue > 0 ? "text-ink font-700" : "text-ink-3"}`}
                    >
                      {row.live_overdue}
                    </td>
                    <td className="py-3 px-4 text-right text-ink-2 tabular">
                      {row.historical_breach_rate !== null
                        ? `${Math.round(row.historical_breach_rate * 100)}%`
                        : "—"}
                    </td>
                    <td className="py-3 px-4 text-right text-ink-2 tabular">
                      {row.sensitive_cases}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
      )}

      {data && (
        <p className="text-[13px] text-ink-3 leading-relaxed mt-8 max-w-[70ch] border-l-2 border-line pl-4">
          {data.privacy.note} {t("hot.notMap")}
        </p>
      )}
    </div>
  );
}

function Cell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "amber" | "rose";
}) {
  const colour =
    tone === "amber"
      ? "text-ink bg-amber-tint px-1.5"
      : tone === "rose"
        ? "text-rose"
        : "text-ink";
  return (
    <div className="card px-3 py-2.5">
      <dt className="text-[12px] text-ink-3 font-600 mb-0.5">{label}</dt>
      <dd className={`${colour} text-[15px] font-700 tabular`}>{value}</dd>
    </div>
  );
}
