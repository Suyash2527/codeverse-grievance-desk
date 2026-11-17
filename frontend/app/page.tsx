"use client";

/**
 * The entry page.
 *
 * Not a marketing hero: this is the front counter of a district office. The
 * first screen has to say what the service does, let a citizen start in one
 * tap, and make the constraints visible — because on this project the
 * constraints are the product.
 *
 * The only ambient effect is a soft teal wash behind the heading, drawn from
 * the palette. No blobs, no gradient text, no floating shapes.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import { useLang } from "@/components/lang";
import { Figure, Reveal, Step } from "@/components/ui";
import { API_BASE } from "@/lib/api";
import { channelText } from "@/lib/channel-i18n";

type Health = { categories_loaded: number; departments_loaded: number };

const REFUSALS = [
  {
    rule: "Never auto-closes a sensitive case",
    detail: "Enforced at the write, not in a prompt",
  },
  {
    rule: "Never rejects a grievance",
    detail: "Automated actors have a status allow-list",
  },
  {
    rule: "Never rules on liability",
    detail: "That authority belongs to a human officer",
  },
  {
    rule: "Never merges duplicates silently",
    detail: "Every grievance keeps its own reference number",
  },
  {
    rule: "Never contacts a real address",
    detail: "Every destination is a placeholder",
  },
];

export default function Home() {
  const { t, lang } = useLang();
  const [health, setHealth] = useState<Health | null>(null);
  const [rules, setRules] = useState<{ passed: number; total: number } | null>(
    null,
  );

  useEffect(() => {
    fetch(`${API_BASE}/api/health`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => setHealth(null));
    fetch(`${API_BASE}/api/compliance/rules`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setRules({ passed: d.passed, total: d.total }))
      .catch(() => setRules(null));
  }, []);

  return (
    <div>
      {/* ---------------------------------------------- hero ---------- */}
      <section className="relative overflow-hidden">
        <div className="hero-wash" aria-hidden />
        <div className="relative mx-auto max-w-[1180px] px-5 md:px-6 pt-12 md:pt-20 pb-12">
          <div className="grid lg:grid-cols-[1.25fr_1fr] gap-10 lg:gap-16 items-start">
            <div>
              <span className="eyebrow quiet-in block mb-4">
                {t("app.subtitle")}
              </span>
              <h1
                className="mb-6 max-w-[16ch] quiet-in"
                style={{ ["--delay" as string]: 60 }}
              >
                {t("home.title")}
              </h1>
              <p
                className="text-[17px] md:text-[19px] leading-[1.65] text-ink-2 max-w-[56ch] mb-8 quiet-in"
                style={{ ["--delay" as string]: 120 }}
              >
{t("home.lead")}
              </p>

              <div
                className="flex flex-col sm:flex-row gap-3 quiet-in"
                style={{ ["--delay" as string]: 180 }}
              >
                <Link
                  href="/citizen"
                  className="group pressable inline-flex items-center justify-center gap-2 px-7 py-4 rounded-chip bg-teal text-ink border-2 border-ink text-[16px] font-700 hover:bg-teal-deep"
                >
                  {t("nav.file")}
                  <span className="arrow-travel" aria-hidden>
                    →
                  </span>
                </Link>
                <Link
                  href="/officer"
                  className="pressable inline-flex items-center justify-center px-7 py-4 rounded-chip border border-line bg-surface-card text-ink text-[16px] font-700 hover:border-line-strong"
                >
                  {t("nav.queue")}
                </Link>
              </div>

              {/* MVP preview of the other ways in */}
              <Link
                href="/channels"
                className="group pressable mt-4 inline-flex items-center gap-2 text-[15px] font-600 text-ink quiet-in"
                style={{ ["--delay" as string]: 210 }}
              >
                <span className="link-underline">{channelText(lang, "entry.wa")} · {channelText(lang, "entry.call")}</span>
                <span className="rounded-chip border-2 border-ink bg-teal px-2 py-0.5 text-[11px] font-700">
                  {channelText(lang, "badge")}
                </span>
                <span className="arrow-travel" aria-hidden>→</span>
              </Link>

              {/* A live strip, not a claim: these numbers come from the API. */}
              <div
                className="flex flex-wrap gap-8 sm:gap-12 mt-10 pt-8 border-t border-line quiet-in"
                style={{ ["--delay" as string]: 240 }}
              >
                <Figure
                  value={health?.categories_loaded ?? "–"}
                  label="Categories loaded from CSV"
                />
                <Figure
                  value={health?.departments_loaded ?? "–"}
                  label="Departments routed"
                />
                <Figure
                  value={rules ? `${rules.passed}/${rules.total}` : "–"}
                  label="Safety rules enforced"
                  tone="teal"
                />
              </div>
            </div>

            {/* What the system will not do. */}
            <Reveal className="lg:pt-10">
              <aside className="card overflow-hidden">
                <div className="px-5 py-4 border-b border-line flex items-baseline justify-between gap-3">
                  <h2 className="text-[15px] font-700 text-ink">
                    {t("home.refuses")}
                  </h2>
                  <Link
                    href="/compliance"
                    className="group text-[13px] font-600 text-ink whitespace-nowrap"
                  >
                    <span className="link-underline">{t("home.proved")}</span>{" "}
                    <span className="arrow-travel" aria-hidden>
                      →
                    </span>
                  </Link>
                </div>
                <ul className="divide-y divide-line-soft">
                  {REFUSALS.map((item) => (
                    <li key={item.rule} className="px-5 py-3.5">
                      <div className="text-[15px] font-600 text-ink mb-0.5">
                        {item.rule}
                      </div>
                      <div className="text-[13px] text-ink-3">
                        {item.detail}
                      </div>
                    </li>
                  ))}
                </ul>
              </aside>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ------------------------------------------- how it works ------ */}
      <section className="mx-auto max-w-[1180px] px-5 md:px-6 py-12 md:py-20">
        <div className="grid lg:grid-cols-[1fr_1.1fr] gap-10 lg:gap-20">
          <Reveal>
            <div className="lg:sticky lg:top-24">
              <span className="eyebrow block mb-3">{t("home.flowEyebrow")}</span>
              <h2 className="mb-4 max-w-[14ch]">
{t("home.flowTitle")}
              </h2>
              <p className="text-[16px] text-ink-2 leading-relaxed max-w-[48ch]">
{t("home.flowLead")}
              </p>
            </div>
          </Reveal>

          <Reveal delay={80}>
            <ol>
              <Step
                n={1}
                title="Intake"
                body="Turns speech or text in Marathi, Hindi or English into a structured draft, and asks for what is missing. Nothing is filed until the citizen confirms what they are about to submit."
              />
              <Step
                n={2}
                title="Retrieval"
                body="Finds comparable past cases from the district's own 800 records and passes them on as evidence with a rationale. It never decides the outcome."
              />
              <Step
                n={3}
                title="Policy gate"
                body="Reads the Sensitive and Identity-Hiding flags and the confidence threshold from the category table, and returns either automated resolution or the human queue, with the exact rule that applied."
              />
              <Step
                n={4}
                title="Decision"
                body="Routes to the responsible department and composes priority from severity, urgency and affected population — never from how many times something was reported."
              />
              <Step
                n={5}
                title="Action"
                body="Updates the case, fires the department webhook and records the citizen's update. Every write passes the guards a second time."
                last
              />
            </ol>
          </Reveal>
        </div>
      </section>

      {/* ------------------------------------------------ desks -------- */}
      <section className="mx-auto max-w-[1180px] px-5 md:px-6 pb-16 md:pb-24">
        <div className="grid sm:grid-cols-3 gap-4">
          {[
            {
              href: "/citizen",
              title: t("nav.file"),
              body: "Chat intake with voice, a draft you confirm, and a reference number you keep.",
            },
            {
              href: "/officer",
              title: t("nav.queue"),
              body: "Triage by urgency, with the policy rule, the evidence and the confidence behind every case.",
            },
            {
              href: "/compliance",
              title: t("nav.rules"),
              body: "The safety contract, executed live against the running policy module.",
            },
          ].map((desk, i) => (
            <Reveal key={desk.href} delay={i * 70}>
              <Link
                href={desk.href}
                className="group card card-interactive block p-6 h-full"
              >
                <h3 className="text-[17px] font-700 text-ink mb-2 flex items-center gap-2">
                  {desk.title}
                  <span className="arrow-travel text-ink" aria-hidden>
                    →
                  </span>
                </h3>
                <p className="text-[14px] text-ink-2 leading-relaxed">
                  {desk.body}
                </p>
              </Link>
            </Reveal>
          ))}
        </div>
      </section>
    </div>
  );
}
