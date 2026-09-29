import localFont from "next/font/local";

/* The landing route's three faces. Loaded here rather than in the root
   layout so the app pages, which never set them, don't download them.
   Self-hosted from app/fonts; the variable files cover every weight used.

   Newsreader (document serif, optical sizing): the printed argument below
   the hero. The landing page's world is ink on paper.

   Schibsted Grotesk: the type that sits on the hero film. The route runs two
   display voices with a job each: the grotesk speaks over the film, and
   Newsreader keeps the argument on paper below it.

   IBM Plex Mono: dimension names, scores, framework versions and section
   numerals in the product frames. Outside the landing, `font-mono` falls
   back to the system monospace. */
const serif = localFont({
  src: [
    { path: "../app/fonts/newsreader-normal.woff2", weight: "200 800", style: "normal" },
    { path: "../app/fonts/newsreader-italic.woff2", weight: "200 800", style: "italic" },
  ],
  variable: "--font-serif",
  display: "swap",
});

const grotesk = localFont({
  src: "../app/fonts/schibsted-grotesk.woff2",
  weight: "400 900",
  variable: "--font-grotesk",
  display: "swap",
});

const mono = localFont({
  src: [
    { path: "../app/fonts/ibm-plex-mono-400-normal.woff2", weight: "400", style: "normal" },
    { path: "../app/fonts/ibm-plex-mono-500-normal.woff2", weight: "500", style: "normal" },
  ],
  variable: "--font-mono",
  display: "swap",
});

/** The serif alone, for the executive brief: the document a minister reads
 *  is set like the landing's printed argument. */
export const serifVariable = serif.variable;

/** Classes that define the three font variables; put them on `.landing`. */
export const landingFontVariables = `${serif.variable} ${grotesk.variable} ${mono.variable}`;
