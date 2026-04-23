/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // We render incident lists as server components but want fresh data on each
  // request in dev; Next respects `cache: 'no-store'` per-fetch, so no extra
  // config is needed here. Kept minimal on purpose.
};

module.exports = nextConfig;
