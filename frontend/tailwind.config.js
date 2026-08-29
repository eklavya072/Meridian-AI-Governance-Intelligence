/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      /* ── Color system: black + white + grey, full stop. The old navy/teal
             tokens are REMAPPED (not removed) so every existing component
             resolves to the monochrome scale by construction — no leftover
             blue anywhere. ─────────────────────────────────────────────── */
      colors: {
        black: "#0A0A0A",
        /* ── Grey scale — the prompt's canonical tokens ─────────────── */
        grey: {
          900: "#1A1A1A",
          700: "#404040",
          500: "#737373",
          300: "#D4D4D4",
          100: "#F5F5F5",
          /* intermediate steps for smooth structure */
          950: "#121212",
          800: "#262626",
          600: "#595959",
          400: "#A3A3A3",
          200: "#E5E5E5",
          50: "#FAFAFA",
        },
        /* navy scale — REMAPPED to greys. Keeps class names working. */
        navy: {
          50: "#F7F7F7",
          100: "#EDEDED",
          200: "#DEDEDE",
          300: "#C4C4C4",
          400: "#A3A3A3",
          500: "#8A8A8A",
          600: "#737373",
          700: "#595959",
          800: "#404040",
          900: "#262626",
          950: "#0A0A0A",
        },
        /* teal scale — REMAPPED to greys (light-grey accents on dark,
           pale-grey tints on light). Keeps class names working. */
        teal: {
          50: "#F2F2F2",
          100: "#E5E5E5",
          200: "#D4D4D4",
          300: "#C4C4C4",
          400: "#A3A3A3",
          500: "#8A8A8A",
          600: "#737373",
          700: "#595959",
          800: "#404040",
          900: "#262626",
        },
        surface: "#F5F5F5",
        /* Muted status colors — the one functional exception to the
           monochrome rule (coverage verdicts, risk levels, verification).
           Desaturated so they sit within the grey system. */
        status: {
          green: "#3F7A52", // muted forest green — covered / verified
          amber: "#B07E2B", // muted amber — partial / caution
          red: "#A8483F", // muted red — missing / error
        },
        /* Chart tokens — muted, used by the dashboard charts so Recharts
           never falls back to its own saturated default palette. Coverage
           distribution uses the muted status colors; everything else grey. */
        chart: {
          covered: "#3F7A52",
          partial: "#C9AF7A", // soft gold — softer than amber against red/green
          missing: "#A8483F",
          neutral: "#8A8A8A",
        },
        /* Legacy UNDP aliases — mapped onto the monochrome scale. */
        undp: {
          blue: "#0A0A0A",
          "blue-light": "#404040",
          teal: "#8A8A8A",
          green: "#3F7A52",
          red: "#A8483F",
          yellow: "#B07E2B",
        },
      },

      /* ── Typography: Space Grotesk (display, distinctive grotesque) +
             Public Sans (body, government-grade readability). Set via
             next/font variables; see app/layout.tsx. ───────────────────── */
      fontFamily: {
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
        /* Brand wordmark face (Unbounded) — see app/layout.tsx. */
        brand: ["var(--font-brand)", "ui-sans-serif", "system-ui", "sans-serif"],
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
