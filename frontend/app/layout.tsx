import type { Metadata } from "next";
import { Space_Grotesk, Unbounded, Public_Sans } from "next/font/google";
import "./globals.css";
import { MotionConfig } from "motion/react";
import { ChatProvider } from "@/components/ChatProvider";
import ChatPanel from "@/components/ChatPanel";
import NavBar from "@/components/NavBar";

/* The description asserted "UNDP DAI Hub", which claims an affiliation this
   project does not have — and it is the string that renders in every search
   result, LinkedIn card and Slack unfurl, aimed squarely at the audience
   best placed to check it. It describes what Meridian does instead.

   Open Graph and Twitter cards were absent entirely, so every share of this
   link rendered as a bare URL. */
const DESCRIPTION =
  "Meridian reads a national AI strategy and reports what it obliges — " +
  "every commitment graded from a stated aspiration to an enforceable duty, " +
  "its gaps ranked against forty-three international instruments, with a " +
  "citation behind every line.";

export const metadata: Metadata = {
  /* Link previews need an absolute image URL. SITE_URL is the deployed
     address, set at build time (deploy/huggingface/Dockerfile). */
  metadataBase: new URL(process.env.SITE_URL || "http://localhost:3000"),
  title: "Meridian — AI Governance Intelligence Workbench",
  description: DESCRIPTION,
  openGraph: {
    title: "Meridian — AI Governance Intelligence Workbench",
    description: DESCRIPTION,
    siteName: "Meridian",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Meridian — AI Governance Intelligence Workbench",
    description: DESCRIPTION,
  },
};

/* ── App typefaces ────────────────────────────────────────────────────────
   Three faces load on every page. The landing route adds its own three in
   lib/landingFonts.ts, so the app pages never download them.

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

/* Brand face (Unbounded): the Meridian wordmark in the nav only — a wide,
   geometric display face, on its own variable so the wordmark can differ
   from the Space Grotesk headings. */
const brand = Unbounded({
  subsets: ["latin"],
  variable: "--font-brand",
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
      <body className={`${display.variable} ${body.variable} ${brand.variable}`}>
        {/* reducedMotion="user": every motion-driven animation in the app
            honors the user's prefers-reduced-motion preference — the CSS-only
            animations (status dot, progress bar) already have their own
            fallback in globals.css. */}
        <MotionConfig reducedMotion="user">
          <ChatProvider>
            <NavBar />
            <main className="max-w-7xl mx-auto px-4 pt-[5.5rem] pb-8">{children}</main>
            <ChatPanel />
          </ChatProvider>
        </MotionConfig>
      </body>
    </html>
  );
}
