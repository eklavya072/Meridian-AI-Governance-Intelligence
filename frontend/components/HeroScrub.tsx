"use client";

/**
 * The scroll-scrubbed hero.
 *
 * A tall pinned region holds a sticky full-viewport stage. Progress through
 * that region maps 0..1 and drives the video's currentTime, so the light
 * sweeping across the page is moved by the reader rather than by a clock.
 * Three caption bands own ranges of that progress and assemble against it.
 *
 * The rule this route is built on still holds, and it is worth stating
 * precisely because a scrub looks like a violation of it: nothing here gates
 * READABLE CONTENT on the frame loop. The video is decorative and aria-hidden;
 * the poster is painted underneath before it exists; the real sections below
 * use the latching reveal hooks and never consult scroll progress. What the
 * scrub can lose is motion, never words.
 */

import { Fragment, useEffect, useRef } from "react";
import Link from "next/link";

/* Scroll distance for the pinned region. Three beats, each needing roughly a
   viewport of fully-settled plateau plus its ramps, plus the viewport the
   sticky stage itself occupies. Paced in vh, never in seconds: a scroll page
   is read in flicks. */
/* Dwell is the point of a scrubbed hero; the assembly is only how it starts.
   At 900vh a beat held for 576px — better than the 288 before it, still less
   than a viewport, so a line was never simply THERE while you read it. At
   1100vh a beat owns 1800px and holds for 900 of them: a full window of
   scrolling with the words finished and perfectly still. */
const HERO_VH = 1100;

/* ── The beat map ─────────────────────────────────────────────────────────
   Five beats, and the video HOLDS STILL on every one of them.

   The first cut mapped scroll to video time linearly, which meant the
   footage was always mid-move while a line was assembling on top of it —
   two things moving at once, neither finishing, and the whole hero read as
   messy. Measuring the clip explains why nothing could fix that by tuning:
   its per-frame motion never drops below 8.8 and averages 15.7, so there
   is no natural pause anywhere in it to land a line on.

   So the pause is constructed. Each beat owns a HOLD, a stretch of scroll
   where the video's time is pinned to a single frame, and the footage
   travels only in the gaps between them. The page arrives, stops, and only
   then does the text assemble. */
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
   words assemble across.

   Measured at a 900px window, each beat owns 1800px of scroll and spends it
   like this: 450px assembling, 900px perfectly still, 450px leaving. Half
   the beat is the hold — the thing every previous version of this table got
   wrong, because the assembly kept eating it. */
const BANDS: Beat[] = [
  { a: 0.0, b: 0.2, ka: 0.005, kb: 0.055, t: 0 },
  { a: 0.2, b: 0.4, ka: 0.205, kb: 0.255, t: 0 },
  { a: 0.4, b: 0.6, ka: 0.405, kb: 0.455, t: 0 },
  { a: 0.6, b: 0.8, ka: 0.605, kb: 0.655, t: 0 },
  { a: 0.8, b: 1.0, ka: 0.805, kb: 0.855, t: 0 },
];

/* ── Progress to video time ───────────────────────────────────────────────
   This table is the clip's own CUMULATIVE MOTION, measured frame by frame
   (difference each frame against the last, take the mean brightness of that
   difference, integrate). Read as (fraction of total movement, seconds).

   It exists because the footage does not move at a constant rate. Measured
   per quarter-second, its motion ranges from 5.9 to 27.6 — the page drops
   fast early and crawls later. Two previous mappings both failed on that:
   a straight linear scroll-to-time made the fast stretches blur past and
   the slow ones feel stuck, and pinning the video to five fixed frames
   traded that for something worse, a hold-then-lurch rhythm.

   This clip is far steadier than the one it replaced: its motion sits
   between 3.3 and 8.1 where the previous ran 5.9 to 27.6, so the curve
   below is nearly a straight line and the remapping barely has to work.
   Driving scroll against the INVERSE of this curve makes equal scroll
   distance produce equal VISUAL change. The clip then reads at one steady
   rate the whole way down, which is the only way the text can sit at an
   even cadence against it. */
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
   way. Update this if the encode is replaced. */
