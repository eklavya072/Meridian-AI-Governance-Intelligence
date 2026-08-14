"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { motion } from "motion/react";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { EASE, DUR } from "@/lib/motion";
import ScrollFloat from "@/components/ScrollFloat";
import { cn } from "@/lib/utils";

export type ModuleStackItem = {
  id: string;
  /** Card title — the module name shown on the deck card's header bar. */
  title: string;
  /** Optional small status on the header bar (dot + text). */
  meta?: ReactNode;
  content: ReactNode;
};

/**
 * Skiper51-style creative carousel, ported natively with the project's
 * `motion` library (no extra dependencies — swiper is not in this project,
 * and the effect is standard transform/opacity animation). Replaces the old
 * Skiper16 sticky scroll deck.
 *
 * One module card is in view at a time: the NEXT card slides in from the
 * right while the CURRENT card recedes (scale-down + shadow, the "creative"
 * prev treatment); navigation loops. Deliberately NO autoplay — these are
 * reading panels (Evaluation, Recommendations, Roadmap, Case Intelligence),
 * not an image reel; the user advances with the arrows, the pagination dots,
 * the "01 / 04" counter, or by swiping the card horizontally.
 *
 * The card chrome is untouched — header band (counter + ScrollFloat title +
 * meta) and the content area are exactly the deck cards that were already
 * there. Only the display animation changed.
 *
 * Cards size to their OWN content: a short module shows a short card, a long
 * one grows. The deck container height is measured from the active card and
 * animated, so switching cards grows/shrinks the deck smoothly — no fixed
 * viewport, no internal scroll, no padding whitespace on short cards.
 */

const NAV_BUTTON_CLS =
  "pressable flex h-8 w-8 items-center justify-center rounded-full border border-[color:var(--border)] bg-white text-navy-950 shadow-sm transition-colors hover:bg-navy-950/5";

