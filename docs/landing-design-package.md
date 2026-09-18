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

---

## 10. Black, white and grey

The page carries no hue. `--key` is the ink itself at full strength, so
emphasis is a change in LUMINANCE rather than the arrival of a second
colour, and the canvas is a neutral near-black tinted to match footage that
is graded to true greyscale.

This replaced a brass accent, and the reason is worth recording because the
brass was defensible on its own terms. Near-black plus a warm accent under a
high-contrast serif is the single most common destination for any page
briefed as dark, rich or cinematic — it is what a design falls into when
"premium" is the only instruction. Two independent sources said so, and the
page is stronger without it: with no hue to lean on, the hierarchy has to be
carried by size, weight and space, which is where it should have been.

The device survives its own decolouring. The sounding line, the underline
mark, the method spine and the focus ring all still read as one system.

## 11. The type scale

Six roles, in `--t-*`. Sizes are fluid, but the *steps between them* are
fixed ratios, so the hierarchy survives every viewport instead of
collapsing at the ends of the clamps — the failure the previous arbitrary
per-element clamps had at both extremes.

Two decisions worth keeping:

- **Display caps at 6rem**, down from 7. Past that, Newsreader at weight
  300 stops reading as confident and starts reading as a banner.
- **H2 is weight 400, not the display's 300.** At h2 sizes the lighter
  weight stopped holding its own against the body copy beneath it and the
  two roles began reading as one.

Body copy on a dark ground gets all three of the standard corrections
together — more leading, more tracking, and the brighter ink token —
because light type on dark blooms into its background and any one
correction alone under-does it.

## 12. What the numbered labels were

`01 / The finding` and its four siblings are gone. They were eyebrows, and
an eyebrow is a label apologising for a heading that should carry itself.
The step numbers inside the method section stay, because there the sequence
is the information: it is a four-step pipeline and the order is the point.

## 13. The sounding line

The plumb rail was always the page's signature. It now pays out as you
descend: the weight rides the leading edge and the sounded length brightens
behind it. The method section carries the same device at a smaller scale, a
spine drawing down through the four stages.

Both read scroll progress into a CSS custom property rather than React
state, and both treat progress 0 as a presentable state — a plumb line at
rest, an undrawn spine. Nothing on the page depends on the scroll ever
arriving, which is section 8's rule applied to a new mechanism.

## 14. Correction to the fail-safe

`useSequence` chained one timeout per step, and the settle that guaranteed
the finished state waited on that chain. In a backgrounded or
non-composited tab, repeat timers clamp to about a second — so the
eight-step framework sequence authored at 190ms ran for eight seconds
there, and the guarantee inherited the delay. Measured: four of eight cards
still invisible four seconds in.

It now carries an independent deadline, a single timeout armed once for the
whole budget. A lone long timeout is not subject to that clamp. The
sequence animates when the page can animate and simply arrives when it
cannot.

**The general lesson, worth more than the fix:** a fail-safe that depends on
the mechanism it protects is not a fail-safe. Both of this route's earlier
invisible-content bugs had the same shape.


## 15. The scrubbed hero

The hero is a 460vh pinned region holding a sticky viewport-height stage.
Progress through it maps 0..1 and drives the video's `currentTime`, so the
light travelling across the page is moved by the reader rather than by a
clock. Three caption bands own overlapping ranges of that same progress.

**Why a scrub is not a violation of section 8.** The rule bans constructs
whose failure mode is invisible content, and a scrub looks like exactly
that. The split that makes it safe:

- The **video seek** rides a `requestAnimationFrame` lerp, because seeking
  is expensive and needs smoothing. It is decorative and `aria-hidden`.
- The **captions** are written directly from the scroll position, plus a
  500ms poll. They never touch the frame loop.

That split was not theoretical. Driving the bands from the lerped value
first — the obvious reading of the pipeline — meant that when the
compositor stalled, bands two and three stayed at opacity zero for good.
Measured at scroll progress 0.50 with the opening band still on screen.

**Three findings from the build worth keeping:**

1. **Butted bands leave the hero blank.** Ranges that end where the next
   begins produce a stretch of scroll with every band at zero — about 190px
   of footage with no words, twice. Consecutive ranges now overlap by
   exactly one ramp width, so a line is always arriving as another leaves.

2. **A shared class is not a free size token when it also sets box
   properties.** The closing headline borrowed `.l-h2` for its size and
   inherited its `margin: 0`, which beat the auto margins that were meant to
   centre it. It sat 226px off centre. Sized independently now.

3. **Scrims were three times heavier than legibility required.** The
   worst-frame audit returned 11.3 to 11.9 to 1 against a 3.5 floor, which
   is why the footage looked flattened. Halving both scrim alphas lands the
   three bands at 4.9 to 5.5 to 1 — clear of the floor, and of the 4.5 body
   standard, with the film visible through the words.

**Verified:** flick test at 120px holds each beat for 8, 8 and 12
consecutive steps against a floor of 5 to 6; at aggressive 360px steps every
beat still reaches full opacity, so none is skippable.

**Encode:** 1920x1080, crf 21, `-g 8 -keyint_min 8` so every scroll position
seeks to a real keyframe rather than snapping to the nearest one two seconds
away. Greyscale, unblurred — sharpness was the brief. 6.11MB, fetched as a
Blob so it works on hosts without HTTP Range support, behind a progress ring
that the poster is allowed to beat.

**The static hero** covers five conditions — phones, portrait tablets,
coarse-pointer portrait, landscape phones, and reduced motion — decided live
rather than once at load, so a rotation or a preference flip re-arms or
disarms the scrub instead of leaving a blank multi-viewport region. The
five query strings are duplicated between `HeroScrub.tsx` and the stylesheet
and must stay character-for-character identical.

## 16. Five beats, and the constructed pause

The hero is five beats now, and the change that matters most is not the
copy — it is that **the video holds still while text arrives**.

The first cut mapped scroll to video time linearly, so the footage was
always mid-move while a line assembled on top of it: two things moving at
once, neither finishing. Measuring the clip shows why no amount of tuning
could have fixed that. Its per-frame motion never falls below 8.8 and
averages 15.7 — there is no natural pause anywhere in it to land a line on.

So the pause is constructed. Progress maps to video time through a
piecewise-linear curve whose flat segments are HOLDS: each beat pins the
video to one frame for its whole plateau, and the footage travels only in
the gaps between beats. Each band's assembly window sits deliberately
*inside* its hold and just after it opens, so the sequence a reader sees is
always: the page arrives, the page stops, the words assemble.

| Beat | Copy | Placement | Job |
| --- | --- | --- | --- |
| 1 | Measure the depth. | Low left | The hook |
| 2 | The OECD read every national AI strategy on earth. | Left, large | Why the product exists |
| 3 | A policy is only as strong as what it obliges someone to do. | Right | What it is |
| 4 | So it grades force, not vocabulary. | Left | Why it is not the others |
| 5 | You already have the document. | Centred | The act |

Beat 2 was previously a small block in a corner, which read as a caption on
someone else's research. It is the finding the whole product rests on and
now carries the frame.

Beat 4 shows the normative-force ladder rather than describing it — five
rungs, T0 Aspirational to T4 Enforceable, lighting up in order, with the
top rung the only one at full ink. This is the one genuinely distinctive
thing Meridian does, so it is the one thing the hero draws.

The eye is walked low-left, left, right, left, centre, so no two
consecutive beats occupy the same ground.

**Legibility, measured per beat against the real frames:** 7.40, 7.60,
7.71, 7.05, 7.60 to 1, against a 3.5 floor. Sampled on the actual text
element boxes rather than the full-canvas band box, which is the honest
zone to measure now that the bands span the whole stage.

## 17. The sideways middle

The three panels after the hero — the standards, the reading, the proof —
travel horizontally inside a pinned region. Scrolling down still means
moving forward, which is the only thing that makes the device worth using:
it borrows the hero's grammar so the middle of the page reads as one
continuous move rather than three stacked sections.

The failure mode was designed first, not last:

- **Stacked is the default.** With no JS, no transform and no media query
  support, the panels are a plain flex column in normal flow and every one
  of them is reachable. The horizontal behaviour is a class added on top.
- **The transform never touches `requestAnimationFrame`.** Scroll listener
  plus a 500ms poll, written straight to the style attribute.
- **Three gates, evaluated live:** under 1024px, portrait touch, and
  reduced motion all stack it.

**Panel activation is a latch, and it has three independent ways to fire.**
The product frames hide their own contents until active, so whatever drives
that flag must never be able to go false again. A panel activates on the
first of: its centre is horizontally near the middle of the window, OR the
viewport cannot be measured, OR two seconds have passed since it became
vertically visible. The animation plays when the panel arrives; the content
appears regardless of whether that measurement ever succeeds.

