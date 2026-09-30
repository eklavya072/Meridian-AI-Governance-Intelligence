"use client";

/**
 * The scroll-scrubbed hero.
 *
 * A tall pinned region holds a sticky full-viewport stage. Progress through
 * that region maps 0..1 and drives the video's currentTime, so the light
 * sweeping across the page is moved by the reader rather than by a clock.
 * Five caption bands own ranges of that progress and assemble against it.
 *
 * The rule this route is built on still holds, and it is worth stating
 * precisely because a scrub looks like a violation of it: nothing here gates
 * READABLE CONTENT on the frame loop. The video is decorative and aria-hidden;
 * the poster is painted underneath before it exists; the real sections below
 * use the latching reveal hooks and never consult scroll progress. What the
 * scrub can lose is motion, never words.
 */

import { Fragment, useEffect, useLayoutEffect, useRef } from "react";

const useLayoutEffectSafe = typeof window === "undefined" ? useEffect : useLayoutEffect;
import Link from "next/link";

/* Scroll distance for the pinned region. Dwell is the point of a scrubbed
   hero: each beat owns about 140vh, a full window with the words finished
   and still. Paced in vh, never in seconds: a scroll page is read in flicks. */
const HERO_VH = 800;

/* ── The beat map ─────────────────────────────────────────────────────────
   Five beats. The footage has no natural pause to land a line on, so the
   pause is constructed: each beat owns a HOLD, a stretch of scroll where the
   video's time is pinned to a single frame, and the footage travels only in
   the gaps between them. The page arrives, stops, and only then does the
   text assemble. */
type Beat = {
  /** opacity window */
  a: number;
  b: number;
  /** assembly window, deliberately inside the hold and just after it opens */
  ka: number;
  kb: number;
  /** the video time this beat pins to */
  t: number;
};

/* `a`/`b` are the band's own span; `ka`/`kb` are the stretch of scroll its
   words assemble across. Roughly a quarter of each beat assembles, half is
   the hold, and a quarter leaves. */
const BANDS: Beat[] = [
  { a: 0.0, b: 0.2, ka: 0.005, kb: 0.055, t: 0 },
  { a: 0.2, b: 0.4, ka: 0.205, kb: 0.255, t: 0 },
  { a: 0.4, b: 0.6, ka: 0.405, kb: 0.455, t: 0 },
  { a: 0.6, b: 0.8, ka: 0.605, kb: 0.655, t: 0 },
  { a: 0.8, b: 1.0, ka: 0.805, kb: 0.855, t: 0 },
];

/* ── Progress to video time ───────────────────────────────────────────────
   The clip's own CUMULATIVE MOTION, measured frame by frame (difference each
   frame against the last, take the mean brightness of that difference,
   integrate), as (fraction of total movement, seconds).

   Driving scroll against the INVERSE of this curve makes equal scroll
   distance produce equal VISUAL change, so the clip reads at one steady rate
   and the text can sit at an even cadence against it. */
const MOTION_CURVE: [number, number][] = [
  [0.0, 0.0], [0.055, 0.5], [0.11, 1.0], [0.165, 1.5], [0.22, 2.0],
  [0.273, 2.5], [0.324, 3.0], [0.377, 3.5], [0.427, 4.0], [0.478, 4.5],
  [0.527, 5.0], [0.575, 5.5], [0.618, 6.0], [0.665, 6.5], [0.709, 7.0],
  [0.751, 7.5], [0.794, 8.0], [0.826, 8.5], [0.853, 9.0], [0.886, 9.5],
  [0.922, 10.0], [0.96, 10.5], [1.0, 11.0],
];

function videoTimeAt(p: number) {
  const k = MOTION_CURVE;
  if (p <= 0) return k[0][1];
  for (let i = 1; i < k.length; i++) {
    if (p <= k[i][0]) {
      const [p0, t0] = k[i - 1];
      const [p1, t1] = k[i];
      const span = p1 - p0;
      return span <= 0 ? t1 : t0 + ((p - p0) / span) * (t1 - t0);
    }
  }
  return k[k.length - 1][1];
}

