/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#0a0f14",
          subtle: "#0f1722",
          panel: "#121c28",
          elevated: "#192636",
        },
        line: {
          DEFAULT: "#243548",
          subtle: "#1c2a3a",
          strong: "#2f465d",
        },
        ink: {
          DEFAULT: "#e6edf6",
          muted: "#92a2b6",
          dim: "#5d6b7e",
        },
        brand: {
          DEFAULT: "#5ec8ff",
          subtle: "#1f8fff",
          deep: "#0f5fa6",
          glow: "rgba(94,200,255,.18)",
        },
        accent: {
          ok: "#37d67a",
          warn: "#f2b94b",
          err: "#ff6b6b",
          info: "#5ec8ff",
        },
      },
      fontFamily: {
        sans: ['"Inter"', '"Segoe UI"', '"SF Pro Display"', '"Helvetica Neue"', "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 16px 36px rgba(0,0,0,.18)",
        elevated: "0 24px 60px rgba(0,0,0,.28)",
        glow: "0 0 0 1px rgba(94,200,255,.28), 0 0 24px rgba(94,200,255,.12)",
      },
      borderRadius: {
        card: "18px",
      },
      fontSize: {
        "2xs": ["10px", { lineHeight: "14px" }],
      },
      backgroundImage: {
        "radial-brand":
          "radial-gradient(circle at top right, rgba(31,143,255,.12), transparent 34%), radial-gradient(circle at bottom left, rgba(55,214,122,.08), transparent 26%), linear-gradient(180deg, #0a0f14 0%, #0f1722 100%)",
      },
    },
  },
  plugins: [],
};