export default function ModuleStack({
  items,
}: {
  items: ModuleStackItem[];
}) {
  const [active, setActive] = useState(0);
  const n = items.length;

  // Card height follows the ACTIVE card's content. The container height is
  // measured from the active slide and animated, so switching modules
  // grows/shrinks the deck to fit instead of every card being locked to one
  // fixed height with whitespace padding.
  const [viewportH, setViewportH] = useState<number>(0);
  const slideEls = useRef<(HTMLDivElement | null)[]>([]);

  // Drag-to-advance only on mouse/hover devices: framer-motion applies
  // `touch-action: none` to a draggable element, which would block native
  // vertical scrolling of the content inside the card on touch screens.
  // Desktop keeps the swipe gesture; touch users navigate via the arrows.
  const [canDrag, setCanDrag] = useState(false);
  useEffect(() => {
    setCanDrag(
      typeof window !== "undefined" &&
        window.matchMedia("(hover: hover) and (pointer: fine)").matches
    );
  }, []);

  // A different set of modules (e.g. the coverage tier changed on a re-run,
  // swapping Recommendations for Best Practices or dropping the Roadmap)
  // restarts at the first module. Keyed on the module ids rather than the
  // items array identity — the analysis page rebuilds the array every
  // render, and an identity-keyed effect would fight the user's navigation
  // on any parent re-render.
  const itemsKey = items.map((i) => i.id).join("|");
  useEffect(() => {
    setActive(0);
  }, [itemsKey]);

  // Measure the active slide and drive the container height (animated).
  // Runs before paint so the first render is already correctly sized, and a
  // ResizeObserver keeps it in sync when content inside changes height
  // (e.g. an evidence accordion expanding inside a module). No feedback
  // loop: slides are absolutely positioned and content-sized, so the
  // container height never feeds back into a slide's height.
  useLayoutEffect(() => {
    const el = slideEls.current[active];
    if (!el) return;
    const measure = () => setViewportH(el.offsetHeight);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [active, itemsKey]);

  // Hidden slides are inert — genuinely removed from focus and interaction
  // for the whole subtree (links, accordion toggles inside them can't be
  // tabbed into), so assistive tech and keyboard users only reach the
  // module on display. Synced after every render via an effect rather than
  // a ref callback: framer-motion's motion.div does not re-invoke ref
  // callbacks on re-render (the React `inert` prop is also dropped by it).
  useEffect(() => {
    items.forEach((item, i) => {
      const el = slideEls.current[i];
      if (!el) return;
      if (i === active) el.removeAttribute("inert");
      else el.setAttribute("inert", "");
    });
  }, [active, itemsKey, items]);

  if (n === 0) return null;

  const go = (dir: number) => setActive((a) => (a + dir + n) % n);

  // Distance of item i from the active card, centered so the carousel
  // wraps: for n=4 the positions are 0, +1, ±2, -1 (never 3 cards away in
  // one direction).
  const positionOf = (i: number) => {
    const raw = ((i - active) % n + n) % n;
    return raw > n / 2 ? raw - n : raw;
  };

  return (
    <div>
      {/* Deck viewport: height follows the active card via a CSS transition
          (motion's numeric-height animate skips applying the value on a
          fresh mount, which collapsed the deck to 0px until the first
          navigation; a plain style + transition is deterministic). */}
      <div
        className="relative w-full overflow-hidden transition-[height] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]"
        style={{ height: viewportH || undefined }}
      >
        {items.map((item, i) => {
          const pos = positionOf(i);
          const isActive = pos === 0;
          const hidden = Math.abs(pos) > 1;

          // Slide placement: the next card waits mostly off the right edge
          // (just a sliver peeking so the user sees there is more), the
          // previous card recedes to the left; everything further away is
          // fully off-screen so only one card is really visible at a time.
          let x = "0%";
          if (pos === 1) x = "88%";
          else if (pos === -1) x = "-88%";
          else if (pos > 1) x = "112%";
          else if (pos < -1) x = "-112%";

          return (
            <motion.div
              key={item.id}
              ref={(el) => {
                slideEls.current[i] = el;
              }}
              initial={false}
              animate={{
                x,
                scale: hidden ? 0.94 : pos === 0 ? 1 : 0.95,
                // Side cards stay fully opaque — the "creative" effect comes
                // from position/scale, not translucency. Only cards 2+ away
                // (fully off-screen) are hidden.
                opacity: hidden ? 0 : 1,
              }}
              transition={{ duration: DUR.base, ease: EASE.out }}
              className={cn(
                "absolute inset-x-0 top-0 flex",
                isActive
                  ? "z-30 cursor-grab active:cursor-grabbing"
                  : "pointer-events-none z-20"
              )}

              style={{ transformOrigin: "center" }}
              // Swipe the card sideways to advance — drag is horizontal-only
              // and gated to mouse/hover devices, so vertical scrolling
              // inside the content area still works (and touch screens keep
              // native scrolling instead of framer's touch-action: none).
              drag={isActive && canDrag ? "x" : false}
              dragConstraints={{ left: 0, right: 0 }}
              dragElastic={0.18}
              onDragEnd={(_, info) => {
                if (info.offset.x < -60) go(1);
                else if (info.offset.x > 60) go(-1);
              }}
            >
              {/* Card chrome — unchanged from the scroll deck cards. */}
              <div className="flex w-full flex-col overflow-hidden rounded-xl border border-[color:var(--border)] bg-white shadow-sm">
                {/* Header band — reads as a real card heading: subtle tint,
                    centered display type, position counter, status meta. */}
                <div className="relative shrink-0 border-b border-[color:var(--border)] bg-white px-4 py-4 text-center">
                  <span className="absolute right-3 top-3 text-[11px] font-bold tabular-nums text-navy-950">
                    {String(i + 1).padStart(2, "0")} /{" "}
                    {String(n).padStart(2, "0")}
                  </span>
                  <h4 className="font-display text-lg font-bold tracking-tight text-navy-950">
                    {/* Float-on-scroll reveal (React Bits ScrollFloat) —
                        animation only; inherits the h4's own font/size. */}
                    <ScrollFloat
                      scrollContainerRef={undefined}
                      animationDuration={1}
                      ease="back.inOut(2)"
                      scrollStart="center bottom+=50%"
                      scrollEnd="bottom bottom-=40%"
                      stagger={0.03}
                    >
                      {item.title}
                    </ScrollFloat>
                  </h4>
                  {item.meta && (
                    <div className="mt-2 flex justify-center">{item.meta}</div>
                  )}
                </div>
                {/* Content sized to the card — no fixed max-height, no
                    internal scroll; a short module renders a short card. */}
                <div className="p-4">{item.content}</div>
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* Navigation: arrows + pagination dots. Purely user-driven (no
          autoplay) — this is analytical reading content. */}
      <div className="mt-3 flex items-center justify-center gap-4">
        <button
          type="button"
          aria-label="Previous module"
          className={NAV_BUTTON_CLS}
          onClick={() => go(-1)}
        >
          <ChevronLeftIcon className="h-4 w-4" />
        </button>
        <div className="flex items-center gap-1.5">
          {items.map((item, i) => (
            <button
              key={item.id}
              type="button"
              aria-label={`Go to ${item.title}`}
              onClick={() => setActive(i)}
              className={cn(
                "h-1.5 rounded-full transition-all duration-200",
                i === active
                  ? "w-5 bg-navy-950"
                  : "w-1.5 bg-navy-950/40 hover:bg-navy-950/70"
              )}
            />
          ))}
        </div>
        <button
          type="button"
          aria-label="Next module"
          className={NAV_BUTTON_CLS}
          onClick={() => go(1)}
        >
          <ChevronRightIcon className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
