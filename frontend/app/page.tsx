"use client";

/**
 * Meridian — the landing route.
 *
 * The premise is DEPTH. Every national AI strategy says the right things;
 * only a minority ever say when. The distance between a promise and a
 * commitment is what Meridian measures, and the page teaches that one idea
 * from the first line to the call to action.
 *
 * The hero is a scroll-scrubbed film: a tall pinned region whose progress
 * drives the video's time, so the light travelling across the page is moved
 * by the reader. Three caption bands assemble against that same progress.
 * The proof lives below it, in the product's own screens animating
 * themselves.
 *
 * The engineering rule holds throughout, and the scrub is not an exception
 * to it: constructs whose failure mode is INVISIBLE CONTENT are banned. The
 * hero video is decorative and aria-hidden, its poster is painted beneath
 * it, and every section below reveals through latching timers that never
 * consult scroll progress. A stalled compositor costs motion here, never
 * words.
 */

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Lenis from "lenis";
import HeroScrub, { type HeroIntro } from "@/components/HeroScrub";
import Preloader from "@/components/Preloader";
import LandingSections from "@/components/LandingSections";
import { landingFontVariables } from "@/lib/landingFonts";
import "./landing.css";

/* The intro plays on a fresh load of the page (a first visit or a reload),
   not on every return to it while browsing the app: this flag lives as long
   as the loaded script does. */
let introPlayed = false;

export default function Landing() {
  /* The Meridian intro covers the page, then its stairs drop away and the
     hero's opening line is set word by word beneath them. It is in the
     server-rendered HTML, so the page is never seen before it. */
  const [showPreloader, setShowPreloader] = useState(() => !introPlayed);
  const [intro, setIntro] = useState<HeroIntro>(() => (introPlayed ? "none" : "wait"));
  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Smooth scrolling on the landing only. A wheel moves the page in steps,
     and at speed the scrubbed hero, the pinned track and the reveals all
     jumped with it; Lenis turns the steps into one glide that everything
     scroll-driven follows. Paused while the intro covers the page; off
     under reduced motion; touch keeps its native momentum. */
  const lenisRef = useRef<Lenis | null>(null);
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const lenis = new Lenis({ lerp: 0.085, smoothWheel: true, anchors: true, autoRaf: true });
    lenisRef.current = lenis;
    return () => {
      lenis.destroy();
      lenisRef.current = null;
    };
  }, []);
  useEffect(() => {
    if (showPreloader) lenisRef.current?.stop();
    else lenisRef.current?.start();
  }, [showPreloader]);

  /* Arming the section reveals is a separate step from playing them.
     Their start states hide content, so they cannot live in CSS
     unconditionally: without JS the server-rendered page would paint blank.
     `armed` gates every one of them, and it is set in a layout effect,
     which runs after the DOM is written and BEFORE the browser paints, so
     the hidden state is the first thing on screen rather than a flash of
     visible text snapping away.

     No JS at all means no `armed`, which means everything simply renders. */
  const [armed, setArmed] = useState(false);
  const useIsomorphicLayoutEffect =
    typeof window === "undefined" ? useEffect : useLayoutEffect;
  useIsomorphicLayoutEffect(() => {
    setArmed(true);
  }, []);

  return (
    <div className={`landing ${landingFontVariables}${armed ? " is-armed" : ""}`}>
      {/* The ground below the fold. The hero carries the moving image, so
          nothing here needs a frame loop. */}
      <div className="l-waves-still" aria-hidden />

      {/* Dust drifting on a 90 second cycle. */}
      <div className="l-dust" aria-hidden />

      {showPreloader && (
        <Preloader
          reduced={reduced}
          onReveal={() => {
            introPlayed = true;
            setIntro(reduced ? "none" : "play");
          }}
          onDone={() => setShowPreloader(false)}
        />
      )}

      <HeroScrub intro={intro} />

      {/* Not a <main>: the root layout already provides that landmark, and
          nesting a second one gives assistive tech two competing main
          regions. This is the scrim surface and the anchor target only. */}
      <div id="content" className="l-content">
        <LandingSections />
      </div>
    </div>
  );
}