const VIDEO_URL = "/hero/hero-scrub.mp4";
const POSTER_URL = "/hero/hero-poster.jpg";
/* The fallback when Content-Length is missing, so the ring is honest either
   way. Update this if the encode is replaced.

   Encoded all-intra (every frame a keyframe, x264 CRF 26, no B-frames): a
   scrub seeks on every frame it draws, and an all-intra seek is a single
   decode. */
const VIDEO_BYTES = 6589395;

/* The five conditions that get the composed static hero instead of the
   scrub. These strings are the single source of truth: the stylesheet reads
   the same list, so the two sides cannot drift. */
const GATES = [
  "(max-width: 720px)",
  "(orientation: portrait) and (max-width: 1024px)",
  "(orientation: portrait) and (pointer: coarse)",
  "(orientation: landscape) and (pointer: coarse) and (max-height: 560px)",
  "(prefers-reduced-motion: reduce)",
];

const clamp = (v: number, lo: number, hi: number) =>
  Math.min(hi, Math.max(lo, v));

const smoothstep = (p: number, e0: number, e1: number) => {
  const t = clamp((p - e0) / (e1 - e0), 0, 1);
  return t * t * (3 - 2 * t);
};

/* Seeded, so the per-word offsets are identical on every load and the
   entrance is a designed thing rather than a different accident each time. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296;
}

/**
 * Splits a line into word spans carrying their own assembly threshold, so a
 * band's --k drives the whole line through one CSS rule. The real sentence
 * stays in the DOM for screen readers; the split copy is decoration.
 */
function ScrubWords({
  text,
  seed,
  spread = 0.55,
  className = "",
  indexFrom = 0,
}: {
  text: string;
  seed: number;
  spread?: number;
  className?: string;
  /** Position of the first word in the opening line's entrance sequence. */
  indexFrom?: number;
}) {
  const words = text.split(" ");
  const rand = rng(seed);
  return (
    <span className={className}>
      <span className="l-sr">{text}</span>
      <span aria-hidden="true">
        {words.map((w, i) => {
          const th = (i / Math.max(1, words.length - 1)) * spread + rand() * 0.05;
          /* The space belongs BETWEEN the masked spans, never inside one:
             .l-sw is an overflow-hidden inline-block, and a trailing space
             inside it collapses, running the words together. */
          return (
            <Fragment key={`${w}-${i}`}>
              <span className="l-sw">
                <span
                  className="l-sw-in"
                  style={{
                    ["--th" as string]: th.toFixed(3),
                    ["--wi" as string]: indexFrom + i,
                  }}
                >
                  {w}
                </span>
              </span>
              {i < words.length - 1 ? " " : null}
            </Fragment>
          );
        })}
      </span>
    </span>
  );
}

/** The opening line's entrance: `wait` holds it hidden under the intro,
 *  `play` runs it as the intro's stairs drop away, `none` shows it as is
 *  (reduced motion, or a return visit within the session). */
export type HeroIntro = "wait" | "play" | "none";

/* Word cadence for the opening line, matched to the intro's stairs, which
   drop 50ms apart; the words run a touch slower so the line reads as being
   set rather than blinking on. */
const INTRO_WORD_MS = 70;
const INTRO_TOTAL_MS = 2400;

