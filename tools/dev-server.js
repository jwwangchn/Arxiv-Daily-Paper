/** Simple dev server: serves docs/ statically, proxies /api/* to Worker on port 8787 */
const http = require("http");
const fs = require("fs");
const path = require("path");

const DOCS = path.join(__dirname, "..", "docs");
const WORKER_PORT = Number(process.env.WORKER_PORT || 8787);
const WORKER = `http://127.0.0.1:${WORKER_PORT}`;
const PORT = Number(process.env.PORT || 3000);

const MIME = {
  ".html": "text/html",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

http
  .createServer((req, res) => {
    const requestUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);
    // Proxy /api/* to Worker
    if (requestUrl.pathname.startsWith("/api") || requestUrl.pathname.startsWith("/health")) {
      const options = {
        hostname: "127.0.0.1",
        port: WORKER_PORT,
        path: requestUrl.pathname + requestUrl.search,
        method: req.method,
        headers: { ...req.headers, host: `127.0.0.1:${WORKER_PORT}` },
      };
      const proxy = http.request(options, (proxyRes) => {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        proxyRes.pipe(res);
      });
      req.pipe(proxy);
      proxy.on("error", (e) => {
        res.writeHead(502, { "Content-Type": "text/plain" });
        res.end("Worker unavailable: " + e.message);
      });
      return;
    }

    // Serve static files from docs/
    const filePath = requestUrl.pathname === "/" ? path.join(DOCS, "index.html") : path.join(DOCS, requestUrl.pathname);
    const ext = path.extname(filePath);
    const mime = MIME[ext] || "application/octet-stream";

    fs.readFile(filePath, (err, data) => {
      if (err) {
        res.writeHead(404, { "Content-Type": "text/plain" });
        res.end("Not found: " + requestUrl.pathname);
        return;
      }
      // Keep browser API requests same-origin; this server proxies /api to the Worker.
      if (filePath.endsWith(".html")) {
        const html = data
          .toString()
          .replace("</head>", '<script>window.API_BASE_URL="";</script></head>');
        res.writeHead(200, {
          "Content-Type": mime,
          "Content-Length": Buffer.byteLength(html),
          "Cache-Control": "no-store, no-cache, must-revalidate",
        });
        res.end(html);
        return;
      }
      // Prevent caching JS/CSS in dev mode
      if (ext === ".js" || ext === ".css") {
        res.writeHead(200, {
          "Content-Type": mime,
          "Content-Length": data.length,
          "Cache-Control": "no-store, no-cache, must-revalidate",
        });
        res.end(data);
        return;
      }
      res.writeHead(200, { "Content-Type": mime, "Content-Length": data.length });
      res.end(data);
    });
  })
  .listen(PORT, () => {
    console.log(`Dev server running at http://localhost:${PORT}`);
    console.log(`Worker must be running on port ${WORKER_PORT}`);
  });
