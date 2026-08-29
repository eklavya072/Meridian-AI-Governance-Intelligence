"use client";

/**
 * Meridian — the landing route.
 *
 * The premise is DEPTH. Every national AI strategy says the right things;
 * only a minority ever say when. The distance between a promise and a
 * commitment is what Meridian measures, and the page teaches that one idea
 * from the first line to the call to action.
 *
 * The hero is one composed viewport rather than a scroll-scrubbed film. The
 * proof lives below it, in the product's own screens animating themselves:
 * the analysis taking its readings, the auditor answering with a citation,
 * the framework library assembling, and the four stages of the run.
 *
 * Every animation on this route is driven by timers and plain CSS
 * transitions. Constructs whose failure mode is invisible content have
 * burned this codebase repeatedly in embedded webviews where
 * requestAnimationFrame stalls, so nothing here can strand content at
 * opacity zero.
 *
 * Full creative rationale and copy: docs/landing-design-package.md
 */

import { useEffect, useLayoutEffect, useState } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import LandingSections from "@/components/LandingSections";
import { RollWords } from "@/components/TextEffects";

/* The swell is WebGL and only meaningful once the page is interactive, so
   it never enters the server render. Its still fallback is already on
   screen underneath, which means there is nothing to wait for and nothing
   that shifts when it arrives. */
const GradientWaves = dynamic(() => import("@/components/GradientWaves"), {
  ssr: false,
});

export default function Landing() {
  /* The waves are held back until after mount and skipped entirely under
     reduced motion. The still gradient beneath them carries the same grade,
     so either way the page is a lit room rather than a flat rectangle. */
  const [waves, setWaves] = useState(false);
  /* Arming the motion is a separate step from playing it, and both matter.

     The roll's start state hides the words, so it cannot live in CSS
     unconditionally: without JS the server-rendered hero would paint blank.
     `armed` gates it, and it is set in a layout effect, which runs after
     the DOM is written and BEFORE the browser paints, so the hidden state
     is the first thing on screen rather than a flash of visible text
     snapping away. Then `lit` follows a frame later and the words roll in.

     No JS at all means no `armed`, which means the text simply renders. */
  const [armed, setArmed] = useState(false);
  const [lit, setLit] = useState(false);
  const useIsomorphicLayoutEffect =
    typeof window === "undefined" ? useEffect : useLayoutEffect;
  useIsomorphicLayoutEffect(() => {
    setArmed(true);
  }, []);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setLit(true), 60);
    /* The same fail-safe every entrance on this route carries: a timer
       asserts the finished state with the transition switched off, so a
       compositor that never advances still leaves the hero readable. */
    const s = setTimeout(() => setSettled(true), 2600);
    return () => {
      clearTimeout(t);
      clearTimeout(s);
    };
  }, [armed]);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => setWaves(!mq.matches);
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  return (
    <div className={`landing${armed ? " is-armed" : ""}`}>
      {/* The ground: a still grade, with the slow swell over it. */}
      <div className="l-waves-still" aria-hidden />
      {waves && (
        <div className="l-waves" aria-hidden>
          <GradientWaves
            horizonColor="#1B1F26"
            waveColor="#8A9099"
            crestColor="#CFD3D9"
            speed={0.32}
            amplitude={2.4}
            waveScale={0.62}
            waveRatio={0.9}
            swell={44}
            turbulence={18}
            tilt={0.92}
            zoom={1}
            height={8.2}
            /* The layer is fixed, so its composition decides how much of
               EVERY viewport is lit swell and how much is empty horizon.
               A high tilt with a low camera put the lit band in the bottom
               third and left the top two thirds black on every section.
               Raising the camera and flattening the tilt fills the frame;
               fogDepth then sets how far that field stays lit before it
               falls off into the horizon colour. */
            fogDepth={34}
            detail="medium"
            brightness={1}
            opacity={0.66}
            mouseInteraction={false}
            parallaxStrength={0.35}
            grain
            grainIntensity={0.045}
          />
        </div>
      )}

      {/* Dust drifting on a 90 second cycle, over the swell. */}
      <div className="l-dust" aria-hidden />

      {/* The signature: a plumb rail down the page's margin. The brand mark
          is already a plumb line hanging on true vertical; this is that mark
          unrolled to full page height. */}
      <div className="l-rail" aria-hidden>
        <span className="l-rail-weight" />
      </div>

      <header className={`l-hero${lit ? " in" : ""}${settled ? " settled" : ""}`}>
        <div className="l-hero-inner">
          <RollWords as="h1" className="l-display l-h1" text="Measure the depth." stagger={110} />

          <p className="l-body l-hero-sub">
            Any strategy can say the right things. Meridian reads yours against
            eight governance dimensions and the frameworks the world already
            agreed on, then shows you exactly where it stops.
          </p>

          <div className="l-cta l-hero-cta">
            <Link href="/workspace" className="l-btn l-btn-primary">
              Benchmark your policy
            </Link>
            <Link href="/analysis" className="l-btn l-btn-quiet">
              See a finished analysis
            </Link>
          </div>
        </div>

        <span className="l-scroll-cue" aria-hidden>
          <span className="l-scroll-cue-line" />
        </span>
      </header>

      {/* Not a <main>: the root layout already provides that landmark, and
          nesting a second one gives assistive tech two competing main
          regions. This is the scrim surface and the anchor target only. */}
      <div id="content" className="l-content">
        <LandingSections />
      </div>
    </div>
  );
}
