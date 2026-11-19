import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { build } from "esbuild";
import { createHash } from "node:crypto";

const serviceWorkerVersion = createHash("sha256").update(await readFile("public/sw.js")).digest("hex").slice(0, 16);

const { metafile } = await build({
  entryPoints: { dashboard: "src/main.tsx" },
  outdir: "dist/assets",
  entryNames: "[name]-[hash]",
  assetNames: "[name]-[hash]",
  bundle: true,
  minify: true,
  jsx: "automatic",
  loader: { ".woff": "file", ".woff2": "file" },
  metafile: true,
  define: { __SW_VERSION__: JSON.stringify(serviceWorkerVersion) },
});
const assets = Object.keys(metafile.outputs).map(path => path.replace(/^dist/, ""));
const script = assets.find(path => path.endsWith(".js"));
const style = assets.find(path => path.endsWith(".css"));
const html = await readFile("index.html", "utf8");
await mkdir("dist", { recursive: true });
await cp("public", "dist", { recursive: true });
await writeFile("dist/index.html", html
  .replace("</head>", `  <link rel="stylesheet" href="${style}">\n  </head>`)
  .replace("/src/main.tsx", script));