export default function HeroScrub({ intro = "none" }: { intro?: HeroIntro }) {
  const rootRef = useRef<HTMLElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const ringRef = useRef<SVGCircleElement>(null);
  const bandRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const root = rootRef.current;
    const stage = stageRef.current;
    const video = videoRef.current;
    if (!root || !stage || !video) return;

    /* ── drive state ─────────────────────────────────────────────────── */
    let target = 0;
    let shown = 0;
    let velocity = 0;
    let rafId: number | null = null;
    let lastTick = 0;
    /* Wall-clock stamp of the last tick that actually ran, so the poll below
       can tell a converged loop from a dead one. */
    let lastTickAt = 0;
    let onScreen = true;
    let scrubOn: boolean | null = null;
    let loadK = 0;
    let objectUrl: string | null = null;

    /* Seek gating: one seek in flight at a time, coalesced to the newest
       target. A seek is released by whichever comes first: the new frame
       reaching the screen (requestVideoFrameCallback), the `seeked` event,
       or a 250ms timeout. A seek whose completion signal never arrives
       would otherwise hold the gate shut and freeze the film on one frame. */
    let seekBusy = false;
    let pendingTime: number | null = null;
    let seekTimer: ReturnType<typeof setTimeout> | null = null;
    type FrameVideo = HTMLVideoElement & {
      requestVideoFrameCallback?: (cb: () => void) => number;
    };
    const frameVideo = video as FrameVideo;

    const releaseSeek = () => {
      if (!seekBusy) return;
      seekBusy = false;
      if (seekTimer) clearTimeout(seekTimer);
      seekTimer = null;
      if (pendingTime !== null) {
        const t = pendingTime;
        pendingTime = null;
        requestSeek(t);
      }
    };
    const requestSeek = (t: number) => {
      if (!video.duration || Number.isNaN(video.duration)) return;
      if (seekBusy) {
        pendingTime = t;
        return;
      }
      seekBusy = true;
      try {
        video.currentTime = t;
        frameVideo.requestVideoFrameCallback?.(releaseSeek);
        seekTimer = setTimeout(releaseSeek, 250);
      } catch {
        seekBusy = false;
      }
    };
    const onVideoError = () => {
      seekBusy = false;
      pendingTime = null;
      stage.classList.add("is-videoless");
    };
    video.addEventListener("seeked", releaseSeek);
    video.addEventListener("error", onVideoError);

    /* The hero's place on the page, measured on load and resize rather
       than on every scroll event: reading layout inside a scroll handler,
       right after the frame loop has written styles, forces the browser to
       lay the page out again mid-scroll. */
    let rootTop = 0;
    let span = 1;
    const measure = () => {
      rootTop = root.getBoundingClientRect().top + window.scrollY;
      span = Math.max(1, root.offsetHeight - window.innerHeight);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(root);
    window.addEventListener("resize", measure);
    const heroProgress = () => clamp((window.scrollY - rootTop) / span, 0, 1);

    /* The clip runs at 24000/1001 fps. Seeking to a time inside the frame
       already on screen decodes that same frame again, so seeks snap to
       frame boundaries and a repeat is skipped. */
    const FPS = 24000 / 1001;
    let lastFrame = -1;
    const seekTo = (p: number) => {
      const frame = Math.round(videoTimeAt(p) * FPS);
      if (frame === lastFrame) return;
      lastFrame = frame;
      requestSeek(frame / FPS);
    };

    /* ── caption bands, written only on change ───────────────────────── */
    const cache = BANDS.map(() => ({ op: -1, k: -1, x: -1 }));

    const updateBands = (p: number) => {
      BANDS.forEach((band, i) => {
        const el = bandRefs.current[i];
        if (!el) return;
        const { a, b } = band;
        /* The exit is the SLOWER of the two edges: a beat should arrive
           promptly and be released, not snatched. */
        const fIn = 0.02;
        const fOut = 0.05;
        /* The first band skips the ease-in and the last skips the ease-out,
           so the journey opens and closes on settled text. */
        const inEdge = i === 0 ? 1 : smoothstep(p, a, a + fIn);
        const outEdge =
          i === BANDS.length - 1 ? 1 : 1 - smoothstep(p, b - fOut, b);
        const op = Math.round(inEdge * outEdge * 1000) / 1000;

        /* Exit progress, published separately from opacity so the words can
           lift and shrink as they go rather than just becoming transparent. */
        const x =
          i === BANDS.length - 1
            ? 0
            : Math.round(smoothstep(p, b - fOut, b) * 1000) / 1000;

        let k = clamp((p - band.ka) / (band.kb - band.ka), 0, 1);
        /* Band one opens assembled on load rather than waiting for a scroll
           that may never come. Once loadK reaches 1 the max holds it there,
           which is right: there is nothing above the first beat. */
        if (i === 0) k = Math.max(k, loadK);
        k = Math.round(k * 1000) / 1000;

        const c = cache[i];
        if (Math.abs(op - c.op) > 0.001) {
          c.op = op;
          el.style.opacity = String(op);
          el.style.visibility = op < 0.004 ? "hidden" : "visible";
        }
        if (Math.abs(k - c.k) > 0.002) {
          c.k = k;
          el.style.setProperty("--k", String(k));
        }
        /* No blur on the way out: blurring the band would blur its
           screen-wide scrim too, re-rendered on every frame of a handover. */
        if (Math.abs(x - c.x) > 0.002) {
          c.x = x;
          el.style.setProperty("--x", String(x));
        }
      });
    };

    /* One smoothed progress drives the footage AND the words, so they move
       as one surface.

       The smoothing is a critically damped spring rather than a plain lerp.
       A lerp starts at full speed the instant the target moves, which reads
       as a jolt at the start of every flick; the spring picks up speed and
       lays it down again, with no overshoot. OMEGA sets how closely it
       follows; the page scroll is already smoothed (Lenis), so it follows
       tightly, settling in about a fifth of a second. */
    const OMEGA = 16;
    const tick = (now: number) => {
      const dt = Math.min(0.05, (now - (lastTick || now)) / 1000);
      lastTick = now;
      lastTickAt = Date.now();
      const off = shown - target;
      const decay = Math.exp(-OMEGA * dt);
      const next = (off + (velocity + OMEGA * off) * dt) * decay;
      velocity = (velocity - OMEGA * (velocity + OMEGA * off) * dt) * decay;
      shown = target + next;
      if (Math.abs(next) < 0.00015 && Math.abs(velocity) < 0.0005) {
        shown = target;
        velocity = 0;
        rafId = null;
        lastTick = 0;
      } else {
        rafId = requestAnimationFrame(tick);
      }
      updateBands(shown);
      if (video.duration) seekTo(shown);
    };

    /* The frame loop is where the words move now, so the rule this route is
       built on (no readable content may depend on it) is kept by the
       interval further down: if no frame has run for a third of a second,
       it writes the captions from the raw scroll position itself. A stalled
       compositor costs the glide, never the words. */
    const onScroll = () => {
      target = heroProgress();
      if (rafId === null && onScreen) rafId = requestAnimationFrame(tick);
    };

    /* ── the static, non-scrub presentation ──────────────────────────── */
    const pinToFinalStates = () => {
      BANDS.forEach((_, i) => {
        const el = bandRefs.current[i];
        if (!el) return;
        cache[i].op = -1;
        cache[i].k = -1;
        /* EVERY band renders in the static hero, stacked and in order:
           below 720px, on portrait touch and under reduced motion the page
           still carries its <h1> and the whole argument, not just the call
           to action. The stacking, spacing and per-beat composition are
           handled in CSS under `.is-static`. */
        el.style.opacity = "1";
        el.style.visibility = "visible";
        el.style.setProperty("--k", "1");
        el.style.setProperty("--x", "0");
        cache[i].x = -1;
      });
    };

    /* ── blob load (the Range rule) ──────────────────────────────────── */
    let started = false;
    let ctrl: AbortController | null = null;

    const setRing = (frac: number) => {
      const r = ringRef.current;
      if (r) r.style.setProperty("--ld", String(Math.round(126 * (1 - frac))));
    };

    const failVideo = () => {
      stage.classList.add("is-videoless");
      stage.classList.remove("is-loading");
    };

    const loadHeroBlob = async () => {
      ctrl = new AbortController();
      let watchdog = setTimeout(() => ctrl?.abort(), 20000);
      try {
        const res = await fetch(VIDEO_URL, { signal: ctrl.signal });
        if (!res.ok || !res.body) throw new Error("hero video unavailable");
        const total = Number(res.headers.get("Content-Length")) || VIDEO_BYTES;
        const reader = res.body.getReader();
        const chunks: BlobPart[] = [];
        let got = 0;
        let lastRing = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          clearTimeout(watchdog);
          watchdog = setTimeout(() => ctrl?.abort(), 20000);
          chunks.push(value as BlobPart);
          got += value.length;
          const frac = Math.min(1, got / total);
          const now = performance.now();
          if (now - lastRing > 100 || frac === 1) {
            lastRing = now;
            setRing(frac);
          }
        }
        clearTimeout(watchdog);
        setRing(1);
        objectUrl = URL.createObjectURL(new Blob(chunks, { type: "video/mp4" }));
        video.src = objectUrl;
        video.load();
        video.addEventListener(
          "canplay",
          () => {
            stage.classList.remove("is-loading");
            stage.classList.add("is-video-ready");
            if (video.duration) seekTo(heroProgress());
          },
          { once: true },
        );
      } catch {
        clearTimeout(watchdog);
        failVideo();
      }
    };

    const startBlobFetch = () => {
      if (started) return;
      started = true;
      stage.classList.add("is-loading");
      void loadHeroBlob();
    };

    let initialised = false;
    let posterTimer: ReturnType<typeof setTimeout> | null = null;
    const initHeroOnce = () => {
      if (initialised) return;
      initialised = true;
      /* The poster wins the bandwidth race by design: the blob only starts
         once the poster has painted, or has failed to. */
      const img = new Image();
      img.onload = startBlobFetch;
      img.onerror = startBlobFetch;
      img.src = POSTER_URL;
      posterTimer = setTimeout(startBlobFetch, 4000);
    };

    /* ── arming and disarming, decided live ──────────────────────────── */
    const rampTimers: ReturnType<typeof setInterval>[] = [];
    const enableScrub = () => {
      if (scrubOn === true) return;
      scrubOn = true;
      stage.classList.remove("is-static");
      initHeroOnce();
      window.addEventListener("scroll", onScroll, { passive: true });
      cache.forEach((c) => {
        c.op = -1;
        c.k = -1;
        c.x = -1;
      });
      /* The opening beat is assembled from the start; its entrance is a CSS
         transition (see the intro effect below), which runs on the
         compositor while the main thread is still loading the page. */
      loadK = 1;
      updateBands(heroProgress());
      onScroll();
      /* The same insurance every reveal on this route carries: scroll
         events are not delivered in every embedded context, timers are. */
      rampTimers.push(
        setInterval(() => {
          if (!scrubOn) return;
          const p = heroProgress();
          /* If the frame loop is not running, the spring never advances.
             When no frame has landed for a third of a second and the page is
             behind the scroll, jump words and footage straight to it. */
          if (Date.now() - lastTickAt > 330 && Math.abs(p - shown) > 0.001) {
            shown = p;
            target = p;
            velocity = 0;
            updateBands(p);
            if (video.duration) seekTo(p);
          }
        }, 250),
      );
    };

    const disableScrub = () => {
      if (scrubOn === false) return;
      scrubOn = false;
      stage.classList.add("is-static");
      window.removeEventListener("scroll", onScroll);
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      pinToFinalStates();
    };

    const mqls = GATES.map((q) => window.matchMedia(q));
    const applyHeroMode = () => {
      if (mqls.some((m) => m.matches)) disableScrub();
      else enableScrub();
    };
    mqls.forEach((m) => m.addEventListener("change", applyHeroMode));

    /* Keep the loop from running while the hero is scrolled past. Failing
       open here is the safe direction: a missed observer costs a running
       rAF, never a hidden word. */
    let io: IntersectionObserver | null = null;
    if ("IntersectionObserver" in window) {
      io = new IntersectionObserver(
        ([e]) => {
          onScreen = e.isIntersecting;
          if (onScreen && scrubOn) onScroll();
        },
        { rootMargin: "10% 0px" },
      );
      io.observe(root);
    }

    applyHeroMode();

    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
      mqls.forEach((m) => m.removeEventListener("change", applyHeroMode));
      window.removeEventListener("scroll", onScroll);
      video.removeEventListener("seeked", releaseSeek);
      if (seekTimer) clearTimeout(seekTimer);
      video.removeEventListener("error", onVideoError);
      if (rafId !== null) cancelAnimationFrame(rafId);
      rampTimers.forEach(clearInterval);
      if (posterTimer) clearTimeout(posterTimer);
      ctrl?.abort();
      io?.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);

  /* The opening line's entrance. Held hidden while the intro covers the
     page, then played as its stairs drop: each word rises through its mask
     in reading order, the gold turn follows, then the deck. The classes
     come off once it has run, so scrolling drives the line from then on
     with no transition lag. Without JS neither class is ever set and the
     line simply shows. */
  const bandA = useRef<HTMLDivElement | null>(null);
  useLayoutEffectSafe(() => {
    const el = bandA.current;
    if (!el) return;
    if (intro === "wait") {
      el.classList.add("is-intro-pending");
      return;
    }
    if (intro !== "play") return;
    el.classList.add("is-intro-pending");
    // Flush styles so the transition starts from the hidden state. Not a
    // frame callback: those pause in a background tab, and the intro's own
    // timers would then run ahead of the words.
    void el.offsetWidth;
    el.classList.add("is-intro-play");
    el.classList.remove("is-intro-pending");
    const done = setTimeout(() => el.classList.remove("is-intro-play"), INTRO_TOTAL_MS);
    return () => clearTimeout(done);
  }, [intro]);

  return (
    <section
      ref={rootRef}
      data-surface="void"
      data-nav-pin
      className="l-scrub"
      style={{ height: `${HERO_VH}vh` }}
    >
      <div ref={stageRef} className="l-stage is-static">
        <div
          className="l-stage-media"
          style={{ backgroundImage: `url(${POSTER_URL})` }}
          aria-hidden
        >
          <video
            ref={videoRef}
            className="l-stage-video"
            poster={POSTER_URL}
            muted
            playsInline
            preload="none"
            aria-hidden="true"
            tabIndex={-1}
          />
        </div>

        {/* The always-on base scrim, so no frame is ever raw behind the page. */}
        <div className="l-stage-scrim" aria-hidden />

        {/* 1 — the hook. Centred, and the only beat that is: the opening
            statement addresses the reader head on, and the four beats after
            it walk around the frame. */}
        <div
          className="l-band l-band-a"
          style={{ ["--intro-word" as string]: `${INTRO_WORD_MS}ms` }}
          ref={(el) => {
            bandRefs.current[0] = el;
            bandA.current = el;
          }}
        >
          <h1 className="l-hero-display l-h1">
            <ScrubWords
              text="Most AI strategies name a duty."
              seed={11}
              spread={0.42}
            />
            <span className="l-h1-turn">
              <ScrubWords
                text="We measure how deep it goes."
                seed={17}
                spread={0.4}
                indexFrom={8}
              />
            </span>
          </h1>
          <p className="l-h1-sub">
            Meridian grades every commitment on a five-rung ladder, from a
            stated aspiration to an enforceable duty.
          </p>
        </div>

        {/* 2 — why the product exists. Left, and big: this is the finding
            the whole page turns on, not a footnote to the hook. */}
        <div
          className="l-band l-band-b"
          ref={(el) => {
            bandRefs.current[1] = el;
          }}
        >
          <p className="l-band-attrib">OECD &middot; AI Policy Observatory</p>
          <p className="l-band-source">
            The OECD read the governance commitments in the
            world&rsquo;s national AI strategies.
          </p>
          <p className="l-hero-display l-band-lede">
            <ScrubWords
              text="Most of them commit to less than they appear to."
              seed={29}
              spread={0.55}
            />
          </p>
          <ul className="l-band-find">
            {/* Three quantities, and only the last one is gold. The first
                two are the setup; "a minority ever set a date" is the
                finding the product exists because of. Colouring all three
                is what an instrument does; colouring one is what an argument
                does, and this is an argument. */}
            {[
              ["Most", "set out actions and goals."],
              ["About half", "name a budget, or who is accountable."],
              ["A minority", "ever set a date."],
            ].map(([qty, rest], i) => (
              <li
                key={qty}
                className={`l-find-row${i === 2 ? " is-gap" : ""}`}
                style={{ ["--th" as string]: (0.08 + i * 0.17).toFixed(2) }}
              >
                <span className="l-find-qty">{qty}</span>
                <span className="l-find-text">{rest}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* 3: what it does. Two short lines of equal weight, centred; the
            verdict takes the accent. The frameworks set what a complete
            regime holds, the verdict weighs the document's own duties, so
            they sit in the note rather than in the claim. */}
        <div
          className="l-band l-band-c"
          ref={(el) => {
            bandRefs.current[2] = el;
          }}
        >
          <p className="l-hero-display l-band-stmt">
            <ScrubWords className="l-stmt-line" text="One document." seed={53} spread={0.3} />
            <ScrubWords
              className="l-stmt-line l-band-key"
              text="Eight verdicts."
              seed={59}
              spread={0.3}
            />
          </p>
          <p className="l-body l-band-note">
            Read against forty-three international frameworks, across eight
            dimensions of governance. Not the industrial policy, the compute or
            the skills.
          </p>
        </div>

        {/* 4 — why it is not the same as everything else. The force ladder,
            drawn as the ladder it is, lighting up rung by rung. */}
        <div
          className="l-band l-band-d"
          ref={(el) => {
            bandRefs.current[3] = el;
          }}
        >
          <p className="l-hero-display l-band-stmt">
            <ScrubWords
              text="We grade force, not vocabulary."
              seed={71}
              spread={0.5}
            />
          </p>
          <ol className="l-ladder-mini">
            {["Aspirational", "Intentional", "Assigned", "Obligatory", "Enforceable"].map(
              (rung, i) => (
                <li
                  key={rung}
                  className={`l-rung-mini${i === 4 ? " is-top" : ""}`}
                  style={{ ["--th" as string]: (0.05 + i * 0.12).toFixed(2) }}
                >
                  <span className="l-rung-tier">T{i}</span>
                  <span className="l-rung-name">{rung}</span>
                </li>
              ),
            )}
          </ol>
          <p className="l-body l-band-note">
            Other tools check whether the words appear. We check what they
            oblige anyone to do, and what follows if nobody does.
          </p>
        </div>

        {/* 5 — the close. Centred, because it is the one to act on. */}
        <div
          className="l-band l-band-e"
          ref={(el) => {
            bandRefs.current[4] = el;
          }}
        >
          <p className="l-hero-display l-band-head">
            <ScrubWords text="No claim without a" seed={83} spread={0.42} />{" "}
            <span className="l-band-key">
              <ScrubWords text="citation." seed={89} spread={0.16} />
            </span>
          </p>
          <p className="l-body l-band-sub">
            Every line of the brief carries the passage it came from. Nothing
            here asks to be taken on trust.
          </p>
          <div className="l-cta l-band-cta">
            <Link href="/workspace" className="l-btn l-btn-primary">
              Benchmark your AI governance
            </Link>
            <Link href="/analysis" className="l-btn l-btn-quiet">
              See a finished analysis
            </Link>
          </div>
        </div>

        {/* The loader ring, and after it the scroll cue. */}
        <svg className="l-ring" viewBox="0 0 48 48" aria-hidden="true">
          <circle
            ref={ringRef}
            cx="24"
            cy="24"
            r="20"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeDasharray="126"
            style={{ strokeDashoffset: "var(--ld, 126)" }}
          />
        </svg>
        <span className="l-scroll-cue" aria-hidden>
          <span className="l-scroll-cue-line" />
        </span>
      </div>
    </section>
  );
}
