import { readFileSync } from "node:fs";
import { defineConfig } from "vite";

const { version } = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf8"),
);
if (
  typeof version !== "string" ||
  !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/.test(version)
) {
  throw new Error("Desktop package.json must declare a valid release version.");
}

export default defineConfig({
  plugins: [
    {
      name: "desktop-version",
      transformIndexHtml(html) {
        return html.replaceAll("__CASEQUARRY_DESKTOP_VERSION__", version);
      },
    },
  ],
});
