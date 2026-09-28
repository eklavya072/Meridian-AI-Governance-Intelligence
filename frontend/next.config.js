/** @type {import('next').NextConfig} */
const nextConfig = {
  // Two ways to ship the same pages. The compose stack runs the standalone
  // Node server behind Caddy. NEXT_OUTPUT=export writes plain HTML, CSS and
  // JS to out/, which the API serves itself (FRONTEND_DIST) so a single
  // container is the whole application, as on the hosted demo. Nothing here
  // needs a server: every page is a client component reading the API.
  output: process.env.NEXT_OUTPUT === "export" ? "export" : "standalone",
  images: { unoptimized: true },
};

module.exports = nextConfig;
