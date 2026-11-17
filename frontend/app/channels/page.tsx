"use client";

/**
 * MVP preview of the WhatsApp and phone-call channels.
 *
 * Scripted on purpose for round 1: the phones play a fixed conversation and
 * nothing is sent, dialled or filed. The point is to show judges how a
 * citizen without the website reaches the same agent and the same rules.
 */
import Link from "next/link";

import { CallPreview, WhatsAppPreview } from "@/components/channel-preview";
import { useLang } from "@/components/lang";
import { channelText } from "@/lib/channel-i18n";

export default function ChannelsPage() {
  const { lang } = useLang();
  const c = (key: string) => channelText(lang, key);

  return (
    <div className="mx-auto max-w-[1180px] px-5 md:px-6 py-8 md:py-14">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <span className="eyebrow">{c("page.eyebrow")}</span>
        <span className="inline-flex items-center rounded-chip border-2 border-ink bg-teal px-3 py-1 text-[12px] font-700 text-ink">
          {c("badge")}
        </span>
      </div>
      <h1 className="mb-4 max-w-[18ch]">{c("page.title")}</h1>
      <p className="text-[17px] leading-[1.65] text-ink-2 max-w-[62ch] mb-3">{c("page.lead")}</p>
      <p className="text-[14px] text-ink-3 max-w-[62ch] mb-10">{c("page.note")}</p>

      <div className="grid gap-12 md:grid-cols-2 md:gap-10 items-start">
        <section aria-label={c("wa.title")}>
          <p className="text-[15px] text-ink-2 mb-5 max-w-[42ch] mx-auto text-center">{c("wa.lead")}</p>
          <WhatsAppPreview />
        </section>
        <section aria-label={c("call.title")}>
          <p className="text-[15px] text-ink-2 mb-5 max-w-[42ch] mx-auto text-center">{c("call.lead")}</p>
          <CallPreview />
        </section>
      </div>

      <div className="mt-14 card p-6 md:p-8 grid gap-6 md:grid-cols-3">
        {[
          ["Same intake agent", "The channel only changes how words arrive. Drafting, confirmation and filing are the web flow’s own steps."],
          ["Same eight rules", "A sensitive case from WhatsApp is held for a human exactly like one typed on the website."],
          ["Round 2", "Meta WhatsApp Cloud API and a voice provider behind the same adapter, with Sarvam for Marathi and Hindi speech."],
        ].map(([title, body]) => (
          <div key={title}>
            <h2 className="text-[18px] font-700 mb-1.5">{title}</h2>
            <p className="text-[14px] text-ink-2 leading-relaxed">{body}</p>
          </div>
        ))}
      </div>

      <div className="mt-10">
        <Link href="/citizen" className="group pressable inline-flex items-center gap-2 text-[16px] font-600 text-ink">
          <span className="link-underline">File on the website instead</span>
          <span className="arrow-travel" aria-hidden>→</span>
        </Link>
      </div>
    </div>
  );
}
