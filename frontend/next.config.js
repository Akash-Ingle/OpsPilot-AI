/** @type {import('next').NextConfig} */

// The browser talks to the backend through a SAME-ORIGIN proxy (`/api/v1/*`)
// so the session cookie the backend sets is first-party — third-party cookies
// are blocked by Safari/Brave and being phased out in Chrome. `BACKEND_ORIGIN`
// is the backend's scheme+host (no /api/v1 suffix); defaults to local dev.
const BACKEND_ORIGIN = (
  process.env.BACKEND_ORIGIN || "http://localhost:8000"
).replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (.next/standalone) for a lean Docker image.
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
