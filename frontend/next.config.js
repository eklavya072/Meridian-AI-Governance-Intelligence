const { PHASE_DEVELOPMENT_SERVER } = require("next/constants");

/** @type {(phase: string) => import('next').NextConfig} */
module.exports = (phase) => ({
  // Two ways to ship the same pages. The compose stack runs the standalone
  // Node server behind Caddy. NEXT_OUTPUT=export writes plain HTML, CSS and
  // JS to out/, which the API serves itself (FRONTEND_DIST) so a single
  // container is the whole application, as on the hosted demo. Nothing here
  // needs a server: every page is a client component reading the API.
  output: process.env.NEXT_OUTPUT === "export" ? "export" : "standalone",
  // `next dev` works in its own folder. Sharing .next with a build replaced
  // the dev server's chunks mid-session, and every page on localhost:3000
  // stopped hydrating (its scripts returned 404). Builds keep the default,
  // so the export still lands in out/.
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next",
  images: { unoptimized: true },
});
