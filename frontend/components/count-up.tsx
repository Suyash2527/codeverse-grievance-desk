"use client";

/**
 * A figure that counts up once, when it first arrives.
 *
 * This is the one piece of decorative motion on the queue, and it earns its
 * place: the counts are the first thing an officer reads, and the movement
 * draws the eye there before anything else on the screen moves.
 *
 * It runs once per value change, never loops, and respects reduced motion.
 */
import { useEffect, useRef, useState } from "react";

export function CountUp({
  value,
  className,
}: {
  value: number | undefined;
  className?: string;
}) {
  const [shown, setShown] = useState(value ?? 0);
  const frame = useRef<number | null>(null);

  useEffect(() => {
    if (value === undefined) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || value === 0) {
      setShown(value);
      return;
    }

    const from = 0;
    const duration = 650;
    const start = performance.now();

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // Same easing curve as every other entrance on the site.
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(Math.round(from + (value - from) * eased));
      if (t < 1) frame.current = requestAnimationFrame(tick);
    };

    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [value]);

  if (value === undefined) {
    return <span className={className}>–</span>;
  }
  return (
    <span className={className} aria-label={String(value)}>
      {shown}
    </span>
  );
}

/** A queue card placeholder, matching the real card's shape. */
export function QueueSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <ul className="space-y-3" aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="card px-5 py-5 relative overflow-hidden pl-6">
          <span className="absolute left-0 top-0 bottom-0 w-1.5 bg-surface-sunk" />
          <div className="flex gap-3 mb-4">
            <div className="skeleton h-7 w-32" />
            <div className="skeleton h-7 w-16" />
          </div>
          <div className="skeleton h-5 w-3/4 mb-3" />
          <div className="skeleton h-4 w-1/2" />
        </li>
      ))}
    </ul>
  );
}
