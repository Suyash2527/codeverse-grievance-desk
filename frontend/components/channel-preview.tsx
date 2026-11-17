"use client";

/**
 * Scripted previews of the WhatsApp and phone-call channels (MVP).
 *
 * Deliberately NOT wired to the backend: nothing is sent, dialled or filed.
 * Each phone plays a fixed script in the selected language so the judges see
 * the full experience. The live integration (same intake agent, Sarvam
 * speech) is planned for round 2.
 *
 * Every step is plain text on screen, so the preview also reads as captions
 * and works with sound off. Reduced-motion users get the finished
 * conversation at once instead of a timed playback.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useLang } from "@/components/lang";
import { channelText } from "@/lib/channel-i18n";

const DEMO_REFERENCE = "GRV-DEMO-0001";
const DIGIT_FOR_LANG = { mr: "1", hi: "2", en: "3" } as const;

function prefersReducedMotion() {
  return typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Runs a list of timed steps; returns play() and whether it is running. */
function useScript<T>(build: () => { delay: number; item: T }[]) {
  const [items, setItems] = useState<T[]>([]);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const timers = useRef<number[]>([]);

  const clear = () => {
    timers.current.forEach((id) => window.clearTimeout(id));
    timers.current = [];
  };

  const play = useCallback(() => {
    clear();
    const steps = build();
    if (prefersReducedMotion()) {
      setItems(steps.map((s) => s.item));
      setRunning(false);
      setDone(true);
      return;
    }
    setItems([]);
    setDone(false);
    setRunning(true);
    let at = 0;
    steps.forEach((step, index) => {
      at += step.delay;
      timers.current.push(
        window.setTimeout(() => {
          setItems((prev) => [...prev, step.item]);
          if (index === steps.length - 1) {
            setRunning(false);
            setDone(true);
          }
        }, at),
      );
    });
  }, [build]);

  useEffect(() => clear, []);
  return { items, running, done, play, setItems };
}

/* ------------------------------------------------------------ WhatsApp -- */

type WaItem =
  | { kind: "bot"; text: string }
  | { kind: "me"; text: string }
  | { kind: "typing" }
  | { kind: "draft" }
  | { kind: "filed" };

