/** @type {import('tailwindcss').Config} */
const colorVar = (name) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: colorVar("--color-bg"),
          subtle: colorVar("--color-bg-subtle"),
          panel: colorVar("--color-bg-panel"),
          elevated: colorVar("--color-bg-elevated"),
        },
        line: {
          DEFAULT: colorVar("--color-line"),
          subtle: colorVar("--color-line-subtle"),
          strong: colorVar("--color-line-strong"),
        },
        ink: {
          DEFAULT: colorVar("--color-ink"),
          muted: colorVar("--color-ink-muted"),
          dim: colorVar("--color-ink-dim"),
        },
        brand: {
          DEFAULT: colorVar("--color-brand"),
          subtle: colorVar("--color-brand-subtle"),
          deep: colorVar("--color-brand-deep"),
        },
        accent: {
          ok: colorVar("--color-accent-ok"),
          warn: colorVar("--color-accent-warn"),
          err: colorVar("--color-accent-err"),
          info: colorVar("--color-accent-info"),
        },
      },
      fontFamily: {
        sans: ['"Inter"', '"Segoe UI"', '"SF Pro Display"', '"Helvetica Neue"', "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "var(--shadow-card)",
        elevated: "var(--shadow-elevated)",
        glow: "var(--shadow-glow)",
      },
      borderRadius: {
        card: "18px",
      },
      fontSize: {
        "2xs": ["10px", { lineHeight: "14px" }],
      },
      backgroundImage: {
        "radial-brand": "var(--bg-radial-brand)",
      },
    },
  },
  plugins: [],
};
