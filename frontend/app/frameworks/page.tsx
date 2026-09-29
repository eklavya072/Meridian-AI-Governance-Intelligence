"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { motion } from "motion/react";
import { api, Framework } from "@/lib/api";
import TiltCard from "@/components/TiltCard";
import UnderlineLink from "@/components/UnderlineLink";
import PageHeader from "@/components/PageHeader";
import { staggerContainer, staggerChild } from "@/lib/motion";

import palette from "@/lib/palette.json";
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
        el.style.borderColor = palette.black;
        el.style.boxShadow = "0 0 0 3px rgba(10, 10, 10, 0.18)";
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
      setError(`Couldn't load the frameworks. ${e instanceof Error ? e.message : ""}`.trim());
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Framework Library"
        subtitle="Reference frameworks used for analysis. Sources are config-driven."
      />

      {error && (
        <div role="alert" className="bg-status-red-tint border border-status-red-line text-status-red px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-grey-600">Loading framework library...</p>
      ) : frameworks.length === 0 ? (
        <div className="bg-status-amber-tint border border-status-amber-line text-status-amber-ink px-4 py-3 rounded-lg text-sm">
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
              className="h-full bg-white rounded-xl shadow-sm border border-grey-100 p-6"
            >
              <div className="flex items-start justify-between mb-3 gap-3">
                <h2 className="font-semibold text-grey-950">{fw.name}</h2>
                {/* Dot indicator: 8px dot + muted label, no filled pill. */}
                <span className="dot-indicator shrink-0 !gap-1.5 !text-xs">
                  <span
                    className="dot !w-1.5 !h-1.5"
                    style={{ background: fw.indexed ? palette.status.green : palette.grey["500"] }}
                  />
                  <span className="text-grey-600">
                    {fw.indexed ? "Indexed" : "Not Indexed"}
                  </span>
                </span>
              </div>
              {fw.website && (
                <UnderlineLink
                  href={fw.website}
                  ariaLabel={`Official source for ${fw.name}`}
                  className="mt-3 text-sm text-grey-950"
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