export function WhatsAppPreview() {
  const { lang, t } = useLang();
  const c = useCallback((key: string) => channelText(lang, key), [lang]);

  const build = useCallback(
    (): { delay: number; item: WaItem }[] => [
      { delay: 0, item: { kind: "bot", text: c("wa.greeting") } },
      { delay: 1300, item: { kind: "me", text: c("complaint") } },
      { delay: 700, item: { kind: "typing" } },
      { delay: 1400, item: { kind: "draft" } },
      { delay: 2600, item: { kind: "me", text: "1" } },
      { delay: 700, item: { kind: "typing" } },
      { delay: 1300, item: { kind: "filed" } },
      { delay: 1500, item: { kind: "bot", text: c("wa.sensitive") } },
    ],
    [c],
  );
  const { items, running, done, play, setItems } = useScript(build);

  // show the greeting before anyone presses play, and refresh on language change
  useEffect(() => {
    setItems([{ kind: "bot", text: c("wa.greeting") }]);
  }, [c, setItems]);

  const feed = useRef<HTMLDivElement>(null);
  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: "smooth" });
  }, [items]);

  // a typing indicator is only shown while it is the latest item
  const visible = items.filter(
    (item, i) => item.kind !== "typing" || i === items.length - 1,
  );

  return (
    <PhoneFrame label={c("wa.title")}>
      <div className="flex items-center gap-3 bg-ink text-surface-card px-4 py-3">
        <span className="w-9 h-9 rounded-chip bg-teal text-ink grid place-items-center font-700 text-[15px]">
          G
        </span>
        <div className="min-w-0">
          <div className="text-[15px] font-600 leading-tight truncate">{c("wa.contact")}</div>
          <div className="text-[12px] opacity-75 leading-tight">
            {running && items[items.length - 1]?.kind === "typing" ? c("wa.thinking") : c("wa.status")}
          </div>
        </div>
      </div>

      <div ref={feed} className="flex-1 overflow-y-auto px-3 py-4 space-y-2.5 bg-surface-sunk" aria-live="polite">
        {visible.map((item, i) => {
          if (item.kind === "typing") return <TypingBubble key={i} />;
          if (item.kind === "me") {
            return (
              <div key={i} className="flex justify-end quiet-in">
                <div className="max-w-[82%] rounded-[14px] rounded-br-[4px] bg-teal text-ink border-2 border-ink px-3 py-2 text-[14px] leading-snug">
                  {item.text}
                  <span className="flex justify-end mt-1"><Ticks /></span>
                </div>
              </div>
            );
          }
          if (item.kind === "draft") {
            return (
              <BotBubble key={i}>
                <div className="eyebrow mb-1.5">{c("wa.draft")} <span className="text-ink-3 normal-case tracking-normal">· AI</span></div>
                <p className="text-[14px] text-ink mb-2">{c("complaint")}</p>
                <dl className="grid grid-cols-2 gap-1 text-[12px] mb-2">
                  <dt className="text-ink-3">{c("wa.place")}</dt>
                  <dd className="text-ink font-600">Loha</dd>
                  <dt className="text-ink-3">{c("wa.urgency")}</dt>
                  <dd className="text-rose font-600">{t("priority.CRITICAL")}</dd>
                </dl>
                <p className="text-[13px] text-ink-2 mb-2">{c("wa.confirmHint")}</p>
                <div className="grid grid-cols-2 gap-1.5">
                  <span className="text-center text-[13px] font-600 rounded-chip border-2 border-ink bg-teal py-1.5">{c("wa.file")}</span>
                  <span className="text-center text-[13px] font-600 rounded-chip border border-ink py-1.5">{c("wa.change")}</span>
                </div>
              </BotBubble>
            );
          }
          if (item.kind === "filed") {
            return (
              <BotBubble key={i}>
                <p className="text-[14px] text-ink mb-1">{c("wa.filed")}</p>
                <p className="ref text-[16px] font-600 text-ink mb-1">{DEMO_REFERENCE}</p>
                <p className="text-[12px] text-ink-3">{c("wa.trackHint")}</p>
              </BotBubble>
            );
          }
          return (
            <BotBubble key={i}>
              <p className="text-[14px] text-ink leading-snug">{item.text}</p>
            </BotBubble>
          );
        })}
      </div>

      <div className="flex items-center gap-2 px-3 py-2.5 border-t-2 border-ink bg-surface-card">
        <div className="flex-1 rounded-chip border border-line-strong px-4 py-2 text-[14px] text-ink-3 truncate">
          {c("wa.placeholder")}
        </div>
        <span className="w-10 h-10 rounded-chip bg-ink text-surface-card grid place-items-center" aria-hidden>
          <IconSend />
        </span>
      </div>

      <PlayBar running={running} done={done} onPlay={play} label={running ? c("playing") : done ? c("replay") : c("play")} />
    </PhoneFrame>
  );
}

function BotBubble({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex justify-start quiet-in">
      <div className="max-w-[86%] rounded-[14px] rounded-bl-[4px] bg-surface-card border-2 border-ink px-3 py-2.5">
        {children}
      </div>
    </div>
  );
}

