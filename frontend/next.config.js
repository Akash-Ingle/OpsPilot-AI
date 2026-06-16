/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (.next/standalone) for a lean Docker image.
  output: "standalone",
  // We render incident lists as server components but want fresh data on each
  // request in dev; Next respects `cache: 'no-store'` per-fetch, so no extra
  // config is needed here. Kept minimal on purpose.
};

module.exports = nextConfig;
