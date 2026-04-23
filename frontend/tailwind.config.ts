import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Inter",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "JetBrains Mono",
          "monospace",
        ],
      },
      colors: {
        // Semantic severity palette. Keep these tied to Tailwind defaults so
        // the rest of the UI composes cleanly.
        severity: {
          critical: "#ef4444", // red-500
          high: "#f97316",     // orange-500
          medium: "#eab308",   // yellow-500
          low: "#38bdf8",      // sky-400
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(0,0,0,0.25), 0 0 0 1px rgba(255,255,255,0.04)",
        "card-hover":
          "0 4px 16px -4px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.08)",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
      },
      animation: {
        "pulse-soft": "pulse-soft 2s cubic-bezier(0.4,0,0.6,1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