**Two bugs worth recording:**

1. **Travel measured against the wrong box.** `rail.scrollWidth -
   rail.clientWidth` is always zero, because the rail is `width:
   max-content` and never overflows its own box — the clipping happens one
   level up. Measured against the window, travel is exactly two panel
   widths and the last panel lands flush.

2. **The second `useSequence` still had the old defect.** `PipelineStages`
   carries its own copy of the hook, and only `ProductFrames`' copy got the
   independent deadline. Under clamped timers the retrieval chunks were
   still arriving five of seven at four seconds. Both copies now have it,
   and the duplication is flagged in the code: they should be extracted the
   next time either is touched.

## 18. The page turns over

The hero is a dark cinema; everything below it is paper. One switch, crossed
once, at the moment the film ends and the argument begins.

The tokens under `.l-content` are the hero's inverted, not a second palette,
so it is still black, white and grey. Every component below reads its colour
through those names, which is why nothing needed rewriting to cross over.
The product screens stop floating as bright rectangles on black and simply
sit on the page they belong to.

`--tshadow` switches off there. Three-layer text shadow is a
type-over-video device; on paper it reads as dirt.

**The colour that is actually in the page** is the coverage vocabulary
inside the product screens: `#3F7A52` covered, `#C9AF7A` partial, `#A8483F`
missing. Those were always there and they mean something, which is the only
kind of colour this page should carry. One slate blue (`--key: #2C5F8A`)
does the interactive work: the link rule, the focus ring, the ladder's top
rung, the track's progress bar. Delete two lines and it is pure greyscale.

## 19. Scroll, third attempt

The clip does not move at a constant rate. Measured per quarter-second, its
motion ranges from **5.9 to 27.6**: the page drops fast early and crawls
later. Two mappings failed on that before this one.

1. **Linear scroll to time.** The fast stretches blurred past, the slow ones
   felt stuck.
2. **Five fixed holds.** Traded that for something worse, a hold-then-lurch
   rhythm, which is the "pauses then gets fast" complaint exactly.

The fix is to drive scroll against the **inverse of the clip's own
cumulative motion curve**, measured frame by frame and baked into
`MOTION_CURVE`. Equal scroll distance then produces equal *visual* change,
so the footage reads at one steady rate the whole way down and the beats can
sit at an even cadence against it. The seek times are deliberately
non-linear in seconds; that is what makes them linear to the eye.

## 20. The track, second attempt

Mapping track progress straight onto travel meant the rail never stopped, so
each panel was correctly framed for one instant and was already sliding as
you began reading. Measured at 6% through the track with the first panel's
copy at **x -90**, ninety pixels off the left edge.

Progress is now split into one segment per gap and eased within each with
smootherstep, which is flat at both ends. The rail is nearly still whenever
a panel is centred and does its moving in between: reading time without the
hold-then-lurch of a hard pause. Measured after: 18px of drift across the
first 6%, against 90+ before.

All three panels also share one shell now. Three different layouts inside a
pinned viewport is what made the track look unformatted.

## 21. Two invisible-content bugs from this pass

1. **The panel headings were not there.** `RollWords` reveals on
   `.l-sec.in`, and the track panels are `.l-pane`. The trigger selector
   never matched, so every heading sat parked 115% below its mask, clipped.
   Measured at `translateY(63.67px)` on a panel that was otherwise fully
   revealed. **A masked reveal whose trigger selector does not match is
   invisible content** — the same class of failure as the rest, arriving by
   a new route: renaming the element the cascade keys on.

2. **A CSS transition stranded a panel's body at zero.** Same root cause as
   the framework cards and the sequence hooks. Panels now carry the settle.

## 22. Type, measured

The audit counted **53 distinct type styles** and **five font families** on
a page whose system is three. Two families were leaking:

- `font-display` in the product-screen recreations pulled the app's Space
  Grotesk, a fourth family competing with the landing's trio. Scoped to the
  landing's sans; the real app is untouched, since those components render
  nowhere else.
- `font-mono` had no entry in the Tailwind config, so it fell through to the
  default `ui-monospace` stack: a fifth family nobody chose. Declared.

Plus one display size carrying two weights and two line-heights at once.
Unified. Families in use after: **Public Sans 235, Newsreader 172, IBM Plex
Mono 33.** Nothing else.

## 23. The hero, second clip

Swapped to the 4K macro of printed type (Pexels 5283825), trimmed to the
steadiest 11 seconds. It is better footage on every axis that matters here:
it is the subject itself (close reading of a printed page), and it is far
steadier. Motion sits between **3.3 and 8.1** where the previous clip ran
**5.9 to 27.6**, so its cumulative curve is nearly a straight line and the
remapping in section 19 barely has to work. Sharp, greyscale, 5.42MB.

**One risk, stated rather than buried:** the words on the page are legible,
and the source text is about physiology. "Golf course" and "handball" are
readable at some frames. A baked blur removes it at the cost of the
sharpness that was asked for; it is one flag on the encode.

The previous clip is kept beside it as `hero-a.mp4` for a one-line switch
back. Both are gitignored except the shipped pair.

## 24. The measured band

Four figures between the argument and the method, each naming its source in
the markup: 8 dimensions, 44 frameworks, 88.7% of citations verified
verbatim, 1,269 tests passing. All from a recorded run or the repository.

The source line under each figure is the point of the section. On a page
whose whole argument is that every claim should cite its evidence, a row of
unattributed numbers would undercut the thing it is there to support.

**A correction it forced:** the hero said "thirty-three international
frameworks". `config/frameworks.yaml` has **44**, and the product screen on
the same page already said 44. Fixed.

The count is driven by `setInterval` with an independent settle timer, not
by a spring or a frame loop, for the reason everything else on this route
is: a number that never finishes counting is worse than one that appears.

## 25. Paper, and the scales

The light stretch was flat because it was a solid fill. Two things fix that
without adding decoration: a fine grain so the surface has tooth, and a
warm-to-cool drift down the page so no two sections sit on the same white.
Both on fixed pseudo-elements, neither costing a repaint.

**Spacing** is now a 4px scale (`--s-1` to `--s-10`) with a shared
`--gutter` and one `--measure`, so every section's left edge agrees.
Previously each section carried its own clamp and none of them lined up.

**Tracking is a function of size**, not a constant: `-0.028em` at display
down to `+0.005em` at body. One flat `-0.018em` across the whole scale is
wrong at both ends — a serif at 96px falls apart into characters without
more negative tracking, and the same face at 17px sets grey without the
space back.

## 26. Two stagger bugs, both found by measuring

1. **Word spaces collapsed in the hero headlines.** `ScrubWords` rendered
   the space *inside* the `overflow: hidden` mask, where it collapses. This
   shipped reading "Becausemostof themcommitless". The identical bug was
   fixed in `RollWords` months ago and reintroduced here by copying the
   structure without the `Fragment`.

2. **The last item in a stagger could never reach full opacity.** The
   multiplier and the final threshold are a pair: peak opacity is
   `(1 - th_last) * multiplier`. The finding rows ran `th_last` 0.74
   against a 3.4 multiplier, capping the third row at **0.884**; the force
   ladder ran 0.80 against 4, capping its **top rung** — the most important
   line in that beat — at 0.836. Permanently dimmer than their siblings for
   no reason a reader could see. Both corrected, and the constraint is now
   written next to the rule.

## 27. The surface ladder

The page was one flat colour per zone: all black, then all white. Both read
badly, and the reason is visible in every reference system worth borrowing
from. **None of them ships a single canvas.** Stripe carries white, soft and
cream. Vercel carries white, soft and soft-2. Resend carries black, card,
elevated, deep AND a light surface.

So the page now steps through five related greyscale surfaces:

| Token | Value | Used by |
| --- | --- | --- |
| `void` | `#0C0C0D` | hero, close, footer |
| `ink` | `#16161A` | the measured band |
| `paper` | `#EFEFEC` | the track, the method |
| `paper-2` | `#E4E4DF` | the bento |

The sequence is **void, paper, ink, paper-2, paper, void**: dark to light,
one dark band through the middle of the light stretch, and a return to the
hero's world at the close.

Each section declares `data-surface` and the ink tokens are redeclared
alongside the canvas, so **a section changes surface without a single
component knowing about it.** Nothing needed rewriting to move between
light and dark.

The grain is tinted from the section's own ink, so one rule gives tooth to a
dark band and a light one without knowing which it is on. A solid fill is
what reads as plain, on any colour.

