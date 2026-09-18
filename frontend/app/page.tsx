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
 *
 * Full creative rationale and copy: docs/landing-design-package.md
 */

import { useEffect, useLayoutEffect, useState } from "react";
import HeroScrub from "@/components/HeroScrub";
import LandingSections from "@/components/LandingSections";

export default function Landing() {
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
    <div className={`landing${armed ? " is-armed" : ""}`}>
      {/* The ground below the fold. The hero carries the moving image, so
          nothing here needs a frame loop. */}
      <div className="l-waves-still" aria-hidden />

      {/* Dust drifting on a 90 second cycle. */}
      <div className="l-dust" aria-hidden />

      <HeroScrub />

      {/* Not a <main>: the root layout already provides that landmark, and
          nesting a second one gives assistive tech two competing main
          regions. This is the scrim surface and the anchor target only. */}
      <div id="content" className="l-content">
        <LandingSections />
      </div>
    </div>
  );
}
