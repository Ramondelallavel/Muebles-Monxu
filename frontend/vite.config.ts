import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `vite build --mode artifact` (con VITE_LOCAL=1): un único JS y un único CSS para incrustar en la página del artefacto.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  build: mode === "artifact"
    ? { outDir: "dist-artifact", cssCodeSplit: false, assetsInlineLimit: 100_000_000, chunkSizeWarningLimit: 4000, modulePreload: false,
        rollupOptions: { output: { inlineDynamicImports: true, entryFileNames: "app.js", assetFileNames: "app.[ext]" } } }
    : { chunkSizeWarningLimit: 4000 },
}));
