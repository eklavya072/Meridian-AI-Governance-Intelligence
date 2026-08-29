"use client";

/**
 * Two text entrances for the landing route.
 *
 * Both render their real text into the DOM on the server and keep it there,
 * so a screen reader, a crawler, and a browser with dead JS all get the
 * sentence. The effect is applied to a visual copy that is hidden from the
 * accessibility tree. Nothing here can leave a line unreadable.
 *
 * RollWords is the page's signature: words rise from behind a mask edge,
 * the way a value settles on a readout. TypeLine is used once, on the
 * section that is about asking a question.
 */

import { Fragment, useEffect, useRef, useState } from "react";

/* Masked text needs descender room, or the tails of g, y and p get cut by
   the overflow. The padding and the matching negative margin give the mask
   somewhere to put them without moving the baseline. */

export function RollWords({
  text,
  className = "",
  as: Tag = "span",
  stagger = 60,
}: {
  text: string;
  className?: string;
  as?: "span" | "h1" | "h2" | "p";
  stagger?: number;
}) {
  const words = text.split(" ");
  return (
    <Tag className={className}>
      <span className="l-sr">{text}</span>
      <span aria-hidden="true">
        {/* The space belongs BETWEEN the masked spans, never inside one:
            a trailing space inside an overflow-hidden inline-block
            collapses, and the words run together. */}
        {words.map((w, i) => (
          <Fragment key={`${w}-${i}`}>
            <span className="l-roll">
              <span
                className="l-roll-in"
                style={{ transitionDelay: `${i * stagger}ms` }}
              >
                {w}
              </span>
            </span>
            {i < words.length - 1 ? " " : null}
          </Fragment>
        ))}
      </span>
    </Tag>
  );
}

/**
 * Types `text` once `active` turns true. Driven by an interval, not the
 * frame loop, and backed by a settle timer that writes the full string
 * regardless of how many ticks actually fired: a throttled tab clamps
 * intervals to about a second, and a half-typed headline is worse than an
 * untyped one.
 */
export function TypeLine({
  text,
  active,
  className = "",
  as: Tag = "span",
  speed = 34,
}: {
  text: string;
  active: boolean;
  className?: string;
  as?: "span" | "h2" | "p";
  speed?: number;
}) {
  const [n, setN] = useState(0);
  const started = useRef(false);

  useEffect(() => {
    if (!active || started.current) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setN(text.length);
      started.current = true;
      return;
    }
    started.current = true;
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setN(i);
      if (i >= text.length) clearInterval(id);
    }, speed);
    const settle = setTimeout(() => setN(text.length), text.length * speed + 900);
    return () => {
      clearInterval(id);
      clearTimeout(settle);
    };
  }, [active, text, speed]);

  const done = n >= text.length;
  return (
    <Tag className={className}>
      <span className="l-sr">{text}</span>
      <span aria-hidden="true">
        {text.slice(0, n)}
        <span className={`l-caret${done ? " is-done" : ""}`} />
      </span>
    </Tag>
  );
}