const VIDEO_BYTES = 5679479;

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
}: {
  text: string;
  seed: number;
  spread?: number;
  className?: string;
}) {
  const words = text.split(" ");
  const rand = rng(seed);
  return (
    <span className={className}>
      <span className="l-sr">{text}</span>
      <span aria-hidden="true">
        {words.map((w, i) => {
          const th = (i / Math.max(1, words.length - 1)) * spread + rand() * 0.05;
          /* The space belongs BETWEEN the masked spans, never inside one.
             .l-sw is an overflow-hidden inline-block, and a trailing space
             inside it collapses, so the words run together: this shipped
             reading "Becausemostof themcommitless". The same bug was fixed
             in RollWords months ago and reintroduced here by copying the
             structure without the Fragment. */
          return (
            <Fragment key={`${w}-${i}`}>
              <span className="l-sw">
                <span
                  className="l-sw-in"
                  style={{ ["--th" as string]: th.toFixed(3) }}
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

export default function HeroScrub() {
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
    let rafId: number | null = null;
    let lastTick = 0;
    /* Wall-clock stamp of the last tick that actually ran, so the poll below
       can tell a converged loop from a dead one. */
    let lastTickAt = 0;
    let onScreen = true;
    let scrubOn: boolean | null = null;
    let loadK = 0;
    let objectUrl: string | null = null;

    /* Seek gating. Writing currentTime while a seek is in flight is the
       difference between smooth and choppy in Chrome. Coalesce to the newest
       target and issue exactly one follow-up. */
    let seekBusy = false;
    let pendingTime: number | null = null;

    const requestSeek = (t: number) => {
      if (!video.duration || Number.isNaN(video.duration)) return;
      if (seekBusy) {
        pendingTime = t;
        return;
      }
      seekBusy = true;
      try {
        video.currentTime = t;
      } catch {
        seekBusy = false;
      }
    };
    const onSeeked = () => {
      seekBusy = false;
      if (pendingTime !== null) {
        const t = pendingTime;
        pendingTime = null;
        requestSeek(t);
      }
    };
    /* The deadlock escape: without this a failed seek leaves seekBusy true
       forever and the video freezes on one frame. */
    const onVideoError = () => {
      seekBusy = false;
      pendingTime = null;
      stage.classList.add("is-videoless");
    };
    video.addEventListener("seeked", onSeeked);
    video.addEventListener("error", onVideoError);

    const heroProgress = () => {
      const span = root.offsetHeight - window.innerHeight;
      if (span <= 0) return 0;
      return clamp(-root.getBoundingClientRect().top / span, 0, 1);
    };

    /* ── caption bands, written only on change ───────────────────────── */
    const cache = BANDS.map(() => ({ op: -1, k: -1, x: -1 }));

    const updateBands = (p: number) => {
      BANDS.forEach((band, i) => {
        const el = bandRefs.current[i];
        if (!el) return;
        const { a, b } = band;
        /* The crossfade was 0.02 of scroll — at a 900px window that is about
           a hundred pixels, so a line did not leave, it was cut. The exit now
           has 0.055 to happen in, and it is the SLOWER of the two edges: a
           beat should arrive promptly and be released, not snatched. */
        const fIn = 0.02;
        const fOut = 0.05;
        /* The first band skips the ease-in and the last skips the ease-out,
           so the journey opens and closes on settled text. */
        const inEdge = i === 0 ? 1 : smoothstep(p, a, a + fIn);
        const outEdge =
          i === BANDS.length - 1 ? 1 : 1 - smoothstep(p, b - fOut, b);
        const op = Math.round(inEdge * outEdge * 1000) / 1000;

        /* Exit progress, published separately from opacity so the words can
           DO something as they go rather than just becoming transparent.
           A fade alone reads as a dropped frame; a fade with a lift and a
           touch of blur reads as the line receding. */
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
        if (Math.abs(op - c.op) > 0.002) {
          c.op = op;
          el.style.opacity = String(op);
          el.style.visibility = op < 0.004 ? "hidden" : "visible";
        }
        if (Math.abs(k - c.k) > 0.008) {
          c.k = k;
          el.style.setProperty("--k", String(k));
        }
        if (Math.abs(x - c.x) > 0.008) {
          c.x = x;
          el.style.setProperty("--x", String(x));
        }
      });
    };

    const tick = (now: number) => {
      const dt = Math.min(100, now - (lastTick || now));
      lastTick = now;
      lastTickAt = Date.now();
      const kSm = 0.16;
      shown += (target - shown) * (1 - Math.pow(1 - kSm, dt / 16.667));
      if (Math.abs(target - shown) < 0.0005) {
        shown = target;
        rafId = null;
        lastTick = 0;
      } else {
        rafId = requestAnimationFrame(tick);
      }
      if (video.duration) requestSeek(videoTimeAt(shown));
    };

    /* Captions track the SCROLL, not the lerped video time.
       The lerp exists to smooth seeking, which is expensive; a caption is
       two cheap DOM writes and has no reason to lag the reader's thumb.
       More importantly, `shown` only advances inside requestAnimationFrame
       — so driving the bands from it made the words dependent on the frame
       loop, and a stalled compositor left bands two and three at opacity
       zero for good. Measured: at progress 0.50 the opening band was still
       the one on screen.

       Scroll events and the interval below both write captions; only the
       video seek rides the rAF. That is the whole rule of this route in one
       split. */
    const onScroll = () => {
      target = heroProgress();
      updateBands(target);
      if (rafId === null && onScreen) rafId = requestAnimationFrame(tick);
    };

    /* ── the static, non-scrub presentation ──────────────────────────── */
    const pinToFinalStates = () => {
      BANDS.forEach((_, i) => {
        const el = bandRefs.current[i];
        if (!el) return;
        cache[i].op = -1;
        cache[i].k = -1;
        /* EVERY band renders in the static hero, stacked and in order.
           This used to show only the closing band — the one with the call
           to action — on the reasoning that stacking beats would be "three
           headlines in a pile". The cost of that was not a pile: it was the
           <h1>. Below 720px, on portrait touch, and under
           prefers-reduced-motion, the page lost its headline, the OECD
           finding, the forty-four-framework claim, the force ladder and the
           governance-only scope caveat — the entire argument — leaving a
           tagline and two buttons. `visibility: hidden` also took the <h1>
           out of the accessibility tree and out of rendered indexing.

           A phone is the likeliest first contact this page gets, and a
           civil-service workstation is likelier than a consumer one to have
           reduced motion set. The static hero has to be the argument, not
           an apology for the absence of one. The stacking, spacing and
           per-beat composition are handled in CSS under `.is-static`. */
        el.style.opacity = "1";
        el.style.visibility = "visible";
        el.style.setProperty("--k", "1");
        el.style.setProperty("--x", "0");
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
            if (video.duration) requestSeek(videoTimeAt(heroProgress()));
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
      /* A one-time, time-based ramp for the opening beat, handing over to
         scroll. Driven by a timer rather than rAF so a stalled compositor
         still arrives at assembled text. */
      const t0 = performance.now();
      const ramp = setInterval(() => {
        loadK = clamp((performance.now() - t0) / 2200, 0, 1);
        updateBands(shown);
        if (loadK >= 1) clearInterval(ramp);
      }, 60);
      rampTimers.push(ramp);
      updateBands(heroProgress());
      onScroll();
      /* The same insurance every reveal on this route carries: scroll
         events are not delivered in every embedded context, timers are. */
      rampTimers.push(
        setInterval(() => {
          if (!scrubOn) return;
          const p = heroProgress();
          updateBands(p);
          /* If the frame loop is not running, the lerp never advances and
             the footage sits on whatever frame it stopped at. Seeking is
             the one thing here that legitimately rides rAF — it needs the
             smoothing — but riding it should cost smoothness, not the
             image. When no tick has landed for a second and the video is
             still behind, jump it straight to the scroll position. */
          if (
            Date.now() - lastTickAt > 1000 &&
            video.duration &&
            Math.abs(p - shown) > 0.01
          ) {
            shown = p;
            target = p;
            requestSeek(videoTimeAt(p));
          }
        }, 500),
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
      mqls.forEach((m) => m.removeEventListener("change", applyHeroMode));
      window.removeEventListener("scroll", onScroll);
      video.removeEventListener("seeked", onSeeked);
      video.removeEventListener("error", onVideoError);
      if (rafId !== null) cancelAnimationFrame(rafId);
      rampTimers.forEach(clearInterval);
      if (posterTimer) clearTimeout(posterTimer);
      ctrl?.abort();
      io?.disconnect();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, []);

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
            statement is the page addressing the reader head on, and the
            four beats after it walk around the frame. The line it carried
            before ("Read what an AI strategy actually commits to") named a
            feature rather than the argument — every governance tool reads
            documents. This one states the finding the product exists for. */}
        <div
          className="l-band l-band-a"
          ref={(el) => {
            bandRefs.current[0] = el;
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

        {/* 3 — what it is. Right, so the eye crosses the frame. */}
        <div
          className="l-band l-band-c"
          ref={(el) => {
            bandRefs.current[2] = el;
          }}
        >
          <p className="l-hero-display l-band-stmt">
            {/* "Eight readings, forty-four frameworks, one brief" was a
                specification — three quantities and a deliverable, which
                tells a reader what they are buying rather than what happens
                to their document. This is the same three facts as an event:
                one thing goes in, forty-four instruments are brought to bear
                on it, eight verdicts come out. */}
            <ScrubWords
              text="One document, against forty-four frameworks."
              seed={53}
              spread={0.5}
            />{" "}
            {/* The brief is the thing beat three delivers — the readings and
                the frameworks are how it is made — so it takes the accent,
                the way the turn does in the hook and "A minority" does in
                the finding. One gold phrase per beat, on the payload. */}
            <span className="l-band-key">
              <ScrubWords text="Eight verdicts." seed={59} spread={0.2} />
            </span>
          </p>
          {/* This ran five lines — the eight dimensions listed in full, then
              a paragraph of scope caveat. A beat the reader crosses in one
              scroll cannot carry a paragraph; the dimensions are named on
              the stages below and the scope belongs in the brief, not in the
              hero. One line, and it says the thing that matters: governance,
              not the whole strategy. */}
          <p className="l-body l-band-note">
            Governance only — not the industrial policy, the compute or the
            skills. Eight dimensions, and the instruments that bind each one.
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
            oblige anyone to do, on a five-rung ladder from a stated
            aspiration to an enforceable duty.
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
