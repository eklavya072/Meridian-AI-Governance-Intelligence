import { Newsreader, Schibsted_Grotesk, IBM_Plex_Mono } from "next/font/google";

/* The landing route's three faces. Loaded here rather than in the root
   layout so the app pages, which never set them, don't download them.
   Only the weights actually in use are requested.

   Newsreader (document serif, optical sizing): the printed argument below
   the hero. The landing page's world is ink on paper.

   Schibsted Grotesk: the type that sits on the hero film. The route runs two
   display voices with a job each: the grotesk speaks over the film, and
   Newsreader keeps the argument on paper below it.

   IBM Plex Mono: dimension names, scores, framework versions and section
   numerals in the product frames. Outside the landing, `font-mono` falls
   back to the system monospace. */
const serif = Newsreader({
  subsets: ["latin"],
  weight: ["300", "400"],
  style: ["normal", "italic"],
  variable: "--font-serif",
  display: "swap",
});

const grotesk = Schibsted_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-grotesk",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

/** Classes that define the three font variables; put them on `.landing`. */
export const landingFontVariables = `${serif.variable} ${grotesk.variable} ${mono.variable}`;
