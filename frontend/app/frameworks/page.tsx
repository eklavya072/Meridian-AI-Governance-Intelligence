"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { motion } from "motion/react";
import { api, Framework } from "@/lib/api";
import TiltCard from "@/components/TiltCard";
import UnderlineLink from "@/components/UnderlineLink";
import WarpText from "@/components/WarpText";
import { EASE, staggerContainer, staggerChild } from "@/lib/motion";

// URL-safe id for a framework card, matched by the analysis page's deep link
// /frameworks?framework=<name> (International Standard Reference links).
function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

export default function FrameworksPage() {
  // useSearchParams needs a Suspense boundary for static prerendering.
  return (
    <Suspense fallback={null}>
      <FrameworksContent />
    </Suspense>
  );
}

function FrameworksContent() {
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadFrameworks();
  }, []);

  // Deep link: scroll to and briefly ring the framework named in the
  // ?framework= query param (sent by Module 2's International Standard
  // Reference links). Keyed on the reactive search param, so it fires on
  // both a fresh mount (analysis → frameworks) and a same-route query
  // change. The grid renders asynchronously, so poll briefly for the card;
  // the ring is applied imperatively (guaranteed, no Tailwind dependency)
  // and the scroll falls back to instant if smooth is unavailable.
  const searchParams = useSearchParams();
  const target = searchParams.get("framework");

  useEffect(() => {
    if (!target) return;
    let attempts = 0;
    let ringEl: HTMLElement | null = null;
    let clearRing: number | undefined;
    let scrollFallback: number | undefined;
    const timer = window.setInterval(() => {
      attempts += 1;
      const el = document.getElementById(`framework-${slugify(target)}`);
      if (el) {
        window.clearInterval(timer);
        ringEl = el;
        const base = el.style.borderColor;
        el.style.borderColor = "rgb(45, 101, 224)";
        el.style.boxShadow = "0 0 0 3px rgba(45,101,224,0.18)";
        clearRing = window.setTimeout(() => {
          el.style.borderColor = base;
          el.style.boxShadow = "";
          ringEl = null;
        }, 4000);
        // Smooth scroll where supported, with a verification fallback:
        // some environments (e.g. heavy GSAP render loops) never advance
        // a smooth scroll, so jump instantly if it stalled.
        const before = window.scrollY;
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        scrollFallback = window.setTimeout(() => {
          if (window.scrollY === before) {
            el.scrollIntoView({ behavior: "auto", block: "center" });
          }
        }, 350);
      } else if (attempts >= 25) {
        // ~2.5s — give up quietly if the card never appears.
        window.clearInterval(timer);
      }
    }, 100);
    return () => {
      window.clearInterval(timer);
      if (clearRing) window.clearTimeout(clearRing);
      if (scrollFallback) window.clearTimeout(scrollFallback);
      if (ringEl) {
        ringEl.style.borderColor = "";
        ringEl.style.boxShadow = "";
      }
    };
  }, [target]);

  async function loadFrameworks() {
    setLoading(true);
    try {
      const data = await api.listFrameworks();
      // Dedupe by name: the library can contain duplicate entries (e.g. a
      // framework synced twice), which would otherwise produce duplicate
      // card ids and duplicate deep-link targets.
      const seen = new Set<string>();
      setFrameworks(
        data.filter((fw) => {
          if (seen.has(fw.name)) return false;
          seen.add(fw.name);
          return true;
        })
      );
      setError(null);
    } catch (e) {
      setError("Failed to load frameworks");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      {/* Simple header — plain surface, no texture, no gradient. The visual
          interest belongs to the framework data itself. */}
      <div className="px-1 py-2">
        {/* Real heading for semantics/SEO; WarpText renders the visual. */}
        <h1 className="sr-only">Framework Library</h1>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE.out }}
        >
          {/* The sr-only h1 above carries the heading semantics; the warp
              visual is decorative, so it is hidden from assistive tech. */}
          <div aria-hidden="true">
            {/* Explicit min-height: the canvas is absolutely positioned and
                WarpText's fit-logic only shrinks text to fit, so a collapsed
                container would rasterize the heading tiny. 100px >= max
                fontSize (4rem) / 0.78 + padding. Size matched to the other
                page headings (clamp 3.25rem → 4rem). */}
            <WarpText
              text="Framework Library"
              color="#0A0A0A"
              fontSize="clamp(3.25rem, 7vw, 4rem)"
              fontWeight={800}
              letterSpacing="-0.03em"
              lineHeight={0.95}
              speed={0.5}
              warpStrength={0.09}
              refraction={0.012}
              style={{ minHeight: 110 }}
            />
          </div>
        </motion.div>
        <motion.p
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: EASE.out, delay: 0.06 }}
          className="text-navy-600 mt-2 max-w-2xl mx-auto text-center"
        >
          Reference frameworks used for analysis. Sources are config-driven.
        </motion.p>
      </div>

      {error && (
        <div className="bg-[#F6ECEB] border border-[#E4C9C6] text-[#A8483F] px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Loading framework library...</p>
      ) : frameworks.length === 0 ? (
        <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 px-4 py-3 rounded-lg text-sm">
          No frameworks indexed yet.
        </div>
      ) : (
        <motion.div
          variants={staggerContainer(0.05, 0.02)}
          initial="hidden"
          animate="show"
          className="grid gap-4 md:grid-cols-2"
        >
          {frameworks.map((fw) => (
            <motion.div key={fw.name} variants={staggerChild} className="h-full">
            <TiltCard className="h-full">
            <div
              id={`framework-${slugify(fw.name)}`}
              className="h-full bg-white rounded-xl shadow-sm border border-gray-200 p-6"
            >
              <div className="flex items-start justify-between mb-3 gap-3">
                <h2 className="font-semibold text-gray-900">{fw.name}</h2>
                {/* Dot indicator: 8px dot + muted label, no filled pill. */}
                <span className="dot-indicator shrink-0 !gap-1.5 !text-xs">
                  <span
                    className="dot !w-1.5 !h-1.5"
                    style={{ background: fw.indexed ? "#3F7A52" : "#8A8A8A" }}
                  />
                  <span className="text-navy-600">
                    {fw.indexed ? "Indexed" : "Not Indexed"}
                  </span>
                </span>
              </div>
              {fw.website && (
                <UnderlineLink
                  href={fw.website}
                  ariaLabel={`Official source for ${fw.name}`}
                  className="mt-3 text-sm text-undp-blue"
                >
                  Official Source
                  <span aria-hidden="true" className="inline-block transition-transform duration-200 group-hover:translate-x-0.5">
                    &rarr;
                  </span>
                </UnderlineLink>
              )}
            </div>
            </TiltCard>
            </motion.div>
          ))}
        </motion.div>
      )}
    </div>
  );
}