function TypingBubble() {
  return (
    <div className="flex justify-start">
      <div className="rounded-[14px] rounded-bl-[4px] bg-surface-card border-2 border-ink px-3 py-3 flex gap-1.5" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className="w-2 h-2 rounded-chip bg-ink-3 animate-pulse" style={{ animationDelay: `${i * 160}ms` }} />
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------- phone call -- */

type CallItem =
  | { kind: "status"; status: "ringing" | "connected" | "ended" }
  | { kind: "ivr"; text: string }
  | { kind: "you"; text: string }
  | { kind: "key"; digit: string };

export function CallPreview() {
  const { lang, t } = useLang();
  const c = useCallback((key: string) => channelText(lang, key), [lang]);
  const digit = DIGIT_FOR_LANG[lang as keyof typeof DIGIT_FOR_LANG] ?? "3";

  const build = useCallback(
    (): { delay: number; item: CallItem }[] => [
      { delay: 0, item: { kind: "status", status: "ringing" } },
      { delay: 1600, item: { kind: "status", status: "connected" } },
      { delay: 300, item: { kind: "ivr", text: c("call.welcome") } },
      {
        delay: 1700,
        item: { kind: "ivr", text: [c("call.menu.mr"), c("call.menu.hi"), c("call.menu.en")].join("\n") },
      },
      { delay: 2400, item: { kind: "key", digit } },
      { delay: 900, item: { kind: "ivr", text: c("call.prompt") } },
      { delay: 2400, item: { kind: "you", text: c("complaint") } },
      {
        delay: 2600,
        item: {
          kind: "ivr",
          text: `${c("call.understood")} ${c("complaint")} ${c("call.place")} Loha. ${c("call.urgency")} ${t("priority.CRITICAL")}.`,
        },
      },
      { delay: 3200, item: { kind: "ivr", text: c("call.confirm") } },
      { delay: 1800, item: { kind: "key", digit: "1" } },
      { delay: 900, item: { kind: "ivr", text: `${c("call.filed")} ${spell(DEMO_REFERENCE)}.` } },
      { delay: 2600, item: { kind: "ivr", text: c("wa.sensitive") } },
      { delay: 2400, item: { kind: "ivr", text: c("call.bye") } },
      { delay: 1500, item: { kind: "status", status: "ended" } },
    ],
    [c, digit, t],
  );
  const { items, running, done, play } = useScript(build);

  const statuses = items.filter((i): i is Extract<CallItem, { kind: "status" }> => i.kind === "status");
  // before Play there is no status item yet; that is the idle screen
  const status = (statuses.length ? statuses[statuses.length - 1].status : "idle") as
    | "idle"
    | "ringing"
    | "connected"
    | "ended";
  const lines = items.filter((i) => i.kind === "ivr" || i.kind === "you" || i.kind === "key");
  const lastKey = [...items].reverse().find((i): i is Extract<CallItem, { kind: "key" }> => i.kind === "key");
  const latest = items[items.length - 1];
  const speaking = running && latest && (latest.kind === "ivr" || latest.kind === "you") ? latest.kind : null;

  const seconds = useCallTimer(status === "connected");

  const feed = useRef<HTMLOListElement>(null);
  useEffect(() => {
    feed.current?.scrollTo({ top: feed.current.scrollHeight, behavior: "smooth" });
  }, [items]);

  return (
    <PhoneFrame label={c("call.title")} dark>
      <div className="text-center px-5 pt-6 pb-4 text-surface-card">
        <div className="mx-auto mb-3 w-16 h-16 rounded-chip border-2 border-surface-card grid place-items-center">
          <IconPhone />
        </div>
        <div className="text-[17px] font-600">{c("call.name")}</div>
        <div className="text-[13px] opacity-70">{c("call.number")}</div>
        <div className="mt-2 text-[13px] font-600 text-teal tabular" aria-live="polite">
          {status === "idle" && " "}
          {status === "ringing" && c("call.ringing")}
          {status === "connected" && `${c("call.connected")} · ${formatTime(seconds)}`}
          {status === "ended" && c("call.ended")}
        </div>
        <Waveform active={speaking} />
      </div>

      <div className="flex-1 min-h-0 mx-3 mb-3 rounded-[14px] bg-surface-card border-2 border-surface-card flex flex-col">
        <div className="eyebrow px-3 pt-2.5 pb-1">{c("call.captions")}</div>
        <ol ref={feed} className="flex-1 overflow-y-auto px-3 pb-3 space-y-2" aria-live="polite">
          {lines.length === 0 && (
            <li className="text-[13px] text-ink-3 pt-1">{c("call.lead")}</li>
          )}
          {lines.map((line, i) => (
            <li key={i} className="quiet-in text-[13px] leading-snug">
              {line.kind === "key" ? (
                <span className="inline-flex items-center gap-1.5 text-ink-3">
                  <span className="ref inline-grid place-items-center w-6 h-6 rounded-chip bg-teal text-ink border-2 border-ink font-700">
                    {line.digit}
                  </span>
                  {c("call.pressed")}
                </span>
              ) : (
                <>
                  <span className={`font-700 ${line.kind === "you" ? "text-ink" : "text-rose"}`}>
                    {line.kind === "you" ? c("call.you") : c("call.ivr")}:{" "}
                  </span>
                  <span className="text-ink whitespace-pre-line">{line.text}</span>
                </>
              )}
            </li>
          ))}
        </ol>
      </div>

      <Keypad active={running ? lastKey?.digit : undefined} label={c("call.keypad")} />

      <PlayBar
        running={running}
        done={done}
        onPlay={play}
        label={running ? c("call.end") : done ? c("replay") : c("call.start")}
        dark
      />
    </PhoneFrame>
  );
}

function useCallTimer(on: boolean) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (!on) return;
    setSeconds(0);
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [on]);
  return seconds;
}

