# Meridian Landing Page — Design Package

The single creative deliverable. Written before generation, consumed by the build.
Every line of copy below ships verbatim. Band ranges are starting points, validated
by the flick test.

Scope: the landing route only. `/workspace`, `/analysis`, `/frameworks`, `/brief`,
and `/auditor` are not touched.

---

## 1. The brand premise

**Depth.**

A national AI strategy is not judged by what it says. Every one of them says the
right things. It is judged by how far down it goes: whether a principle is followed
by a named actor, a budget line, and a date. The OECD reviewed national AI
strategies and found that most define actions and set goals, about half establish
funding or name responsible actors, and only a minority set implementation
timeframes at all.

That distance, between a promise and a commitment, is what Meridian measures.

The whole site teaches this one idea. The video is a descent. The metric is depth.
The brand mark is already a plumb line hanging on true vertical. Three things that
were designed separately turn out to be the same idea, and the page makes that
visible.

If a section does not serve depth, it does not belong on the page.

---

## 2. The palette

Sampled from the footage: charcoal room, ivory paper, cool white light.

```css
:root{
  --canvas:#0B0C0E;          /* page ground, cool-tinted, never pure black */
  --canvas-deep:#070809;     /* the hero void behind the video */
  --panel:#14161A;           /* cards and raised surfaces */
  --panel-raised:#1C1F24;    /* hover and nested surfaces */
  --hairline:rgba(242,239,233,.10);
  --hairline-strong:rgba(242,239,233,.22);  /* interactive borders, 3:1 */

  --text-primary:#F2EFE9;    /* the paper */
  --text-secondary:#9AA0A8;  /* 7.0:1 on canvas */
  --text-tertiary:#626870;   /* labels only, never body */

  --accent:#F2EFE9;          /* the CTA is paper on charcoal */
  --accent-hover:#FFFFFF;
  --accent-muted:rgba(242,239,233,.14);   /* glows, particles, focus rings */

  /* Measured values only. Never decorative. */
  --covered:#3F7A52;
  --partial:#C9AF7A;
  --missing:#A8483F;
}
```

**The colour rule, and it is the signature restraint:** this page has no decorative
accent colour. The only saturated pixels anywhere are the three coverage verdicts,
and they appear only where something has actually been measured. A colour on this
page always means a finding. That reads as institutional rather than styled, and it
is the opposite of what a generated site does.

Deviation stated out loud: the skill bans near-black with a warm amber accent as a
default reach for "dark and cinematic." This palette avoids it. The accent is the
paper's ivory, not amber, and the gold appears only as the "Partial" verdict.

---

## 3. The type trio

| Role | Face | Weights | Why |
|---|---|---|---|
| Display | **Newsreader** | 300, 400 | A document serif with optical sizing. Ink on paper, which is the footage. Institutional without the fashion-serif look. |
| Body | **Public Sans** | 400, 500 | Already in the project. Commissioned for government digital services. The most honest body face this product could use. |
| Mono | **IBM Plex Mono** | 400, 500 | Dimension labels, scores, framework versions, section numerals. |

Never Inter or Roboto. Space Grotesk and Unbounded are retired from this route.

**Known discontinuity:** the rest of the app runs on Space Grotesk. Clicking from
the landing into `/workspace` will feel like a different typeface, because it is.
Carrying the trio through the app is a separate job and is out of scope here.

---

## 4. The hero

No video. The scroll-scrubbed film was designed, built, and then cut: the
footage was the one piece of the page that could not be made truthful without
a generator, and the product's own screens turn out to be better proof than
any abstraction of them. What replaced it is one composed viewport.

- **Lockup:** the mark beside the wordmark, set in the display serif.
- **H1:** Measure the depth.
- **Sub:** Any strategy can say the right things. Meridian reads yours against eight governance dimensions and the frameworks the world already agreed on, then shows you exactly where it stops.
- **CTAs:** Benchmark your policy (to `/workspace`), See a finished analysis (to `/analysis`).
- **Light:** a single soft shaft behind the lockup, so the hero is a lit room rather than a flat dark rectangle.
- **Cue:** a hairline that falls on a loop, at the foot of the frame.

## 5. The six sections

| # | Section | What carries it |
|---|---|---|
| 01 | The finding | The OECD result drawn as three rungs of a ladder, each bar shorter than the last. |
| 02 | The standards | `FrameworksFrame`: the library assembles, instrument by instrument. |
| 03 | The reading | `AnalysisFrame`: the binding-force gauge sweeps, the coverage donut fills, the dimension verdicts land. |
| 04 | The proof | `AuditorFrame`: a question types itself, sends, the model thinks, the answer writes in, the citation lands. |
| 05 | The method | Four stages, each with its own screen: the scan, the chunks breaking out into vector space, the card deck cycling, the brief assembling with its chart and citations. |
| 06 | The close | The mark, one line, the call to action. |

