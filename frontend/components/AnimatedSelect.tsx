"use client";

/**
 * AnimatedSelect — accessible dropdown with a smooth height/opacity open.
 *
 * Communicates: "a choice list is available here" — the list grows out of
 * the trigger origin (Skiper UI origin-aware pattern) rather than popping.
 * Height animates on the inner scroll region (transform/opacity only on the
 * outer motion layer), keeping the open/close under the 300ms ceiling.
 */

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE, DUR } from "@/lib/motion";

export interface SelectOption {
  value: string;
  label: string;
}

export default function AnimatedSelect({
  value,
  onChange,
  options,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  // Keyboard navigation mirrors the native <select> we replace: arrow keys
  // move through options, Home/End jump, Enter selects, Escape closes.
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const selectedIndex = Math.max(
    0,
    options.findIndex((o) => o.value === value)
  );
  const selected = options[selectedIndex];

  function openAndFocus() {
    setOpen(true);
    setActiveIndex(selectedIndex);
  }

  function moveTo(index: number) {
    const clamped = Math.max(0, Math.min(options.length - 1, index));
    setActiveIndex(clamped);
    listRef.current
      ?.querySelectorAll("li")[clamped]
      ?.scrollIntoView({ block: "nearest" });
  }

  function onTriggerKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openAndFocus();
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  function onListKey(e: React.KeyboardEvent) {
    if (!open) return;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        moveTo(activeIndex + 1);
        break;
      case "ArrowUp":
        e.preventDefault();
        moveTo(activeIndex - 1);
        break;
      case "Home":
        e.preventDefault();
        moveTo(0);
        break;
      case "End":
        e.preventDefault();
        moveTo(options.length - 1);
        break;
      case "Enter":
      case " ":
        e.preventDefault();
        if (activeIndex >= 0 && options[activeIndex]) {
          onChange(options[activeIndex].value);
        }
        setOpen(false);
        break;
      case "Escape":
        e.preventDefault();
        setOpen(false);
        break;
    }
  }

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : openAndFocus())}
        onKeyDown={onTriggerKey}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls="animated-select-list"
        className="pressable w-full flex items-center justify-between gap-2 border border-gray-300 rounded-lg px-3 py-2 text-sm text-left bg-white focus:outline-none focus:ring-2 focus:ring-undp-blue hover:border-undp-blue transition-colors"
      >
        <span className={selected ? "text-gray-900" : "text-gray-400 truncate"}>
          {selected ? selected.label : placeholder || "Choose..."}
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: DUR.fast, ease: EASE.out }}
          className="text-gray-400 text-[10px] shrink-0"
          aria-hidden
        >
          ▼
        </motion.span>
      </button>

      <AnimatePresence>
        {open && (
          <motion.ul
            ref={listRef}
            id="animated-select-list"
            role="listbox"
            aria-activedescendant={
              activeIndex >= 0 ? `animated-select-opt-${activeIndex}` : undefined
            }
            onKeyDown={onListKey}
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.99 }}
            transition={{ duration: DUR.fast, ease: EASE.out }}
            style={{ transformOrigin: "top" }}
            className="absolute z-30 mt-1.5 w-full max-h-64 overflow-auto rounded-lg border border-gray-200 bg-white shadow-lg py-1"
          >
            {options.map((o, i) => (
              <li key={o.value}>
                <button
                  type="button"
                  role="option"
                  id={`animated-select-opt-${i}`}
                  aria-selected={o.value === value}
                  onClick={() => {
                    onChange(o.value);
                    setOpen(false);
                  }}
                  onMouseEnter={() => setActiveIndex(i)}
                  onFocus={() => setActiveIndex(i)}
                  className={`w-full text-left px-3 py-2 text-sm transition-colors ${
                    activeIndex === i
                      ? "bg-navy-50 text-undp-blue"
                      : o.value === value
                      ? "bg-navy-50/70 font-medium text-undp-blue"
                      : "text-gray-700 hover:bg-navy-50"
                  }`}
                >
                  {o.label}
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
