import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser always calls same-origin `/api/*`; the dev/preview server proxies to the FastAPI backend,
// so provider credentials and the backend origin never reach the browser bundle.
const apiTarget = process.env.BANKOPS_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const apiProxy = {
  "/api": { target: apiTarget, changeOrigin: true, rewrite: (path: string) => path.replace(/^\/api/, "") },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, strictPort: true, proxy: apiProxy },
  preview: { port: 4173, strictPort: true, proxy: apiProxy },
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 900 },
});