**Contrast, measured on every surface after the change:** body 6.67 to
10.01, meta 4.79 to 5.58, zero failures. `--ink-3` had to move from
`#78787F` to `#5E5E66`: it measured 3.44 on paper-2 and 3.80 on paper,
both under the floor, and it carries the source lines and tier labels,
which is exactly the small text that needs contrast most.

## 28. Hero type

Every hero line was the same serif at roughly the same size in the same
white, so nothing led and nothing supported. Three voices now, and the
difference between them is the hierarchy:

- **Display serif** carries the statement.
- **Mono** carries anything that is a label, a source or a tier, because
  those are readings rather than prose.
- **Sans** carries the one paragraph per beat.

Colour does the rest: full ink for the line that matters, `--ink-2` for
support, `--ink-3` for attribution, and the accent for the single rung that
is the point — the OECD finding's last row and the ladder's top rung.

**Alignment:** the bands now use the same `--measure` and `--gutter` as
every section below, so the hero's left edge and the page's left edge are
the same line. They were two different numbers before.

## 29. The bento

Five capabilities from the README's own table, five cells, three rows, no
empty ones. **Six columns, not four:** with four, the three middle cells
span two each and the third sits alone on its own row with two dead columns
beside it. Six lets the middle row hold all three.

The cells are deliberately unequal — two raised, three flat, three
footprints — so it reads as a composition rather than a row of boxes.

## 30. The sticky stack

The four stages collect into a deck instead of scrolling past as
independent rows. The pattern is skiper-ui's card stack; the implementation
is not. That one runs on **GSAP ScrollTrigger plus Lenis** and pins by
hijacking the scroll, and on this route a scroll hijack whose frame loop
stalls is a page that cannot be scrolled at all.

Here the stack is pure `position: sticky`, which is layout rather than
animation: it holds with the frame loop dead, with JavaScript off, and under
reduced motion. The only scripted part is the dimming of a card once the
next covers it, and its failure mode is a card that stays bright.

## 31. What the audit found

Asked to check back over the work, four real defects turned up. Three were
mine from this session's refactors.

**1. The reduced-motion net was protecting nothing.** It forced `opacity: 1`
on seven selectors, four of which no longer existed: `.l-split-visual`,
`.l-standards-visual`, `.l-stage-visual` and `.l-stage-copy` all died when
those sections became panes, cells and stack cards. The components that
replaced them were never added. Repointed at the live ones.

**2. The sticky stack never formed.** Three bugs in one mechanism, each
hiding the next, and each found by measuring rather than looking:

- *No travel.* All four cards share one container so they can accumulate,
  which means the scroll room has to come from the cards. Without it the
  container ended at the last card and the deck released before forming.
  Measured: three cards at `top: 11px` instead of their offsets of 110,
  124 and 138.
- *Margin collapse.* The last card's tail margin collapsed straight through
  the container, so the container never grew. The arithmetic gave it away
  exactly: 1563px of cards plus 1504px of margins is 3067, and the measured
  height was 3066 — the missing 256px being precisely that margin.
  `display: flow-root` contains it.
- *Padding on the wrong box.* The first attempt at tail room used the
  container's `padding-bottom`. A sticky box is constrained by its
  containing block's CONTENT box and padding sits outside it, so the
  container grew from 3066 to 3434 and cards two and three released at the
  identical scroll position. The room had to be a margin, inside the
  content box.

The size is arithmetic, not taste: card two's flow top is 734 and it is 415
tall, so it holds until content height minus 415; card four's flow top is
2396 and needs 2258px of scroll to reach rest. Content has to reach
734 + 2258 + 415 = 3407 for the earliest card to outlast the last one.
Verified after: all four stacked at 96 / 110 / 124 / 135.

**3. The bento had an empty cell.** Five cells on a four-column grid leaves
the third middle cell alone with two dead columns. Six columns fits three
across.

**4. Dead CSS.** 18 rules and selector lines for sections that no longer
exist. Some remain inside multi-selector rules; they match nothing and are
harmless, and chasing the rest with a regex risked breaking live rules for
no gain.

**The pattern worth naming:** every one of these was invisible to a
screenshot and obvious to a measurement. The stack in particular looked
plausible at every single scroll position I had sampled before — it only
failed in the gap between samples.

---

## 32 — The reference pass

Five design systems were read in full before anything was touched: monopo
saigon, Lamborghini.com, Hyer Aviation, Structured, and ORYZO AI. They
disagree about almost everything except four points, and those four are what
this pass implemented.