function formatTime(total: number) {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** How an IVR reads a reference out: one character at a time. */
function spell(reference: string) {
  return reference.split("").filter((ch) => ch !== "-").join(" ");
}

function Waveform({ active }: { active: "ivr" | "you" | null }) {
  return (
    <div className="mt-3 h-6 flex items-end justify-center gap-1" aria-hidden>
      {Array.from({ length: 11 }).map((_, i) => (
        <span
          key={i}
          className={`w-1 rounded-chip transition-all duration-300 ${
            active ? (active === "you" ? "bg-surface-card animate-pulse" : "bg-teal animate-pulse") : "bg-surface-card/30"
          }`}
          style={{
            height: active ? `${8 + ((i * 7) % 16)}px` : "4px",
            animationDelay: `${i * 70}ms`,
          }}
        />
      ))}
    </div>
  );
}

function Keypad({ active, label }: { active?: string; label: string }) {
  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];
  return (
    <div className="px-6 pb-2" role="group" aria-label={label}>
      <div className="grid grid-cols-3 gap-x-6 gap-y-1.5">
        {keys.map((k) => (
          <span
            key={k}
            className={`ref mx-auto w-11 h-9 rounded-chip grid place-items-center text-[16px] font-600 transition-colors duration-150 ${
              active === k ? "bg-teal text-ink" : "text-surface-card/80"
            }`}
          >
            {k}
          </span>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------- shared --- */

function PhoneFrame({
  children,
  label,
  dark = false,
}: {
  children: React.ReactNode;
  label: string;
  dark?: boolean;
}) {
  return (
    <figure className="w-full max-w-[360px] mx-auto">
      <div
        className={`relative h-[660px] rounded-[38px] border-[3px] border-ink p-2 ${
          dark ? "bg-ink" : "bg-surface-card"
        }`}
        style={{ boxShadow: "6px 6px 0 0 var(--color-ink)" }}
      >
        <div
          className={`h-full rounded-[30px] overflow-hidden flex flex-col ${
            dark ? "bg-ink" : "bg-surface-card border-2 border-ink"
          }`}
        >
          {children}
        </div>
      </div>
      <figcaption className="mt-4 text-center text-[14px] font-600 text-ink">{label}</figcaption>
    </figure>
  );
}

function PlayBar({
  running,
  done,
  onPlay,
  label,
  dark = false,
}: {
  running: boolean;
  done: boolean;
  onPlay: () => void;
  label: string;
  dark?: boolean;
}) {
  return (
    <div className={`px-3 pb-3 pt-1 ${dark ? "" : "bg-surface-card"}`}>
      <button
        type="button"
        onClick={onPlay}
        className={`pressable w-full rounded-chip border-2 py-2.5 text-[15px] font-700 ${
          running
            ? dark
              ? "border-surface-card text-surface-card"
              : "border-ink text-ink"
            : "bg-teal text-ink border-ink"
        }`}
        aria-pressed={running}
      >
        {running ? "■ " : done ? "↻ " : "▶ "}
        {label}
      </button>
    </div>
  );
}

function Ticks() {
  return (
    <svg width="18" height="11" viewBox="0 0 18 11" aria-label="read" role="img">
      <path d="M1 6l3 3 6-7M7 9l1 1 7-8" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function IconSend() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 2L11 13" />
      <path d="M22 2l-7 20-4-9-9-4 20-7z" />
    </svg>
  );
}

function IconPhone() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1.9.4 1.8.7 2.7a2 2 0 01-.5 2.1L8 9.8a16 16 0 006 6l1.3-1.3a2 2 0 012.1-.4c.9.3 1.8.6 2.7.7a2 2 0 011.7 2z" />
    </svg>
  );
}
