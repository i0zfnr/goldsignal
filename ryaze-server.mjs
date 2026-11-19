import { createPublicKey, randomUUID, verify } from "node:crypto";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, resolve } from "node:path";
import "./build.mjs";

const publicKey = createPublicKey({
  key: Buffer.from(process.env.RELAY_PUBLIC_KEY ?? "", "base64"),
  format: "der", type: "spki",
});
const pending = new Map();
const nonces = new Map();
const routes = new Set([
  "GET /api/dashboard", "GET /api/performance", "GET /api/sessions", "POST /api/lot-size",
  "GET /api/pnl", "PUT /api/pnl", "DELETE /api/pnl",
  "GET /api/strategy-b/config", "PUT /api/admin/strategy-b/config",
  "GET /api/admin/telegram", "PUT /api/admin/telegram", "POST /api/admin/telegram/test",
  "PUT /api/push", "DELETE /api/push",
  "GET /api/viewer-profile", "PUT /api/viewer-profile",
  "POST /api/push/status", "POST /api/push/test",
  "GET /api/auth/session", "DELETE /api/auth/session", "POST /api/auth/admin", "POST /api/auth/viewer",
  "GET /api/admin/settings", "POST /api/admin/keys", "DELETE /api/admin/keys", "PUT /api/admin/gemini",
  "GET /api/admin/chat", "POST /api/admin/chat",
  "PUT /api/admin/pause", "GET /api/admin/errors", "GET /api/admin/workers", "POST /api/entry-open",
]);
const mime = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".woff2": "font/woff2", ".woff": "font/woff",
  ".webmanifest": "application/manifest+json", ".png": "image/png",
};

function json(res, status, value) {
  res.setHeader("Cache-Control", "no-store");
  res.writeHead(status, { "Content-Type": "application/json" }).end(JSON.stringify(value));
}

async function readBody(req, limit) {
  const parts = [];
  let length = 0;
  for await (const part of req) {
    length += part.length;
    if (length > limit) throw new Error("Body exceeds limit");
    parts.push(part);
  }
  return Buffer.concat(parts);
}

async function poll(req, res) {
  const timestamp = req.headers["x-relay-time"];
  const nonce = req.headers["x-relay-nonce"];
  const signature = req.headers["x-relay-signature"];
  const now = Date.now();
  if (!/^\d{13}$/.test(timestamp ?? "") || Math.abs(now - Number(timestamp)) > 30000 ||
      !/^[a-f0-9]{32}$/.test(nonce ?? "") || !/^[A-Za-z0-9+/]{86}==$/.test(signature ?? "")) {
    return json(res, 401, { error: "Unauthorized relay" });
  }
  for (const [id, expiry] of nonces) {
    if (expiry < now) nonces.delete(id);
  }
  if (nonces.has(nonce)) return json(res, 401, { error: "Unauthorized relay" });
  const body = await readBody(req, 8 * 1024 * 1024);
  const message = Buffer.concat([Buffer.from(`${timestamp}.${nonce}.`), body]);
  if (nonces.has(nonce) || !verify(null, message, publicKey, Buffer.from(signature, "base64"))) {
    return json(res, 401, { error: "Unauthorized relay" });
  }
  nonces.set(nonce, Number(timestamp) + 30000);
  const result = JSON.parse(body);
  const answered = pending.get(result.id);
  if (answered?.leased && Number.isInteger(result.status) && result.status >= 200 &&
      result.status <= 599 && typeof result.body === "string") {
    const { response } = answered;
    pending.delete(result.id);
    response.setHeader("Cache-Control", "no-store");
    response.setHeader("Content-Type", "application/json");
    if (typeof result.cookie === "string" && /^goldsignal_(viewer|session)=/.test(result.cookie)) {
      response.setHeader("Set-Cookie", /;\s*secure(?:;|$)/i.test(result.cookie) ? result.cookie : `${result.cookie}; Secure`);
    }
    response.writeHead(result.status).end(result.body);
  }
  const waiting = [...pending.values()].find(entry => !entry.leased);
  if (waiting) waiting.leased = true;
  return json(res, 200, waiting?.request ?? null);
}

const server = createServer(async (req, res) => {
  res.setHeader("X-Content-Type-Options", "nosniff");
  try {
    const url = new URL(req.url, "http://localhost");
    if (req.method === "POST" && url.pathname === "/_relay/poll") return await poll(req, res);
    const route = `${req.method} ${url.pathname}`;
    if (routes.has(route)) {
      if (pending.size >= 32) return json(res, 503, { detail: "Live feed busy" });
      const body = await readBody(req, 8192);
      const id = randomUUID();
      const request = { id, method: req.method, path: url.pathname + url.search,
        cookie: req.headers.cookie ?? "", body: body.toString() };
      pending.set(id, { request, response: res, leased: false });
      const timer = setTimeout(() => json(res, 503, { detail: "Windows live feed is unavailable" }), 6000);
      res.once("close", () => { clearTimeout(timer); pending.delete(id); });
      return;
    }
    if (req.method !== "GET" && req.method !== "HEAD") return json(res, 404, { detail: "Not found" });
    const pathname = ["/", "/admin"].includes(url.pathname) ? "/index.html" : url.pathname;
    if (!["/index.html", "/sw.js", "/NOTICE", "/offline.html", "/manifest.webmanifest",
      "/app-icon-192.png", "/app-icon-512.png"].includes(pathname) && !/^\/assets\/[\w.-]+$/.test(pathname)) {
      return json(res, 404, { detail: "Not found" });
    }
    const path = resolve("dist", `.${pathname}`);
    const file = await stat(path).catch(() => null);
    if (!file?.isFile()) return json(res, 404, { detail: "Not found" });
    res.writeHead(200, {
      "Content-Type": mime[extname(path)] ?? "text/plain; charset=utf-8",
      "Content-Length": file.size,
      "Cache-Control": pathname.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-cache",
    });
    if (req.method === "HEAD") return res.end();
    createReadStream(path).on("error", () => res.destroy()).pipe(res);
  } catch {
    if (!res.headersSent) json(res, 400, { detail: "Invalid request" });
    else res.destroy();
  }
});
server.listen(Number(process.env.PORT || 3000), "0.0.0.0");
