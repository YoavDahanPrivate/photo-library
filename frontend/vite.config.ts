import releaseVersion from './release-version.mjs';
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react(), releaseVersion()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
