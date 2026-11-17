import type { Metadata, Viewport } from "next";
// Turbopack requires one next/font/google import statement per font: a
// combined import fails the production build with "queries have exactly one
// entry", while dev tolerates it.
import { Manrope } from "next/font/google";
import { Noto_Sans_Devanagari } from "next/font/google";
import { IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { LanguageProvider } from "@/components/lang";
import { MobileNav, TopNav } from "@/components/nav";
import { ServiceStatus } from "@/components/service-status";

/**
 * Type, chosen for the job rather than defaulted.
 *
 * Manrope carries both display and body: a rounded geometric sans that stays
 * legible at 13px on a phone and gains real presence at 40px, so one family
 * covers the whole range and hierarchy comes from weight and size.
 *
 * Noto Sans Devanagari is not decoration - it is the reason Marathi and Hindi
 * render correctly. The previous body face carried no Devanagari glyphs, so
 * every Indic string fell back to whatever the device happened to have.
 *
 * IBM Plex Mono is reserved for reference numbers, where tabular figures and
 * an unmistakable zero matter.
 */
const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

const devanagari = Noto_Sans_Devanagari({
  variable: "--font-devanagari",
  subsets: ["devanagari", "latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "District Grievance Desk",
  description:
    "File and track a grievance in Marathi, Hindi or English. Demonstration system built on synthetic data.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0a6b5e",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body
        className={`${manrope.variable} ${devanagari.variable} ${plexMono.variable} antialiased`}
      >
        <LanguageProvider>
          <div className="min-h-dvh flex flex-col">
            <ServiceStatus />
            <TopNav />

          {/* Bottom padding clears the mobile tab bar. */}
          <main className="flex-1 pb-28 md:pb-0">{children}</main>

          <footer className="border-t border-line mt-12 hidden md:block">
            <div className="mx-auto max-w-[1180px] px-6 py-8 text-[13px] text-ink-3 leading-relaxed">
              Synthetic demonstration data. Not official government records. All
              contact details are non-operational placeholders and no message is
              delivered to a real address.
            </div>
          </footer>

            <MobileNav />
          </div>
        </LanguageProvider>
      </body>
    </html>
  );
}
