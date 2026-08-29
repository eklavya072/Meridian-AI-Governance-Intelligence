import type { Metadata } from "next";
import { Space_Grotesk, Unbounded, Public_Sans, Newsreader, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { MotionConfig } from "motion/react";
import { ChatProvider } from "@/components/ChatProvider";
import ChatPanel from "@/components/ChatPanel";
import NavBar from "@/components/NavBar";

export const metadata: Metadata = {
  title: "Meridian — AI Governance Intelligence Workbench",
  description:
    "UNDP DAI Hub: Policy gap analysis against international AI governance frameworks.",
};

/* ── Typeface pair ───────────────────────────────────────────────────────
   Space Grotesk (display): a technical grotesque with real letterform
   character — sharp, precise, the distinctive premium headline voice
   (hero, section headings, card titles).
   Public Sans (body): designed for government digital services; highly
   readable at body sizes, the institutional reading face.
   Self-hosted via next/font (no runtime requests, no layout shift). */
const display = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const body = Public_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

/* Brand face (Unbounded): the Meridian wordmark + tagline only — a wide,
   geometric display face with real character. Reserves a separate variable
   so the hero wordmark can be distinctive without changing the display
   voice (Sora) used by headings elsewhere. */
const brand = Unbounded({
  subsets: ["latin"],
  variable: "--font-brand",
  display: "swap",
});

/* ── Landing route trio ──────────────────────────────────────────────────
   Newsreader (display): a document serif with optical sizing. The landing
   page's world is ink on paper, and this is the face that says so without
   reaching for the fashion serif every dark site uses.
   IBM Plex Mono (labels): dimension names, scores, framework versions,
   section numerals. Institutional, and it sits correctly beside a serif.
   Scoped to the landing route by CSS; the rest of the app keeps Space
   Grotesk. Only the weights actually in use are requested. */
const displaySerif = Newsreader({
  subsets: ["latin"],
  weight: ["300", "400"],
  style: ["normal", "italic"],
  variable: "--font-serif",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="font-sans">
      {/* Font variables on <body> (not <html>) keeps the no-JS fallback
          surface clean and scopes them to app content. */}
      <body className={`${display.variable} ${body.variable} ${brand.variable} ${displaySerif.variable} ${mono.variable}`}>
        {/* reducedMotion="user": every motion-driven animation in the app
            honors the user's prefers-reduced-motion preference — the CSS-only
            animations (status dot, progress bar) already have their own
            fallback in globals.css. */}
        <MotionConfig reducedMotion="user">
          <ChatProvider>
            <NavBar />
            <main className="max-w-7xl mx-auto px-4 pt-24 pb-8">{children}</main>
            <ChatPanel />
          </ChatProvider>
        </MotionConfig>
      </body>
    </html>
  );
}
