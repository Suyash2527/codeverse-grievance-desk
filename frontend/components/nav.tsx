"use client";

/**
 * Navigation, built mobile-first.
 *
 * On a phone the primary navigation is a bottom tab bar: thumb-reachable,
 * always visible, and it tells the user at a glance which of the three desks
 * they are standing at. The desktop header is the secondary case.
 *
 * Icons are one consistent line set at a single 1.75 stroke, drawn inline so
 * there is no icon-font request and no emoji.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

import { LanguageSwitch, useLang } from "@/components/lang";

type Tab = { href: string; label: string; icon: (active: boolean) => React.ReactNode };

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function IconQueue() {
  return (
    <svg viewBox="0 0 24 24" className="w-6 h-6" aria-hidden>
      <rect x="3" y="4" width="18" height="5" rx="1.5" {...stroke} />
      <rect x="3" y="12.5" width="18" height="5" rx="1.5" {...stroke} />
      <path d="M6.5 20.5h11" {...stroke} />
    </svg>
  );
}

function IconFile() {
  return (
    <svg viewBox="0 0 24 24" className="w-6 h-6" aria-hidden>
      <path d="M5 4.5h9l5 5v10a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 4 19.5v-14A1.5 1.5 0 0 1 5 4.5Z" {...stroke} />
      <path d="M14 4.5v5h5" {...stroke} />
      <path d="M8.5 14h7M8.5 17h4" {...stroke} />
    </svg>
  );
}

function IconShield() {
  return (
    <svg viewBox="0 0 24 24" className="w-6 h-6" aria-hidden>
      <path d="M12 3.5l7 2.5v6c0 4.2-2.9 7.4-7 8.5-4.1-1.1-7-4.3-7-8.5V6l7-2.5Z" {...stroke} />
      <path d="M9 12.2l2.2 2.2 4-4.2" {...stroke} />
    </svg>
  );
}

function IconTrack() {
  return (
    <svg viewBox="0 0 24 24" className="w-6 h-6" aria-hidden>
      <circle cx="11" cy="11" r="6.5" {...stroke} />
      <path d="M16 16l4.5 4.5" {...stroke} />
    </svg>
  );
}

const TABS: Tab[] = [
  { href: "/officer", label: "queue", icon: () => <IconQueue /> },
  { href: "/citizen", label: "file", icon: () => <IconFile /> },
  { href: "/track", label: "track", icon: () => <IconTrack /> },
  { href: "/compliance", label: "rules", icon: () => <IconShield /> },
];

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function TopNav() {
  const pathname = usePathname() ?? "/";
  const { t } = useLang();
  return (
    <header className="sticky top-0 z-30 bg-surface-card/90 backdrop-blur-md border-b border-line">
      <div className="mx-auto max-w-[1180px] px-5 md:px-6 h-16 flex items-center justify-between gap-3">
        <Link href="/" className="flex items-center gap-2.5 min-w-0">
          <span className="w-8 h-8 rounded-card bg-teal text-ink border-2 border-ink grid place-items-center font-display font-800 text-[15px] shrink-0">
            G
          </span>
          <span className="min-w-0">
            <span className="block font-display font-700 text-[16px] leading-tight text-ink truncate whitespace-nowrap">
              {t("app.name")}
            </span>
            <span className="hidden lg:block text-[11px] text-ink-3 leading-tight whitespace-nowrap">
              {t("app.subtitle")}
            </span>
          </span>
        </Link>

        <div className="hidden md:flex items-center gap-3">
          <nav className="flex items-center gap-1">
            {TABS.map((tab) => {
              const active = isActive(pathname, tab.href);
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  className={`pressable whitespace-nowrap px-3 lg:px-4 py-2 rounded-chip text-[14px] lg:text-[15px] font-600 ${
                    active
                      ? "bg-teal-tint text-ink border border-ink"
                      : "text-ink-2 hover:bg-surface-sunk hover:text-ink"
                  }`}
                >
                  {/* Short labels where the bar is tight, full ones where
                      there is room. */}
                  <span className="lg:hidden">{t(`nav.${tab.label}.short`)}</span>
                  <span className="hidden lg:inline">{t(`nav.${tab.label}`)}</span>
                </Link>
              );
            })}
          </nav>
          <LanguageSwitch size="sm" />
        </div>

        {/* On a phone the switch is the only header control, so it stays. */}
        <div className="md:hidden">
          <LanguageSwitch size="sm" />
        </div>

      </div>
    </header>
  );
}

export function MobileNav() {
  const pathname = usePathname() ?? "/";
  const { t } = useLang();
  return (
    <nav
      className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-surface-card/95 backdrop-blur-md border-t border-line"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      aria-label="Main"
    >
      <ul className="grid grid-cols-4">
        {TABS.map((tab) => {
          const active = isActive(pathname, tab.href);
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={`relative flex flex-col items-center justify-center gap-1 h-16 text-[11px] font-600 transition-colors duration-150 ${
                  active ? "text-ink" : "text-ink-3"
                }`}
              >
                {/* The indicator is the signature mobile motion: it slides
                    to the active tab rather than blinking on. */}
                <span
                  className={`absolute top-0 h-0.5 bg-teal rounded-chip transition-all duration-300 ${
                    active ? "w-10 opacity-100" : "w-0 opacity-0"
                  }`}
                  style={{ transitionTimingFunction: "cubic-bezier(0.16,1,0.3,1)" }}
                  aria-hidden
                />
                {tab.icon(active)}
                {t(`nav.${tab.label}.short`)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
