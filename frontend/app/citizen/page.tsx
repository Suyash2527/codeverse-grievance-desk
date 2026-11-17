"use client";

/**
 * The citizen desk: write or speak a grievance, check the draft, file it.
 *
 * Design note: this is the same ledger, warmer. The officer screen is a
 * triage tool; this one is a counter you are standing at. Wider measure,
 * larger text, one action visible at a time, and the draft shown in full
 * before anything is filed — nobody should discover what was submitted in
 * their name after the fact.
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { LanguageSwitch, useLang } from "@/components/lang";
import { AiMark } from "@/components/marks";
import { VoiceButton } from "@/components/voice";
import { channelText } from "@/lib/channel-i18n";
import {
  ApiError,
  api,
  type IntakeCapabilities,
  type IntakeReply,
  type IntakeTurn,
} from "@/lib/api";

const COPY = {
  en: {
    eyebrow: "Citizen desk",
    title: "File a grievance",
    lead: "Write or speak in your own language. Nothing is filed until you confirm the draft.",
    placeholder: "Describe the problem and where it is happening…",
    send: "Send",
    draft: "Draft for your confirmation",
    confirm: "Yes, file this grievance",
    edit: "No, let me add more",
    filed: "Your grievance has been filed",
    track: "Track a grievance",
    nameLabel: "Your name (optional)",
    phoneLabel: "Phone (optional)",
    category: "Category",
    place: "Place",
    urgency: "Urgency",
    listening: "Listening…",
    speak: "Speak instead",
  },
  hi: {
    eyebrow: "नागरिक डेस्क",
    title: "शिकायत दर्ज करें",
    lead: "अपनी भाषा में लिखें या बोलें। पुष्टि करने तक कुछ भी दर्ज नहीं होगा।",
    placeholder: "समस्या और उसका स्थान बताइए…",
    send: "भेजें",
    draft: "आपकी पुष्टि के लिए मसौदा",
    confirm: "हाँ, यह शिकायत दर्ज करें",
    edit: "नहीं, मुझे और जोड़ना है",
    filed: "आपकी शिकायत दर्ज हो गई है",
    track: "शिकायत ट्रैक करें",
    nameLabel: "आपका नाम (वैकल्पिक)",
    phoneLabel: "फ़ोन (वैकल्पिक)",
    category: "श्रेणी",
    place: "स्थान",
    urgency: "तात्कालिकता",
    listening: "सुन रहे हैं…",
    speak: "बोलकर बताएं",
  },
  mr: {
    eyebrow: "नागरिक कक्ष",
    title: "तक्रार नोंदवा",
    lead: "आपल्या भाषेत लिहा किंवा बोला. पुष्टी केल्याशिवाय काहीही नोंदवले जाणार नाही.",
    placeholder: "समस्या आणि ठिकाण सांगा…",
    send: "पाठवा",
    draft: "आपल्या पुष्टीसाठी मसुदा",
    confirm: "होय, ही तक्रार नोंदवा",
    edit: "नाही, आणखी माहिती द्यायची आहे",
    filed: "आपली तक्रार नोंदवली गेली आहे",
    track: "तक्रार तपासा",
    nameLabel: "आपले नाव (ऐच्छिक)",
    phoneLabel: "दूरध्वनी (ऐच्छिक)",
    category: "श्रेणी",
    place: "ठिकाण",
    urgency: "निकड",
    listening: "ऐकत आहोत…",
    speak: "बोलून सांगा",
  },
} as const;

type LanguageCode = keyof typeof COPY;

export default function CitizenPage() {
  const { lang } = useLang();
  const language = lang as LanguageCode;
  const [capabilities, setCapabilities] = useState<IntakeCapabilities | null>(null);
  const [reply, setReply] = useState<IntakeReply | null>(null);
  const [turns, setTurns] = useState<IntakeTurn[]>([]);
  const [text, setText] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [filed, setFiled] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const copy = COPY[language];

  useEffect(() => {
    void api.capabilities().then(setCapabilities).catch(() => setCapabilities(null));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, filed]);

  const send = useCallback(
    async (message: string, source: "text" | "voice") => {
      if (!message.trim()) return;
      setBusy(true);
      setError(null);
      try {
        const next = await api.sendMessage({
          text: message,
          language,
          session_key: reply?.session_key,
          source,
        });
        setReply(next);
        setTurns(next.transcript);
        setText("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "could not reach the service");
      } finally {
        setBusy(false);
      }
    },
    [language, reply?.session_key],
  );

  async function fileIt() {
    if (!reply) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.confirmDraft(reply.session_key, {
        citizen_name: name || undefined,
        citizen_phone: phone || undefined,
      });
      setFiled(result.reference_no);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "the grievance could not be filed",
      );
    } finally {
      setBusy(false);
    }
  }

  const draft = reply?.draft as Record<string, string> | undefined;

  return (
    <div className="mx-auto max-w-[760px] px-5 md:px-6 py-8 md:py-14">
      <div className="flex items-start justify-between gap-6 mb-8">
        <div>
          <div className="eyebrow mb-3">{copy.eyebrow}</div>
          <h1 className="text-4xl sm:text-5xl text-ink mb-4">{copy.title}</h1>
          <p className="text-[16px] leading-[1.7] text-ink-2 max-w-[52ch]">
            {copy.lead}
          </p>
        </div>
        <Link
          href="/track"
          className="pressable shrink-0 text-[13px] text-ink-2 border border-line-strong rounded-card px-3 py-1.5 hover:text-ink"
        >
          {copy.track}
        </Link>
      </div>

      {/* The shared switch: the choice follows the citizen across the site. */}
      <div className="mb-4">
        <LanguageSwitch />
      </div>

      {/* The other ways in: a preview of the WhatsApp and phone channels. */}
      <Link
        href="/channels"
        className="pressable group mb-7 flex items-center justify-between gap-3 rounded-card border-2 border-ink px-4 py-3 hover:bg-surface-sunk"
      >
        <span className="text-[14px] text-ink">
          <span className="font-700">{channelText(lang, "entry.title")}</span>
          <span className="text-ink-3"> · {channelText(lang, "badge")}</span>
        </span>
        <span className="arrow-travel text-ink" aria-hidden>→</span>
      </Link>

      {capabilities && !capabilities.translation_available && (
        <p className="text-[14px] text-ink-2 border border-amber/30 bg-amber-tint rounded-card p-4 mb-8 leading-relaxed">
          No language model is configured in this demo, so Marathi and Hindi
          complaints are routed to a human officer instead of being classified
          automatically. Voice input is unavailable.
        </p>
      )}

      {/* Conversation */}
      {turns.length > 0 && (
        <div className="space-y-4 mb-8">
          {turns.map((turn, index) => (
            <div
              key={index}
              className={`quiet-in flex ${turn.role === "citizen" ? "justify-end" : "justify-start"}`}
              style={{ ["--delay" as string]: Math.min(index, 6) * 40 }}
            >
              <div
                className={`max-w-[85%] rounded-card px-4 py-3 text-[15px] leading-relaxed ${
                  turn.role === "citizen"
                    ? "bg-surface-sunk text-ink border border-line"
                    : "border-l-2 border-teal bg-surface-card text-ink-2 pl-5"
                }`}
              >
                {turn.text}
                {turn.source === "voice" && (
                  <span className="eyebrow ml-3 align-middle">voice</span>
                )}
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>
      )}

      {/* The draft, shown in full before anything is filed */}
      {reply?.ready_to_confirm && draft && !filed && (
        <section className="stamp border border-teal rounded-card p-6 mb-8 bg-teal-tint/40">
          <div className="flex items-center gap-3 mb-5">
            <span className="eyebrow">{copy.draft}</span>
            <AiMark model={reply.model} />
          </div>
          <p className="text-[16px] text-ink leading-[1.6] mb-5">
            {draft.description}
          </p>
          <dl className="grid grid-cols-2 sm:grid-cols-3 gap-5 mb-6">
            <div>
              <dt className="eyebrow mb-1">{copy.category}</dt>
              <dd className="ref text-[13px] text-ink">{draft.category_id}</dd>
            </div>
            <div>
              <dt className="eyebrow mb-1">{copy.place}</dt>
              <dd className="text-[13px] text-ink">
                {[draft.locality, draft.taluka].filter(Boolean).join(", ") || "—"}
              </dd>
            </div>
            <div>
              <dt className="eyebrow mb-1">{copy.urgency}</dt>
              <dd className="text-[13px] text-ink">{draft.urgency ?? "—"}</dd>
            </div>
          </dl>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-5">
            <label className="block">
              <span className="eyebrow block mb-1.5">{copy.nameLabel}</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full bg-surface-page border border-line-strong rounded-card px-3 py-2 text-[14px] text-ink focus:border-teal outline-none"
              />
            </label>
            <label className="block">
              <span className="eyebrow block mb-1.5">{copy.phoneLabel}</span>
              <input
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                className="w-full bg-surface-page border border-line-strong rounded-card px-3 py-2 text-[14px] text-ink focus:border-teal outline-none"
              />
            </label>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              onClick={() => void fileIt()}
              disabled={busy}
              className="pressable px-6 py-3.5 rounded-chip bg-teal text-ink border-2 border-ink text-[16px] font-600 hover:bg-teal-deep disabled:opacity-50"
            >
              {copy.confirm}
            </button>
            <button
              onClick={() => endRef.current?.scrollIntoView()}
              className="pressable px-6 py-3.5 rounded-chip border border-line bg-surface-card text-ink-2 text-[16px] font-500 hover:text-ink hover:border-line-strong"
            >
              {copy.edit}
            </button>
          </div>
        </section>
      )}

      {/* Filed */}
      {filed && (
        <section className="border border-teal rounded-card p-6 mb-8 bg-teal-tint/40 quiet-in">
          <div className="eyebrow mb-3">{copy.filed}</div>
          <div className="ref text-2xl text-ink mb-4">{filed}</div>
          <Link
            href={`/track?ref=${filed}`}
            className="pressable inline-block text-[14px] text-ink border-b border-teal hover:border-teal"
          >
            {copy.track} →
          </Link>
        </section>
      )}

      {error && (
        <p className="text-[13px] text-rose border border-ink bg-rose-tint rounded-card p-3 mb-6">
          {error}
        </p>
      )}

      {/* Composer */}
      {!filed && (
        <div className="mt-6 md:sticky md:bottom-0 z-20 bg-surface-page pt-3 pb-3">
          <div className="card p-3">
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.repeat) {
                  event.preventDefault();
                  void send(text, "text");
                }
              }}
              rows={3}
              placeholder={copy.placeholder}
              className="w-full bg-surface-card rounded-card px-3 py-2 text-[16px] text-ink placeholder:text-ink-3 outline-none resize-none mb-2"
            />
            <div className="flex items-center gap-2">
              <VoiceButton
                language={language}
                available={capabilities?.voice_available ?? false}
                label={copy.speak}
                listeningLabel={copy.listening}
                onTranscript={(transcript) => void send(transcript, "voice")}
                onError={setError}
              />
              <button
                onClick={() => void send(text, "text")}
                disabled={busy || !text.trim()}
                className="pressable ml-auto px-7 py-3 rounded-chip bg-teal text-ink border-2 border-ink text-[16px] font-700 hover:bg-teal-deep disabled:opacity-40"
              >
                {copy.send}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
