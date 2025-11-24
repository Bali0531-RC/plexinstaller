import { resolve } from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4173,
    host: true
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        guide: resolve(__dirname, "guide.html"),
        faq: resolve(__dirname, "faq.html"),
        terms: resolve(__dirname, "terms.html"),
        privacy: resolve(__dirname, "privacy.html")
      }
    }
  }
});
