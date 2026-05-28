import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Operator console SPA build config.
//
// The console is served by serve_operator_dashboard.py at `/` over the same
// host:port that hosts the dashboard API. To avoid CORS round-trips, the SPA
// calls the local same-origin endpoints (`/v1/...`) directly when deployed.
//
// For local development, set CONSOLE_DEV_PROXY_TARGET=http://127.0.0.1:18094
// (or whichever port the dashboard server is bound to) and `npm run dev`
// will proxy unknown paths there.
const devProxyTarget = process.env.CONSOLE_DEV_PROXY_TARGET ?? "http://127.0.0.1:18094";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/v1": { target: devProxyTarget, changeOrigin: true, secure: false },
      "/healthz": { target: devProxyTarget, changeOrigin: true, secure: false },
      "/metrics": { target: devProxyTarget, changeOrigin: true, secure: false },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    outDir: "dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query", "@tanstack/react-table"],
        },
      },
    },
  },
});
