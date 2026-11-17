"use client";

/**
 * Shared interface pieces.
 *
 * Each one exists because a screen needed it twice, not because a component
 * library usually has one. Motion follows the single personality set in
 * globals.css: fast start, long soft landing, nothing loops.
 */
import { useEffect, useRef, useState } from "react";

/**
 * Reveals its children once, when they first scroll into view.
 *
 * Fires a single time and never animates content the reader is already
 * looking at, so nothing is ever hidden waiting for an observer.
 */
export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (
      typeof IntersectionObserver === "undefined" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      setShown(true);
      return;
    }

    // Already on screen at mount: show immediately, do not animate.
    const rect = node.getBoundingClientRect();
    if (rect.top < window.innerHeight * 0.9) {
      setShown(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -10% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={`${className} ${shown ? "revealed" : "to-reveal"}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/**
 * Confidence as a ring rather than a bar.
 *
 * A ring reads as a single gauge at a glance, which suits the case detail
 * where confidence is one of three or four numbers competing for attention.
 * The threshold is drawn as a notch so the number is never shown without the
 * bar it has to clear.
 */
export function ConfidenceRing({
  confidence,
  threshold,
  size = 92,
}: {
  confidence: number;
  threshold: number;
  size?: number;
}) {
  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const met = confidence >= threshold;
  const [drawn, setDrawn] = useState(0);

  useEffect(() => {
    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    if (reduced) {
      setDrawn(confidence);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 700);
      setDrawn(confidence * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [confidence]);

  const notch = (Math.min(1, threshold) * 360 - 90) * (Math.PI / 180);
  const cx = size / 2;
  const cy = size / 2;

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-surface-sunk"
        />
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - drawn)}
          className={met ? "stroke-teal" : "stroke-amber"}
        />
      </svg>
      {/* the bar it has to clear */}
      <svg width={size} height={size} className="absolute inset-0">
        <line
          x1={cx + (radius - stroke) * Math.cos(notch)}
          y1={cy + (radius - stroke) * Math.sin(notch)}
          x2={cx + (radius + stroke) * Math.cos(notch)}
          y2={cy + (radius + stroke) * Math.sin(notch)}
          className="stroke-ink-2"
          strokeWidth={2}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <span className="font-display font-800 text-[20px] tabular leading-none text-ink">
          {confidence.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

/** A numbered step with a connector, for explaining a flow. */
export function Step({
  n,
  title,
  body,
  last = false,
}: {
  n: number;
  title: string;
  body: string;
  last?: boolean;
}) {
  return (
    <li className="relative pl-14">
      <span className="absolute left-0 top-0 w-10 h-10 rounded-chip bg-teal-tint text-ink border border-ink grid place-items-center font-display font-800 text-[16px]">
        {n}
      </span>
      {!last && (
        <span
          className="absolute left-5 top-11 bottom-0 w-px bg-line"
          aria-hidden
        />
      )}
      <h3 className="text-[17px] font-700 text-ink mb-1.5">{title}</h3>
      <p className="text-[15px] text-ink-2 leading-relaxed pb-8">{body}</p>
    </li>
  );
}

/** A small labelled figure, used in strips of three or four. */
export function Figure({
  value,
  label,
  tone = "ink",
}: {
  value: React.ReactNode;
  label: string;
  tone?: "ink" | "teal" | "amber" | "rose";
}) {
  const colour =
    tone === "teal"
      ? "text-ink"
      : tone === "amber"
        ? "text-ink decoration-amber underline decoration-4 underline-offset-4"
        : tone === "rose"
          ? "text-rose"
          : "text-ink";
  return (
    <div>
      <div
        className={`${colour} font-display font-800 text-[clamp(1.75rem,1.3rem+1.6vw,2.5rem)] leading-none tabular mb-1.5`}
      >
        {value}
      </div>
      <div className="text-[13px] text-ink-3 font-600 leading-tight">
        {label}
      </div>
    </div>
  );
}