The standards come before the readings on purpose: a visitor has to know what a
policy is being measured AGAINST before a verdict on it means anything.

Sections 02 to 05 are the product animating itself rather than screenshots of
it: crisp at any resolution, no image payload, no layout shift, and they never
go stale when the UI moves. The screens are framed in a solid bezel, not a
translucent one, so the moving ground behind the page does not show through the
hardware.

**The finding, drawn rather than written.** Three rungs, each harder to reach
than the last: most define actions, about half name who pays, a minority set a
date. The bars carry those words rather than invented percentages, because the
source reports proportions qualitatively. The last rung is the only lit element
in the section, since it is the product's reason to exist.

**Vocabulary is the instrument's own.** Coverage is Covered, Partial, Missing.
Maturity runs Unaddressed, Emerging, Delegated, Operationalized,
Institutionalized. The headline number is the binding-force index, a mean of
stage scores on 0 to 100, and it is never drawn on a five-point scale, which is
a scale this instrument does not have.

## 6. What was cut, and why

Three things were designed and then removed, recorded here so they are not
re-proposed by accident.

**The scroll-scrubbed video hero.** Built in full: blob loader with a progress
ring, dt-normalised lerp, gated seeks, four caption bands with per-beat
entrances, a two-sided scrim, and five static-hero gates. It passed its flick
test at 120, 240 and 360px. It was cut because the footage never arrived and
because the product's own screens are stronger proof than any abstraction of
them. The engine is gone from the tree; the reasoning is here.

**The depth probe.** A press-and-hold interaction that lowered a plumb through
four layers of a policy commitment, stopping at layer one where most real
strategies stop. It is the best idea in this package that is not on the page,
and it is the first thing to bring back if a seventh section is ever wanted.

**The FAQ.** Five real objections in the buyers' own words. Cut to hold the
six-section brief. Worth restoring before launch, because those objections get
asked whether or not the page answers them.

## 6b. The ground

A slow WebGL swell in charcoal and grey, fixed behind the whole page, tuned to
this palette rather than the old one: horizon `#121419`, wave `#7C818B`, crest
`#C9CDD4`, at 72 percent opacity with mouse interaction off. A still gradient
in the same grade sits underneath it, which is what reduced-motion visitors
get, what renders before the canvas mounts, and what remains if WebGL is
unavailable. Nothing above it paints an opaque background.

## 7. The vector layer

- **The plumb line (the signature).** One hairline vertical rule running the entire
  page height, from the top of the hero to the footer. A small plumb diamond rides
  it as the visitor scrolls. Graduated ticks mark each section, and the tick lights
  as its section arrives. It is the brand mark unrolled to full page height. Remove
  it and the page is a different page, which is the loudness test.
- **The graduated dome**, drawn on scroll in 6.3, eight ticks arriving in sequence.
- **Dust.** One fixed background layer, whisper level, drifting on a 90 second
  cycle, matching the dust in the hero beam so the page and the footage are one room.
- All of it honours reduced motion: final states shown, drives stopped, live in both
  directions.

---

## 8. The engineering rule

One rule governs every animation on this route: **no construct whose failure
mode is invisible content.**

That means no motion transition delays, no presence wrapper that holds a child
until an exit reports done, and no IntersectionObserver gating whether
something can be seen. All three have failed in this codebase, in embedded
webviews that stop producing frames, and each time the symptom was content
rendered at full size and full fidelity sitting at opacity zero.

There is a fourth now, found by measurement: the in-view test compared against
`window.innerHeight`, which a non-composited pane reports as **0**, so every
element was permanently "not seen" and the entire page stayed hidden. An
unmeasurable viewport now fails OPEN.

A fifth, same family: any value animated by the motion library's `pathLength`
stops part-drawn if the frame loop never finishes it. The gauge arc and the
donut arcs are now plain stroke-dash geometry written from the same numbers
printed beside them, so a ring can never disagree with its own legend.

What replaces them: scroll listeners with a 500ms rect poll behind them, state
driven by `setTimeout` and `setInterval`, and plain CSS transitions. Then the
fail-safe on top, which is the part that actually guarantees it. A `done` class
lands on a timer a second or two after each entrance begins and asserts the
finished state with `transition: none`. If the transition never advances, the
element still ends up visible, because there is no longer an animation standing
between the class and the computed value. Timers keep firing where frames do
not.

Architecture note: this is a Next.js route, not a standalone folder. The scrub
engine is vanilla JS in a `useEffect` with its own listeners, exactly as specified.
The root layout's `max-w-7xl` wrapper is unconstrained for this route only, via a
scoped CSS rule, so no other page changes.

---

## 9. The copy gate

Every viewer-facing line above ships verbatim. The built page must pass the Phase 9
grep gate before anyone sees it: zero em dashes, zero stock words, plus the body
sweep for AI tells. The deliberate devices here are craft and stay: the staccato
triplet in 6.1, and "Not our opinion of good governance. Theirs."