**1. Nothing is pure.** ORYZO states it flatly — never `#fff` for text, never
`#000` for a background, "purity reads as wrong here". Structured runs its
light sections on putty `#c4c3b6`; Hyer's darks carry an indigo cast. The
route's neutrals were `#0C0C0D` / `#EFEFEC` on `#FFFFFF` panels, which is a
screen rather than a place. They are now blue-cast darks (the page's water)
and warm parchment lights (its paper), and the two temperatures are what
make the page read as lit instead of printed.

| | was | is |
|---|---|---|
| `void` | `#0C0C0D` | `#0A0C10` |
| `ink` | `#16161A` | `#141922` |
| `paper` | `#EFEFEC` | `#EDEBE3` |
| `paper-2` | `#E4E4DF` | `#DEDACE` |
| panel (light) | `#FFFFFF` | `#F7F5EE` |
| ink (dark surfaces) | `#F4F4F5` | `#F2F1EC` |
| ink (light surfaces) | `#141416` | `#15181E` |

**2. One accent, and it is rare.** Lamborghini gives Giallo to exactly one
element per screen; Hyer gives clay to one card per page; ORYZO's ember is
credit lines only. `--key` is a warm gold (`#C9AF7A` on water, `#6E5522` on
parchment) and appears on the hero's turn line, the OECD attribution, the
top rung of the force ladder, the track's arc, and the stage numerals.

**3. Colour has to mean something.** The three signal tokens are not
invented: they are the instrument's own coverage verdicts, lifted from the
app's chart constants. They appear in exactly one place on the hero — the
three OECD quantities — because that finding *is* a coverage distribution.
Measured against the film's brightest crest: 3.89 / 3.82 / 3.81 to 1.

**4. Surfaces alternate.** "The page should oscillate, not stay flat" (Hyer);
"alternate full-bleed dark and light section by section to create cinematic
pacing" (Lamborghini). The sequence is void → paper → ink → paper-2 → paper
→ void, and every one of those surfaces now reaches both edges of the
screen. Three of them did not: `.l-sec` and `.l-stats` were capped at the
78rem measure, so the method's parchment was a 1248px rectangle with the
page's own dark showing down either side.

## 33 — What changed, and why

**The hero's voice split in two.** A 300-weight serif at 96px over moving
footage is the costume a page reaches for when it has not decided anything.
Every reference that puts type over media uses a grotesk with tight negative
tracking, so the hero moved to Schibsted Grotesk at 500/600 and `-0.035em`,
capped at `4.05rem` rather than `6rem`. Newsreader keeps the printed
argument on the paper sections. The hero is cinema; the page is a document.

**Beat one was rewritten.** "Read what an AI strategy actually commits to"
names a feature every governance tool has. The line is now *Every AI
strategy promises. / Few of them oblige.* — the second sentence in the
accent, because the whole proposition is the gap between them — and it is
centred, the only beat that is.

**The OECD line came back.** It had been demoted to a `0.72rem` mono label,
which left the page's one piece of external evidence set smaller than the
caption beneath it. It is now a `--t-h3` statement with the source above it.

**The scrims came up.** Peak alpha over the film went from ~0.58 composited
to ~0.47. To keep that legible, the hero's secondary copy holds full ink
rather than `--ink-2`, which measured 2.6:1 against the frame's brightest
crest — not a hierarchy, a line you cannot read. Size and weight carry it
instead, which is what the references do at every scale anyway. Worst
measured value anywhere on the film is now 3.81:1 (large) and 5.37:1 (body).

**The sticky deck became four rows.** It read well in a screenshot and badly
in use: three of the four cards spent most of their scroll buried under the
one on top, so a section whose job is to show a pipeline showed one step at
a time.

**The track travels on an arc.** Each panel is placed by its distance from
the window's centre — a quadratic dip, a 2.6° tip and a slight scale — so
the row reads as points on the rim of a large wheel. The progress indicator
is a circle drawing itself rather than a bar filling up. And the traverse is
compressed into the middle 60% of each segment: pure smootherstep across the
whole gap is never still and never quick, which is why one panel took so
long to hand to the next.

**The page ends on a full screen.** The close was 551px and the footer
100px, so the last viewport was a 249px strip of the previous section's
parchment sitting on a dark band — the page ended on a seam. `.l-close` is
now `100svh` minus the footer's own height.

**The footer is a colophon.** One line of 11px mono, and the repository
beside it, drawn as an SVG rather than a glyph.

**The navbar holds through the hero.** Scrolling a scrubbed hero is one
continuous gesture; a bar that tucks itself away three lines in and returns
four lines later turns that into a flicker. `[data-nav-pin]` marks the
region and the hold runs until its sticky stage releases.

### Defects found by measurement during this pass

- `.landing [data-surface] > *` set `position: relative` at specificity
  (0,2,1) and silently beat `.l-stage { position: sticky }`. The hero
  un-pinned after one viewport and left 700vh of bare void. **This was the
  "black after the first screen".**
- `.l-find-row.is-gap .l-find-qty { color: var(--key) }` painted "A
  minority" gold on top of the red its verdict gives it.
- `--key` at `#8A6D2E` carried the 11px stage numerals at 4.08:1 on
  parchment and 3.6:1 on putty. Now 5.86 and 5.16.
- `--ink-3` on film measured 2.89:1 on the 12.8px tier labels.
- Three surfaces were capped at the measure instead of running full-bleed.

---

## 34 — Down to one colour

The route briefly carried the instrument's three verdict hues — a forest
green, a soft gold, a muted red. Three signals is not a signal: with a colour
on every reading, none of them could be the one that mattered. Lamborghini
puts its giallo on exactly one element per screen and calls the restraint the
brand; Hyer gives clay to a single card per page; ORYZO's ember is credit
lines only. So: gold, and nothing else.

Where it now appears, and nowhere else:

| | why it earns it |
|---|---|
| `We measure it in duties.` | the second half of the opening turn — the whole proposition is the gap between the two lines |
| `A minority` | the OECD finding the product exists because of; the other two quantities are the setup |
| `T4 Enforceable` | the top of the force ladder, which is the page's thesis, and the only rung set larger than its siblings |
| the Meridian mark | opening the close, closing the colophon |
| the track's arc | the one indicator on the horizontal section |
| the stage numerals | 01–04, at 11px |

The product screens keep a three-step coverage scale because the app has one,
but it is now a gold *darkening* — full, half, neutral grey — rather than
green/gold/red. Identical reading, one hue. The real `/analysis` screens are
untouched: those are the product, and their verdict colours carry meaning a
first-time reader of the landing page does not need.

Underlines are gone entirely. `.l-mark` was a tinted band *and* a rule doing
one job, and both drew a line the reader has to look past; it is weight and
full ink now. The footer links shift colour instead of carrying a border.

## 35 — The straight line down the left

The band scrim was `inset: -10%` on `.l-band`, and the band is capped at the
78rem measure. At 1440 that put the ellipse from **-29px to 1468px** — past
both edges of a stage that clips at `overflow: hidden`, while the gradient
was still at roughly a third of its alpha where it got cut. That is the hard
vertical edge on the left and the visible curve at the end.

Spanning `100vw` and centring on the band puts the whole ellipse inside the
frame, so it falls to zero on its own terms and there is nothing left to
clip. Measured after: scrim width 1440px against a 1440px frame.

## 36 — The rows that never alternated

DOM order in a stage row is copy, then visual. The only order rules in the
sheet were on `[data-visual-first="false"]` — which restates that same order.
The `true` case had no rule at all, so **nothing ever swapped sides** and all
four stages rendered identically. That is why the section read as a list.

Fixed, plus a cross-axis offset: the column ratio flips with the sides, and
the copy rides ±1.6rem off centre so no two consecutive stages share a
baseline. The reveal now composes with that resting offset through a `--rest`
/ `--lift` pair rather than snapping back to zero. Measured: copy at x=96 /
visual at 774, then copy at 756 / visual at 168, alternating down the four.

## 37 — Proportion

| | was | is |
|---|---|---|
| the figures band | 558px (62vh) | **208px** — a strip; the full bleed is what makes the surface change read, not the height |
| close + colophon | 901px (100%) | **414px (46%)** — a sign-off, not a second hero |
| colophon | 73px | **53px**, 10px mono |
| track handover | move across 20% of the segment | across **38%** — still starts and ends from rest, at about two thirds the speed |
| the arc | 220ms linear | 520ms on the glide curve |

### Measured after

Zero contrast failures anywhere below the hero. Over the film, worst values:
6.90 (h1), 3.68 (the gold turn, large), 4.18 (gold `A minority`, large), 4.10
(gold `Enforceable` — which is why that rung is set at 20.8px, since gold on
film clears the 3:1 large floor and fails the 4.5 small one), 5.03–7.39 for
every body line. `tsc` clean, `next build` clean, detector `[]`.

---

## 38 — The last pass

**The bar stays for the whole route.** `data-nav-pin` used to hold it only
until the hero's sticky stage released; it now holds it for as long as the
element exists on the page. The landing page is one argument read top to
bottom, and losing its navigation halfway down leaves the reader on a page
with no way off it. The app's own routes still auto-hide — the element is
what opts a route in.

**The figures and the bento are one screen.** They measured 1140px against a
900px viewport: a third of a section's worth of parchment hanging past the
fold. Now `min-height: 20svh` and `80svh` — measured at exactly **180 + 720 =
900**. Stated as min-heights rather than trusted to fall out of the padding,
so content that grows pushes the pair past a screen instead of leaving a gap
under it. The room came from the bento's padding and its cells, not the type.

**The counters were running off the bottom edge.** The band was 558px tall
when the trigger was written and an 80px margin was fine. At 180px the strip
enters, counts for its 1.1s and settles while still sitting on the bottom
edge — so by the time a reader is looking at it the numbers have already
landed. Triggering at three-quarters height instead. Measured across the
entry: 0 → 2 → 7 → 8, 0 → 13 → 39 → 44, 0 → 26.0% → 78.2% → 88.7%.

**The hook.** "An AI strategy is written in words / We measure it in duties"
described the method. This states a claim about the world and lets beat two
prove it:

> **Everyone says the right things.**
> **Almost nobody is bound by them.** ← gold

Set at 50.4px rather than 64.8px.

**The sequence.** Beat three said "Upload the AI strategy. Get a brief that
cites itself," which is what every document tool says, and it left the page
going *finding → generic → mechanism*. It is now specific, and it names the
work before the ladder explains how the work is done:

| | |
|---|---|
| 1 | the claim — everyone says the right things |
| 2 | the evidence — the OECD read them all |
| 3 | **what we do** — eight readings, forty-four frameworks, one brief |
| 4 | **how** — we grade force, not vocabulary, on five rungs |
| 5 | the check — no claim without a citation |

**The greys.** Three changes, all measured rather than nudged by eye:

- The close moved off `void` onto `ink`, and `ink` itself lifted from
  `#141922` to `#171D28`. A full-bleed band of the page's deepest black under
  four sections of parchment reads as an absence rather than a room.
- The colophon moved onto `paper`. The page now ends on the surface the
  argument was read on instead of fading out into black, and there is a hard
  cut under the close rather than two dark sections merging.
- `paper` and `paper-2` were six points of luminance apart, which the eye
  reads as an inconsistency rather than a decision. Widened to `#EFEDE6` and
  `#D9D5C8` — parchment, then putty.
- Both dark surfaces carry one very low radial lift from the top edge
  (3.5% ink), so neither is a flat fill. Deliberately under 4%: at any
  strength you can name it, it is a gradient, and this page does not use
  gradients as decoration. The scrub is exempt — it paints its own film.

Two tokens had to move with the surfaces, both caught by measurement rather
than by looking: `--ink-3` on dark went `#85837A → #8E8C83` (4.45:1 on the
11px source lines, under the floor, once `ink` lightened), and on light
`#5C606A → #4F535C` (4.29:1 on the bento's meta lines once `paper-2`
darkened).

### Measured after

Surfaces in order: void 6300, paper 3915, ink 180, paper-2 720, paper 1929,
ink 362, paper 52. Zero contrast failures below the hero; worst value over
the film 3.68:1 (the gold turn, large text) across 12 sampled elements. No
horizontal overflow. Narrow screens: static hero, stacked track, four rows,
bar visible. `tsc` clean, `next build` clean, detector `[]`.

---

## 39 — The smudges behind the words

`--tshadow` was three stacked black layers, the widest a **44px halo at half
alpha**, applied to every element in a band. Every word on this route is its
own `overflow: hidden` inline-block with a gap beside it, so that halo pooled
*per word* instead of behind the line: what the reader saw was a row of
discontinuous black smudges, one per word, which is worse than the
illegibility it was bought to prevent.

It is gone. The legibility moves to the scrim, where it is one continuous
field — deepened from 0.48/0.32 to 0.72/0.56/0.28 and re-measured against the
worst frame rather than adjusted by eye. **18 elements over the film, all
passing, worst 6.94:1.** The scrim was always the right place for this; the
glyph shadows were a second mechanism doing the same job badly.

## 40 — The mask box

Both flagged alignment problems were the same rule. `.l-sw` used
`vertical-align: bottom` with a 0.14em padding / negative-margin pair to give
descenders room inside the clip. `bottom` aligns each inline-block to the
**line box** bottom rather than the baseline, so a word with a descender and a
word without sat on different lines; and the padding hack only holds while the
clip box matches the em box, which stops being true the moment a heading
wraps.

Baseline alignment, symmetrical padding, negative margins on both sides to
keep the box out of the line-height calculation. Measured: every word on every
line of the h1 and of beat three now shares one bottom edge, no raggedness.

## 41 — Scope

Meridian reads **governance**, and a national AI strategy is much more than
its governance. The page was claiming the whole document. Now:

- the hook names the object precisely — *AI governance commitment*
- the OECD line reads "the governance commitments in the world's national
  AI strategies"
- beat three states the limit outright: *"a national AI strategy also carries
  industrial policy, compute, skills and public investment, and Meridian does
  not score any of them"*
- the CTA is "Benchmark your AI governance"; the pipeline and bento say
  "the document", not "the strategy"

## 42 — The hook, again

> **Every AI governance commitment sounds binding.**
> **Almost none of them are.** ← gold

A claim a policy reader can disagree with, which is what makes them read the
next beat — and beat two is the OECD proving it.

## 43 — Surfaces, and the rest

| | |
|---|---|
| stages section | new `paper-mid` `#E4E1D7` — halfway between the track's parchment and the bento's putty, so the four steps are a room of their own. The page now steps light → mid → putty rather than repeating one tone |
| bento heading | "Five surfaces, one run." removed; the grid is the section |
| the arc | 44px → 64px, 2 → 2.5 stroke, and a travelling head that rotates the full 360° with the stroke. An arc alone reports *how far round*; a mark on the circumference is what makes the motion read as circular |
| the counters | no more `started` latch — it fired once per mount, at the one moment the reader was least likely to be watching. Now a window, not a latch: it replays on every entry, over 1.9s instead of 1.1s. Verified replaying on a second approach |

### DevOps audit

Blast radius: `frontend/app/` and `frontend/components/` only. No backend, no
compose, no Makefile, no observability, no `config/frameworks.yaml`. The
landing route makes **no API calls**, so the `/api/v1` contract is untouched;
CI's `make up` smoke test greps the served HTML for "Meridian", which still
matches from `layout.tsx`. `tsc --noEmit` clean, `next build` clean — the two
things CI's frontend job actually runs. Detector `[]`.

One real finding, fixed: `frontend/.dockerignore` did not exclude
`public/hero/`. `.gitignore` keeps the rejected encodes out of a commit, but
**.gitignore does not apply to a Docker build context** — `COPY . .` was
pulling `hero-a.mp4` and `hero-a.jpg` into every frontend image. Both are
unreferenced (the page loads `hero-scrub.mp4` and `hero-poster.jpg` only).
**6.2MB per image**, now excluded, with `tsconfig.tsbuildinfo` added while
there.

---

## 44 — Beat three, aligned and paid off

Beat three sits on the right edge (`align-items: flex-end`), which
right-aligns its two blocks to each other while their text runs left. A 17ch
headline and a 46ch note therefore had left edges **29 characters apart** —
flush on the right, ragged on the left.

The first fix gave both children `width: min(44ch, 100%)` and made it worse
in a new way: `ch` is font-relative, so 44ch of the display face and 44ch of
the body face are two different widths (496px and 459px). Right edges flush,
left edges 96px apart. The width has to be absolute — `min(31rem, 100%)` —
and the rule needs `.l-band.l-band-c > *` to outrank `.l-band-note`'s own
`max-width`. Measured: both blocks now `l: 848, r: 1344`.

The beat also had no accent. The brief is what it delivers — the readings and
the frameworks are how it is made — so **"one brief."** takes the gold, the
way the turn does in the hook and "A minority" does in the finding. One gold
phrase per beat, always on the payload.

## 45 — The black disc

The closing beat had no `::before` override, so it was the **only** band still
running the base scrim — and the base carries the whole legibility budget for
the glyphs since the text-shadows came off, at **0.72 dead centre**. On a
centred beat that lands as a black disc over the middle of the frame with the
footage visible round the edge.

Brought into line with the other four at 0.40, centred, and wide rather than
deep so the dimming has no edge you can point at. It measures **9.12:1** on
the headline and **8.96:1** on the subline — the copy was never the reason it
was that dark.

## 46 — The rest

| | |
|---|---|
| the arc | 64 → **80px**, 2.5 → 3 stroke, and the settle nearly doubled to **900ms**. At 520ms it snapped to each new position and read as a counter ticking rather than as something being drawn. Head still tracks the stroke 0°→360° |
| the bento | **removed** — component, markup, 86 lines of stylesheet, and its entry in the reduced-motion block. The strip above it is sized to its four figures again rather than to a share of a viewport it no longer splits with anything |
| the steps line | "Four steps. Every one leaves a trail." at **56px**, up from 16 — it had a class with no rule behind it and was rendering at body size |
| method alignment | the section ran edge to edge at the gutter (72px at 1440) while every other section is capped at the 78rem measure and centred (96px). Both children now share the measure: head `l: 96` = stages `l: 96` = stats `l: 96` |
| the colophon | 53 → **40px**, 10 → 9.4px mono, 12 → 11px mark |

### Measured after

Surfaces: void, paper, ink, paper-mid, ink, paper. Over the film, 19 elements,
all passing, worst 5.10:1. Zero contrast failures on every light surface. No
horizontal overflow at 1440 or at 314. `tsc` clean, `next build` clean,
detector `[]`.

---

## 47 — The four stages, rebuilt

Measured before touching anything, at 1440 inside a 1248px measure:

| | visual left | visual right | row height |
|---|---|---|---|
| 01 | — | 1272 | 241 |
| 02 | 168 | — | 338 |
| 03 | — | 1306 | 338 |
| 04 | 134 | — | 338 |

**No two rows shared a single edge, and one row was a hundred pixels
shorter than the rest.** Three separate devices were fighting each other:

- column ratios that flipped `1.05fr 0.95fr` ↔ `0.95fr 1.05fr` between rows
- a `padding-inline` of 72px pulling alternate rows off the measure
- a ±1.6rem cross-axis nudge on the copy

All three were added to make the alternation legible. Alternation *is* the
legibility; it does not need help. They are gone, replaced by one mirrored
grid — even columns, flipped by `order` alone.

Two more things were wrong underneath:

- The body was capped at `46ch` (459px) inside a 588px column, so every copy
  block carried **129px of phantom box** on its inner edge and the gap
  between the halves of a row was never the gap the grid declared. The body
  fills its column now.
- The stage screens sized themselves to their own contents, which is why 01
  came out 241px against 338. A fixed `3 / 2` on `.l-stage-visual` makes them
  four of one thing. Verified: no clipping, no overflow, inner content
  595×395 in a 596×397 box on all four.

### Measured after

Every element in the section sits on one of exactly two pairs of edges —
`96 / 692` and `748 / 1344` — mirrored row to row. All four rows **397px**,
all four bodies **two lines**. At 760px it stacks to one column at `38 / 722`
with no overflow.

## 48 — The words

The names were **Ingestion, Retrieval, Analysis, Brief** — three pieces of
pipeline vocabulary and one noun, which is neither parallel nor the language
the rest of the page speaks. A minister reading this wants to know what the
machine *does* at each step:

> **01 Read · 02 Match · 03 Grade · 04 Report**

Four verbs, in the order the run happens. The technical terms survive inside
the sentences, where they carry their meaning ("each passage is embedded and
ranked per governance dimension"). All four bodies are written to ~150
characters, so the rows are the same shape as well as the same size.

The number and the name were two stacked labels the eye had to read in
sequence before reaching the sentence that matters. They sit on one baseline
now, separated by a hairline — which also gives the four rows a repeating
mark to align on.

`tsc` clean, `next build` clean, detector `[]`, 157 elements sampled for
contrast on the light surfaces with zero failures.

---

## 49 — The hero, retimed

Each beat owns a fifth of the hero's scroll. The question is how it spends it.

| | assemble | **hold** | leave |
|---|---|---|---|
| before | 700px | 288px | ~100px |
| after | 432px | **576px** | 504px |

The hold is now the longest of the three, which is the entire point of a
scrubbed hero — the assembly is only how a line starts. Getting there took
the hero from 700vh to **900vh** (1440px of scroll per beat at a 900px
window) and moved the assembly window earlier rather than making it longer.

Leaving is slightly quicker than arriving, per the asymmetry rule: slow where
the reader is deciding, fast where the system is responding.

## 50 — The departure

The crossfade between beats was `0.02` of scroll — about a hundred pixels at
this window. A line did not leave, it was cut.

The exit now has `0.055` to happen in and publishes its own progress as
`--x`, separate from opacity, so the words can *do* something as they go:

- **Reverse stagger.** Each word subtracts a share of its own threshold from
  `--x`, so the last word of a line leaves first and the first leaves last.
  The line un-writes itself in the opposite direction to the one it was
  written in.
- **Upward lift**, 34% of a line — the words recede rather than fall.
- **5px of blur** on the band. Without it a departing beat and an arriving
  one are two crisp lines overlapping, which the eye reads as two objects
  rather than one handover.

## 51 — The shadows, properly this time

Removing the reveal blur did not fix it because the blur was never the
shadow. The actual sources, all still live:

| | |
|---|---|
| `ProductFrames` shell | `0 28px 80px -12px rgba(0,0,0,0.7)` — an 80px black bloom under **every** product screen, including all four stage panels. This was the one following the animation |
| scan line | `0 0 16px rgba(11,12,14,0.55)`, permanently animating up and down the ingestion panel |
| 7 × `shadow-sm` / `shadow-md` | Tailwind defaults on elements that already had borders |

All gone. Every one of them sat on an element with its own hairline — two
devices doing one job, on a route whose whole system is flat surfaces and
1px rules. **Measured: 0 box-shadows anywhere in `.landing`.**

## 52 — `--tr-h1` was never defined

Two headings — the method head and the close — referenced `var(--tr-h1)`
with no fallback. An undefined `var()` is invalid at computed-value time, so
`letter-spacing` fell back to `normal`: both were running at 50–56px with
**zero negative tracking**, which is the size where its absence shows most.
Defined at `-0.028em`; they now measure -1.57px and -1.39px.

## 53 — Space, and the press

The method section stacked three separate gaps — section padding, a 6rem
margin under the heading, and a 9rem row gap — so the reader crossed nearly
400px of empty parchment between the lede and the first step. Emptiness is
impact only when it is doing something; three in a row is just distance.
Now 40px from lede to first row, 59px between rows, 99px section padding.
Everything in the section aligns on x=96.

Buttons had **no press state at all**, and a 320ms transform. Colour and
feedback are two different jobs and now run at two speeds — 240ms for colour,
140ms for the press — with `scale(0.97)` on `:active`, and hover gated behind
`@media (hover: hover) and (pointer: fine)` so a tap does not leave a button
stuck in its hover state.

## 54 — The indicator turns

A drawn arc reports a fraction; it does not read as *circular*, because at no
moment is anything about it going round. The ring now rotates continuously at
a constant rate — 9s, `linear`, the one place on this page where linear
easing is correct, because constant motion is exactly what it is — with the
progress stroke drawing on top. Turning plus drawing is what makes the
gesture read as a circle being travelled. Held still under
`prefers-reduced-motion`.

### Measured after

19 elements sampled mid-dwell over the film, all passing, worst 4.97:1. 162
elements on the light surfaces, zero failures. Zero box-shadows. No
horizontal overflow at 1440 or 314. `tsc` clean, `next build` clean,
detector `[]`.

---

## 55 — The last word never arrived

The final word of every hero line sat 4–8px low and slightly transparent.
It was not alignment. It was an animation that could not finish.

`--kc` was `(--k - --th) * 1.6` — a fixed ramp of `1/1.6 = 0.625` added on
top of a per-word threshold that reaches **0.47** on the hero and **0.67** on
beat three. `0.47 + 0.625 > 1`, so the last word of a line topped out at
`kc = 0.85` and stayed there: permanently 15% short of full opacity and
sitting 16% of a line-height below its neighbours.

It worked at the old multiplier of 2.6, where the ramp overshot far enough to
clamp. **Slowing the words to 1.6 in pass 53 is what exposed it** — the fix
for "too fast" created "not aligned".

The ramp is now a fraction of what each word has *left*:

```css
--kc: clamp(0, (var(--k) - var(--th)) / max(0.08, (1 - var(--th)) * 0.72), 1);
```

Every word reaches exactly 1 at any threshold and any spread, while still
arriving in order. Measured across all five beats: every word at opacity 1,
every line with one distinct top.

## 56 — The hold is a full viewport now

| | assemble | **hold** | leave |
|---|---|---|---|
| pass 49 | 432px | 576px | 504px |
| now | 450px | **900px** | 540px |

The hero went 900vh → **1100vh**, so a beat owns 1800px and spends half of it
perfectly still. 900px at a 900px window is a full screen of scrolling with
the words finished and motionless.

## 57 — The shadow, rebuilt rather than removed

Deleting it was the wrong call. A flat rectangle with a hard edge against a
background of nearly the same value is worse than a bad shadow.

The original was **one layer**: `0 28px 80px -12px rgba(0,0,0,0.7)`. A single
huge, near-opaque blur is what made it read as a bloom trailing the panel
instead of as the panel sitting above the page. It is now three, the way real
elevation falls off — a 1px contact shadow, a short ambient one, a long soft
cast — at roughly a fifth of the original total alpha.

The other half of the problem: `.l-stage-visual` carried its own 1px border
and square corners while the screen inside carried `rounded-2xl`, so a
rounded panel sat inside a sharp one and the corners showed a sliver of flat
background between them. That is the "weird edges and plain area". The outer
chrome is gone — the screen and its own shadow are the object, 16px radius,
fitting its frame exactly.

## 58 — The rest

| | |
|---|---|
| beat three | ran five lines — eight dimensions listed in full plus a paragraph of scope caveat. A beat crossed in one scroll cannot carry a paragraph. Now: *"Governance only — not the industrial policy, the compute or the skills. Eight dimensions, and the instruments that bind each one."* |
| verdict section | `paper-mid` → `paper`, the same surface as the track. Both now `rgb(239,237,230)` |
| the close | each clause on **one line**, both boxes on the same edges (359/1081), gold on the second. `text-wrap: balance` had been splitting one sentence into ragged parts; the sentence has a full stop in the middle and that is where the break belongs. Type sized down to 39px so the longer clause actually fits, with wrapping restored below 1060px |

### Measured after

19 elements over the film, all passing, worst 5.00:1. 158 on light surfaces,
zero failures. No horizontal overflow at 1440 or 314. `tsc` clean,
`next build` clean, detector `[]`.

---

## 59 — Hero typography: weight, not size

The hero was **500 at 50px** — a middle weight at a middle size, which over
moving footage reads as neither quiet nor loud. Presence over film comes from
weight and tracking, not from scale.

| | was | is |
|---|---|---|
| display weight | 500 | **600** |
| hero size | 50.4px | **59.8px** |
| tracking | -0.035em | **-0.042em** |
| measure | 26ch | **32ch** — the cure for a stacked hero is a wider container, not smaller type |
| setup / turn | same weight | **550 / 700** — hierarchy from contrast, not scale |
| deck | 16.3px, -0.01em | **19.4px, +0.006em** — opens where the display closes, so it reads as a different register |

Plus `font-optical-sizing: auto` so the face draws its display cut rather than
a scaled-up text cut, and tabular lining figures throughout.

## 60 — The departure

There was already an exit. It read as a cut because it was **a fade on a
fade** — the band's own opacity multiplied by the word's — so the last third
of it happened in a handful of pixels.

The words carry it now, with three things at once: they lift, they shrink
0.045, and they **soften**. Blur is the piece that matters. During a
crossfade you otherwise see two distinct sets of words overlapping; blur
bridges them so the eye reads one transformation rather than two objects
swapping. Bounded to 5px — heavy blur is expensive in Safari — and it exists
only while a beat is leaving. Measured across a departure: blur 1.6 → 3.6 →
5.0px as opacity falls 0.67 → 0.27 → 0.

## 61 — The ring, tilted

Flat at 56px it read as a pie chart. `rotateX(58deg)` under a deliberately
short `perspective: 320px` gives the stroke a near edge and a far edge, so
the head travelling round it genuinely goes away and comes back instead of
sliding along an outline — the curve it was missing. A long perspective
flattens the tilt back out and takes the depth with it. The bed is drawn at
0.8 because the far half is further away, which is the one cue that sells a
tilted circle as a circle rather than a squashed oval.

## 62 — Two dark chapters

**Proof** (after the figures strip) and **Method** (before the close). Every
number is lifted verbatim from README.md's measured table — p50 4.9s / p95
6.9s, 36 refused with 429 against 45 admitted, 0 fixable HIGH/CRITICAL,
1,889 MB down from 5,683, 238 SBOM packages — and **each card names its
source**. A page whose argument is "no claim without a citation" cannot put
an unsourced figure on its own landing page.

The Proof grid is six columns carrying five cells as **3 + 3 over 2 + 2 + 2**.
The first arrangement tried was 6 + 2 + 2 + 2, which left one cell alone on a
third row with four empty columns beside it — measured and caught: row sums
1246 / 1245 / **415**. Now both rows sum to 1245 of 1248, `grid-auto-flow:
dense`, no dead corner.

Two other defects the pass caught by measuring rather than looking:

- Two adjacent `ink` sections each painted their own radial lift, which reads
  as a seam across a surface that has no seam. Only the first of a dark run
  gets one now.
- At 375px the card figures rendered at 38.4px against a 29.6px section
  heading — the hierarchy inverted at exactly the size with the least context
  to recover it from. Clamps re-cut so the heading leads on small screens and
  the figure leads inside its cell on large ones.

### Measured after

16 elements over the film, all passing, worst 5.33:1. **191 sampled** across
every light and dark surface, zero failures. No horizontal overflow at 1440
or 375. `tsc` clean, `next build` clean, detector `[]`.

---

## 63 — Gold that is gold

`#C9AF7A` was low chroma with the hue pulled toward red — a tan, which on a
dark ground reads as dull brown rather than as metal. `#E6BC55` lifts the
chroma and swings the hue back toward yellow, and it **measures better at the
same time**: 9.41:1 on ink and 10.89:1 on void, against 7.96 and 9.22. Over
the film the hero's turn went **3.68 → 6.71**.

On parchment there is a hard limit worth stating plainly: a true metallic
gold cannot exist at 4.5:1 on near-white. The floor forces the luminance
down, and a dark yellow is an olive-bronze by definition — physics, not
taste. What *is* available is which way the hue leans. `#6E5522` leant red
and read as mud; `#7D5E0A` leans yellow and reads as the dark end of the same
gold. Measured on the two light surfaces the route actually uses: 5.16:1 on
parchment, 4.62:1 on the mid tone.

## 64 — Typography, as a system rather than one size

The craft floor's tracking floor is **-0.04em**; the hero had been pushed to
-0.042em last pass. Pulled back.

The five beats were five separate type decisions that happened to look
related. They are one voice at four volumes now — display at 3rem / 2.4rem /
1.6rem, with every supporting line in the hero holding **one** size and
measure, so the reader never recalibrates mid-hero.

Also themed, from the craft floor's list of the things models skip most
reliably: **text selection, the caret, the focus ring, and the scrollbar**.
A page that contains no blue shipping a blue selection highlight is the
cheapest tell that it was assembled rather than built.

## 65 — Three structural changes

| | |
|---|---|
| the ring | 58° was past the point where a tilted circle still reads as a circle — the minor axis collapses to **53%** of the major and the eye calls it a line. 34° keeps it at **83%**: unmistakably round, still foreshortened enough for the head to travel in depth. Perspective relaxed 320 → 460px to match |
| the figures | were a full-bleed dark band wedged between the track and the method — a change of surface, and therefore of subject, for four numbers that are the *conclusion* of the argument immediately above them. They now ride inside the track as its closing panel, painting their own ink card |
| "Measured, not claimed" | removed. It was also, precisely, the craft floor's named anti-pattern: *the hero-metric template — big number, small label, supporting stats, accent* |

## 66 — Dead air under the screens

`aspect-ratio: 3/2` made all four stage panels identical, which is what it was
for — but the product screens inside lay out to their own content, so the
ratio bought that equality by hanging **60 to 100px of empty panel** under
each one. Equality at the cost of dead air is padding, not equality. The
panels size to their screens now; the grid they sit in already holds the four
together. Measured after: dead air **0** on all four, at 1440 and at 375.

The glass is three things together, not a blur: the layered cast underneath,
an **inset white ring** for the lit top edge a pane of glass catches, and 2px
of backdrop blur so the parchment grain softens at the boundary. Blur alone
is the decoration version of the effect — it is the ring and the cast that
make it read as a physical object above a surface.

## 67 — The Method chapter, as a ledger

Four boxes of equal size with a heading and a paragraph in each is the shape
every generated page reaches for, and it would have made this chapter look
like the thing it argues against.

A ledger instead: the rule's identifier held in a fixed 7.5rem column, the
claim set against it, a hairline between entries. It is the form a statute is
printed in, which is the register the page is speaking in. The asymmetry is
the point — a narrow measured column against a wide prose one gives the eye a
hard left edge to travel down, and that edge is what makes four separate
rules read as one instrument. Body measure set to 68ch, inside the floor's
65–75ch band.

This is also the one place on the route where monospace carries an actual
reference — `R1`, `R2`, a numeric range, a measured percentage — rather than
wearing monospace as a costume for "technical".

### Measured after

16 elements over the film, all passing, worst 5.91:1. **176 sampled** across
every light and dark surface, zero failures. No horizontal overflow at 1440 or
375; ledger collapses to one column, stage panels carry zero dead air, figures
card keeps its inset so its radius is not clipped by the screen edge.
`tsc` clean, `next build` clean, detector `[]`.

---

## 68 — Three families over the film

The complaint was that the first hero line used a different font from the
lines after it. Measured, it was worse than that — the hero was running
**three** families where it should run two:

| | family | |
|---|---|---|
| `.l-h1` | Schibsted Grotesk | display ✓ |
| `.l-band-lede`, `.l-band-stmt`, `.l-band-head` | Schibsted Grotesk | display ✓ |
| **`.l-band-source`** (the OECD line, 25.6px) | **Public Sans** | the body face doing display work |
| **`.l-rung-name`** (Aspirational … Enforceable, 18px) | **Public Sans** | same |

Both moved to the display family. Verified after: every display selector in
the hero resolves to one family.

### What the references actually gave

The Dribbble shots themselves came back blank — the images are lazy-loaded
and the pages render client-side, so there was nothing to read. But the first
shot's description named its live site, **andyhardy.co**, and that could be
instrumented directly. Its system, measured off the running page:

- **One superfamily and its mono companion, four cuts** — Silka-Medium,
  Silka-SemiBold, SilkaMono-Regular, SilkaMono-Medium. Not two unrelated
  sans faces. This is exactly the failure above.
- **A radical tracking split.** Display and body at `normal`; small uppercase
  labels at **2px to 6px** — 0.17em to 0.46em. Enormous and deliberate. A
  label at 11px with that much air is a different instrument from body text,
  not a shrunken version of it.
- **Opacity for hierarchy**, not separate grey tokens: rgba(255,255,255,
  0.6 / 0.7 / 0.8).

The tracking finding drove a real change here. Every uppercase mono label on
this route had been running its own value — 0.16em on the hero attribution,
0.10em on the ladder tiers, 0.20em on the stage numerals, 0.02em in the
colophon. Four values is not a system. One token at **0.2em** now, with the
trailing letter-space negated so a tracked label still sits on its own edge.

## 69 — The verdict colours come back, in one place only

The coverage scale in the product frames had been flattened to a gold ramp
when the route went to one accent. That was right for the page and wrong for
this component: **these screens are a picture of the product.** The real
`/analysis` draws Covered, Partial and Missing in green, gold and red; a
recreation that draws them in three browns is a recreation of something that
does not exist.

`#3F7A52 / #B08114 / #A8483F`, from `--chart-*`. The one-accent rule governs
the page — its headlines, marks and indicators — not a screenshot of software
with its own established colour language.

## 70 — The circle is gone

Removed entirely: markup, refs, the rAF driver, the spin keyframes, the
tilted wrapper and the reduced-motion branch. It had been through flat,
64px, 80px, tilted 58°, tilted 34° — five passes to make an indicator read as
what it is. An element that needs five passes to justify itself is an element
the page does not need.

## 71 — The figures, as a rail

They were a fourth panel on the track: they arrived, then left, which made
the conclusion of the argument into one more station on it.

They hold the foot of the sticky stage now — a hairline with four readings
hung along it, inline rather than stacked, **82px: 9% of the viewport**,
present for the whole sideways travel and gone when the section is.

One bug this surfaced, worth recording because the class of it recurs: the
count never fired. `useSeen` opened at `r.top < vh * 0.82`, which was right
for a band scrolling through the middle of the frame — but a strip pinned to
the foot of a sticky stage never has a `top` above 0.82 of the viewport.
**Anchored elements need presence tests, not position ones.** Now `r.top < vh
&& r.bottom > 0`. Measured across entry: 0 → 2/10/20.7%/296 → 7/39/78.1%/1117
→ 8/44/88.7%/1269, settled and holding for the rest of the track.

### Measured after

172 sampled across every surface, zero contrast failures. No horizontal
overflow at 1440 or 375; the rail goes static and stacks below the panels on
narrow. `tsc` clean, `next build` clean, detector `[]` (now the v4.3.1
compiled binary at `scripts/impeccable detect`, not `detect.mjs`).

---

## 72 — The dark chapter, and what it is for

The page's surface rhythm is now:

> void (hero) → **paper** (track) → **ink** (figures + rules) → **paper**
> (the four steps) → **ink** (close) → paper (colophon)

One dark chapter between the two light ones, doing two jobs in a deliberate
order: **the figures first, on white cards, then the rules that produced
them.** Numbers, then why to believe them.

The white cards are the whole point of putting them there. A dark section
whose contents are also dark is a change of paint; a dark section holding
light cards is a change of **place**, and it is the only hard contrast on a
route that otherwise moves in half-steps. The cards declare the paper tokens
locally — `--canvas`, `--ink`, `--ink-2` remapped on `.l-stat` — so their
contents resolve against parchment rather than against the ink behind them.
Remapping roles is the cheap way to get a light island on a dark ground
right; hand-picking four hex values is the expensive way to get it wrong.

The figures have now been a full-bleed band, a panel on the track, a hairline
rule pinned to its foot, and finally this. None of the first three put them
anywhere: a band was a change of subject, a panel made the conclusion into a
station, and the rule was so quiet it stopped being a moment at all.

## 73 — The lurch at the end of the track

`p` ran 0 to 1 across the whole pinned section, so the rail was **still
moving at the exact scroll position where the sticky released** — sideways
motion stopped and vertical motion started in the same frame, with nothing
between them.

A lead-in at 6% and a tail at 88%. The traverse now finishes early and the
last stretch of the section is the final panel sitting perfectly still while
the stage is still pinned: the reader arrives, reads, and only then does the
page move on. Section height raised 145vh → 170vh per panel so the dwell is
bought with new scroll rather than taken out of the handover speed.

Measured: rail reaches its final `x` at **f = 0.825** and holds it through
f = 1.0 — roughly **645px** of settled dwell before release.

## 74 — Type and copy

| | was | is |
|---|---|---|
| hero | 59.8px | **46.8px** — 60px is where a headline stops being read in one take and starts being scanned in two. Weight and tracking carry the presence now, and a smaller line leaves the film visible around it, which is the reason there is a film |
| beat three | "Eight readings, forty-four frameworks, one brief." | **"One document, against forty-four frameworks. Eight verdicts."** — the same three facts as an event rather than as a specification. A spec tells a reader what they are buying; this tells them what happens to their document |
| the steps | "Four steps. Every one leaves a trail." | **"Nothing is asserted. Everything is traced."** |
| the colophon | mono, 11px, **0.2em** | **Public Sans, 12.5px, 0.005em** |

The colophon was my own regression. The small-label sweep in pass 68 applied
`--tr-label` to every small line on the route, and a colophon is not a label
— it is prose, a product name and a description. Mono at a fifth of an em
between the letters reads as spaced capitals even with the uppercase
transform gone, which is exactly what it looked like.

### Measured after

177 sampled across every surface, zero contrast failures — including the new
parchment-on-ink card pairing. 16 elements over the film, worst 5.91:1. No
horizontal overflow at 1440 or 375; cards collapse to one column at 325px.
`tsc` clean, `next build` clean, detector **0 findings** across the whole
landing route.

One pre-existing warning sits outside it: `components/RadarChart.tsx:204`
animates `width`, which the detector flags as layout thrash. That file serves
`/analysis`, not this page, so it was left alone.

---

## 75 — The critique, and the method error behind six passes

Two isolated sub-agents, per `critique.md`. The finding that reframes
everything before it:

> `impeccable detect` against **source files** returns `[]`.
> Against the **live URL** it returns **27 findings**.

Every "detector clean" claim in §§39–74 was measuring the wrong target. The
rules that matter — content hidden at rest, computed contrast, clipped
containers — can only be evaluated on a rendered page.

### Tier 1 — integrity (all verified in source before acting)

| | |
|---|---|
| `ProductFrames.tsx:346` | labelled the demo **"Kenya. National AI Strategy 2025-2030"** over a verdict spread, donut split and maturity `63.2` that `docs/ENGINEERING-NOTES.md:357` ties to **India's** run. Kenya published a real strategy of that name. → unattributed label + a visible `Illustrative` chip |
| `layout.tsx:19` | `"UNDP DAI Hub: …"` asserted an affiliation this project does not have, in the string that renders in every search result and link unfurl → rewritten to describe Meridian; Open Graph and Twitter cards added (there were none) |
| `README.md:389` | *"721 passed, 9 skipped. Coverage 60%"* against line 33's *"1,269 passed, 78.1%"* — **the same file contradicting itself**, and the file the footer's "Source" link points to → reconciled |

The fourth, **unresolved**: the OECD finding is the page's premise and its only
unsourced claim — attribution line, zero links, no year, no report title, and
vague quantities where the source publishes exact ones. It cannot be fixed by
inventing a citation.

### Tier 2 — structural

- **The static hero showed one beat of five.** Below 720px, on portrait touch,
  and under reduced motion, the page lost its `<h1>`, the OECD finding, the
  ladder and the scope caveat — a tagline and two buttons. `visibility:
  hidden` also removed the `<h1>` from the accessibility tree. It is now the
  full argument as a stacked document: five beats, one fixed film, one scrim.
  Measured at 375: all five visible, `h1` present, 13 elements over the film
  all passing, worst **10.35:1**.
- **The pinned nav ate one word.** At `scrollY 14,806` the pill covered "not"
  in *"The verdict is not the model's opinion"* — inverting the trust
  chapter's claim. Heading clearance added; measured after, heading top **93**
  against pill bottom **73**.
- **`.l-pane.is-reverse`** set its own columns at specificity 0,2,0 and the
  `@media` reset at 0,1,0 never won — panel two's visual was **139px** against
  342 for its siblings.
- **17 contrast failures** in `PipelineStages.tsx`, min **2.68:1** — Tailwind
  `text-black/40‥50`, which my `.l-*`-scoped sweeps could never have seen.
  Raised to `/62` (5.49:1 on `#F5F5F5`).
- **The chat drawer was live on `/`** — 11 focusable controls and an `<h2>` in
  the landing page's outline. React 18 silently drops an `inert` **prop**, and
  framer-motion drops it again; set on the element instead. Measured: 11 in
  DOM, **0 focusable**.
- **`.l-btn-quiet`'s border** was **2.12:1**, under the 3:1 WCAG 1.4.11
  non-text floor — invisible to a text-only sweep, which is every sweep I ran.

### What the two assessments caught alone

Isolation earned its cost. **Design-only:** the Kenya substitution, the UNDP
claim, the nav occlusion, the `is-reverse` specificity bug, the dead code —
none mechanically detectable. **Mechanical-only:** the 17 Tailwind failures,
the 83.2ch measure, the 34-font-size and 19-duration counts. The design pass
spot-checked contrast and concluded it held; the mechanical pass measured 201
elements and found 17 failures.

### Where the detector is wrong for this page

`Nested cards ×16` fires on recreated product UI inside panels — a
screenshot, not a card system. `Tiny numbered section labels ×4` fires on the
pipeline's 01–04, which the craft floor explicitly permits when "the sequence
itself carries information". `Content invisible at rest` is the desktop
scrub; SSR was checked and the full hero text **is** in the served HTML, and
the mobile path now renders all of it.

### Method note worth keeping

The last contrast finding had **median 4.9:1** and minimum **1.4:1**. My
sweeps composite film + scrim alpha over the darkest frame arithmetically;
the detector screenshots what is actually on screen, blur included. When the
two disagree, the screenshot wins — that is what a reader sees. The opening
beat's scrim went 0.36 → 0.50 on that evidence.

### Measured after

Live detector **27 → 24**; contrast findings **3 → 1** (median now above
floor). 173 elements sampled across every surface, **zero** failures. No
horizontal overflow at 1440 or 375. Desktop scrub intact. `tsc` clean,
`next build` clean.
