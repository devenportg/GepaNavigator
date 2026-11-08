import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.GEPA_API_PROXY_TARGET ?? "http://127.0.0.1:8000";
const apiProxy = {
  "/api": { target: apiTarget, changeOrigin: true },
  "/health": { target: apiTarget, changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    proxy: apiProxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    proxy: apiProxy,
  },
});
