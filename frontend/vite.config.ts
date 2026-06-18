import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

async function maybeComponentTagger() {
  try {
    const mod = await import("@codestoryai/component-tagger");
    const tagger = (mod as any).componentTagger;
    return typeof tagger === "function" ? tagger() : null;
  } catch {
    return null;
  }
}

export default defineConfig(async () => {
  const taggerPlugin = await maybeComponentTagger();

  return {
    plugins: [react(), ...(taggerPlugin ? [taggerPlugin] : [])],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: 5173,
    },
  };
});
