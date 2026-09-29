/** @type {import('tailwindcss').Config} */
const palette = require("./lib/palette.json");

module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      /* ── Colour: one palette, lib/palette.json ─────────────────────────
             Black, white and one neutral grey scale, plus the three muted
             status colours (verdicts, verification) and the chart tokens.
             Components read the same file for inline colours, so a value
             lives in exactly one place. The old navy/teal/undp aliases, which
             had long since been remapped onto greys, are gone. */
      colors: {
        black: palette.black,
        white: palette.white,
        surface: palette.surface,
        grey: palette.grey,
        status: palette.status,
        chart: palette.chart,
      },

      /* ── Typography: Space Grotesk (display, distinctive grotesque) +
             Public Sans (body, government-grade readability). Set via
             next/font variables; see app/layout.tsx. ───────────────────── */
      fontFamily: {
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
        /* Brand wordmark face (Unbounded) — see app/layout.tsx. */
        brand: ["var(--font-brand)", "ui-sans-serif", "system-ui", "sans-serif"],
        /* Declared so `font-mono` resolves to IBM Plex Mono rather than
           Tailwind's default ui-monospace stack. Without this entry the
           product-screen labels were rendering in the raw system mono — a
           whole extra family nobody chose, measured on the landing. */
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },

      /* Real type scale — 12/14/16/18/24/32/48 with consistent line-height
         ratios (1.5 captions → 1.1 hero). No arbitrary per-component sizes. */
      fontSize: {
        xs: ["0.75rem", "1.5"], // 12 — eyebrows, captions, meta
        sm: ["0.875rem", "1.5"], // 14 — small body, table cells
        base: ["1rem", "1.6"], // 16 — body copy
        lg: ["1.125rem", "1.55"], // 18 — lead / emphasized
        xl: ["1.5rem", "1.3"], // 24 — card titles, section titles
        "2xl": ["2rem", "1.2"], // 32 — page titles
        "3xl": ["3rem", "1.1"], // 48 — hero
      },

      /* ── Shadow tokens — black-based, soft, low opacity. ───────────── */
      boxShadow: {
        sm: "0 1px 2px rgba(10, 10, 10, 0.05)",
        md: "0 4px 12px rgba(10, 10, 10, 0.08)",
      },

      /* Consistent surface radius: cards 12px. */
      borderRadius: {
        card: "12px",
      },

      /* Eyebrow/section-label letter-spacing (Section 6). */
      letterSpacing: {
        eyebrow: "0.05em",
      },
    },
  },
  plugins: [],
};
