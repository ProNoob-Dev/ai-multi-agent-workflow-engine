// Headless verification for the docs-site simulation (no npm deps).
// Launches the Playwright chromium, serves docs/ over http, runs all three
// scenarios end to end, takes screenshots, and records the approve scenario
// as a screencast video for the README.
//
// Usage: node scripts/verify_sim.mjs [--shots-only] [--video-only]
// Env: CHROME_PATH (default: ~/workspace/bin/chrome-no-sandbox.sh)
import { spawn, execFile } from "node:child_process";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { createReadStream } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DOCS = path.join(ROOT, "docs");
const SHOTS = path.join(DOCS, "screenshots");
const DEMO = path.join(DOCS, "demo");
const CHROME = process.env.CHROME_PATH || path.join(process.env.HOME, "workspace/bin/chrome-no-sandbox.sh");
const PORT = 8137;
const DEBUG_PORT = 9222;

const MIME = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".png": "image/png", ".webm": "video/webm", ".json": "application/json" };

function serve() {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      const url = decodeURIComponent(req.url.split("?")[0]);
      const file = path.join(DOCS, url === "/" ? "index.html" : url);
      if (!file.startsWith(DOCS)) { res.writeHead(403); return res.end(); }
      try {
        const data = await readFile(file);
        res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
        res.end(data);
      } catch {
        res.writeHead(404); res.end("not found");
      }
    });
    server.listen(PORT, "127.0.0.1", () => resolve(server));
  });
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function getJson(url) {
  const res = await fetch(url);
  return res.json();
}

class CDP {
  constructor(wsUrl) { this.ws = new WebSocket(wsUrl); this.n = 1; this.pending = new Map(); this.events = []; }
  async open() {
    await new Promise((res, rej) => { this.ws.onopen = res; this.ws.onerror = () => rej(new Error("CDP socket failed")); });
    this.ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.id && this.pending.has(d.id)) { const p = this.pending.get(d.id); this.pending.delete(d.id); d.error ? p.rej(new Error(d.error.message)) : p.res(d.result); }
      else if (d.method) this.events.push(d);
    };
  }
  send(method, params = {}, ms = 30000) {
    const id = this.n++;
    return new Promise((res, rej) => {
      const t = setTimeout(() => { this.pending.delete(id); rej(new Error("CDP timeout: " + method)); }, ms);
      this.pending.set(id, { res: (v) => { clearTimeout(t); res(v); }, rej: (e) => { clearTimeout(t); rej(e); } });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error("page JS error: " + JSON.stringify(r.exceptionDetails).slice(0, 500));
    return r.result.value;
  }
  async shot(file) {
    const r = await this.send("Page.captureScreenshot", { format: "png" });
    await writeFile(file, Buffer.from(r.data, "base64"));
  }
  async scrollTo(y) {
    await this.eval(`scrollTo({top: ${y}, behavior: "instant"})`);
    await sleep(600);
  }
}

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? " — " + detail : ""}`);
}

async function main() {
  const shotsOnly = process.argv.includes("--shots-only");
  const videoOnly = process.argv.includes("--video-only");
  await mkdir(SHOTS, { recursive: true });
  await mkdir(DEMO, { recursive: true });
  const server = await serve();

  const chrome = spawn(CHROME, [
    "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
    `--remote-debugging-port=${DEBUG_PORT}`, "--window-size=1440,900",
    "about:blank",
  ], { stdio: "ignore" });

  let target;
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    try { const list = await getJson(`http://127.0.0.1:${DEBUG_PORT}/json`); target = list.find((t) => t.type === "page"); if (target) break; } catch { /* not up yet */ }
  }
  if (!target) throw new Error("chrome did not start");

  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.open();
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await cdp.send("Page.navigate", { url: `http://127.0.0.1:${PORT}/index.html` });
  await sleep(2500);

  const errors = await cdp.eval(`window.__errs ? window.__errs.join("\\n") : "none"`);
  await cdp.eval(`window.__errs = []; window.addEventListener("error", e => window.__errs.push(String(e.message)))`);

  async function click(selector) {
    const sel = JSON.stringify(selector);
    return cdp.eval(`(() => { const el = document.querySelector(${sel}); if (!el) return "missing: " + ${sel}; el.click(); return "ok"; })()`);
  }
  const trace = () => cdp.eval(`[...document.querySelectorAll("#sim-trace-list li")].map(li => li.textContent.trim()).join(" | ")`);
  const resultTitle = () => cdp.eval(`document.getElementById("sim-result-title").textContent`);
  const narration = () => cdp.eval(`document.getElementById("sim-narration").textContent`);
  const particleOn = () => cdp.eval(`document.getElementById("sim-particle").classList.contains("go")`);

  // --- Console errors on load ---
  check("page loads without JS errors", (await cdp.eval(`window.__errs.length`)) === 0);

  // --- Scenario 1: validate (no gate, no saga) ---
  await click('[data-scenario="validate"]');
  await click("#sim-play");
  await sleep(7000);
  let t = await trace();
  check("validate: router + tools traced", t.includes("classify intent") && t.includes("lookup_invoice") && t.includes("validate_invoice"), t);
  check("validate: result valid", (await resultTitle()).includes("valid"), await resultTitle());
  check("validate: particle travelled", await particleOn());
  await cdp.eval(`document.getElementById("sim").scrollIntoView()`);
  await sleep(400);
  await cdp.shot(path.join(SHOTS, "06-sim-validate.png"));

  // --- Scenario 2: approve with HITL hold + approve ---
  await click('[data-scenario="approve"]');
  await click("#sim-play");
  await sleep(6500); // reaches the gate (6 steps x ~950ms)
  const gateHolding = await cdp.eval(`document.getElementById("sim-node-hitl").classList.contains("holding")`);
  const approveEnabled = await cdp.eval(`!document.getElementById("sim-approve").disabled`);
  check("approve: HITL gate holds the flow", gateHolding && approveEnabled, `holding=${gateHolding} approveEnabled=${approveEnabled}`);
  await cdp.shot(path.join(SHOTS, "07-sim-gate-hold.png"));
  await cdp.eval(`document.getElementById("sim-node-hitl").scrollIntoView({block: "center"})`);
  await sleep(500);
  await cdp.shot(path.join(SHOTS, "12-sim-gate-particle.png"));
  // Reject path first on this same run? No: approve, then test reject separately.
  await click("#sim-approve");
  await sleep(4500);
  t = await trace();
  check("approve: saga ran after approval", t.includes("reserve funds") && t.includes("post ledger entry") && t.includes("notify vendor"), t);
  check("approve: result paid", (await resultTitle()).includes("paid"), await resultTitle());
  await cdp.shot(path.join(SHOTS, "08-sim-approved.png"));

  // --- Reject path ---
  await click('[data-scenario="approve"]');
  await click("#sim-play");
  await sleep(6500);
  await click("#sim-reject");
  await sleep(800);
  check("reject: no side effects", (await resultTitle()).includes("rejected") && (await narration()).includes("No side effects"), await narration());
  await click("#sim-play");
  await sleep(1200);
  t = await trace();
  check("play after reject restarts the run", t.startsWith("request received") && !t.includes("reserve funds"), t);

  // --- Scenario 3: approve-fail (saga compensates) ---
  await click('[data-scenario="approve-fail"]');
  await click("#sim-play");
  await sleep(6500);
  await click("#sim-approve");
  await sleep(7000);
  t = await trace();
  check("approve-fail: notify failed", t.includes("FAILED"), t);
  check("approve-fail: compensations ran in reverse", t.indexOf("reverse ledger entry") > -1 && t.indexOf("release reservation") > t.indexOf("reverse ledger entry"), t);
  check("approve-fail: result undone", (await resultTitle()).includes("undone"), await resultTitle());
  await cdp.shot(path.join(SHOTS, "09-sim-compensated.png"));
  await cdp.eval(`document.getElementById("sim-node-result").scrollIntoView({block: "center"})`);
  await sleep(500);
  await cdp.shot(path.join(SHOTS, "13-sim-saga.png"));

  // --- Step-through control ---
  await click("#sim-reset");
  await click("#sim-step");
  await sleep(300);
  const stepped = await cdp.eval(`document.querySelectorAll("#sim-trace-list li").length`);
  check("step button advances one step", stepped === 1, `rows=${stepped}`);
  await click("#sim-reset");
  const resetOk = await cdp.eval(`document.querySelector("#sim-trace-list .t-empty") !== null && !document.getElementById("sim-approve").disabled === false`);
  check("reset clears the run", resetOk);

  // --- Moments mounted ---
  const moments = await cdp.eval(`document.documentElement.getAttribute("data-moments-ready")`);
  check("moments mounted", moments !== null, `ready=${moments}`);

  // --- Layers section screenshot ---
  await cdp.eval(`document.getElementById("layers").scrollIntoView()`);
  await sleep(2500);
  await cdp.shot(path.join(SHOTS, "10-layers.png"));

  // --- Hero + full page screenshots ---
  await cdp.eval(`scrollTo({top: 0, behavior: "instant"})`);
  await sleep(800);
  await cdp.shot(path.join(SHOTS, "00-hero.png"));

  // --- Screencast video of the approve scenario ---
  if (!shotsOnly) {
    const framesDir = path.join(DEMO, "frames");
    await rm(framesDir, { recursive: true, force: true });
    await mkdir(framesDir, { recursive: true });
    await click('[data-scenario="approve"]');
    await cdp.eval(`document.getElementById("sim").scrollIntoView()`);
    await sleep(500);
    let frameNo = 0;
    const onFrame = (d) => {
      if (d.method === "Page.screencastFrame") {
        const p = path.join(framesDir, `f${String(frameNo++).padStart(4, "0")}.jpg`);
        writeFile(p, Buffer.from(d.params.data, "base64")).catch(() => {});
        cdp.send("Page.screencastFrameAck", { sessionId: d.params.sessionId }).catch(() => {});
      }
    };
    cdp.ws.addEventListener("message", (m) => { try { onFrame(JSON.parse(m.data)); } catch {} });
    const vidStart = Date.now();
    await cdp.send("Page.startScreencast", { format: "jpeg", quality: 70, everyNthFrame: 1 });
    await click("#sim-play");
    await sleep(6500);
    await click("#sim-approve");
    await sleep(4500);
    await cdp.send("Page.stopScreencast");
    const vidSeconds = (Date.now() - vidStart) / 1000;
    await sleep(800);
    console.log(`screencast frames: ${frameNo} over ${vidSeconds.toFixed(1)}s`);
    if (frameNo > 10) {
      const fps = Math.max(4, Math.round(frameNo / vidSeconds));
      await new Promise((res, rej) => {
        const ff = execFile("ffmpeg", ["-y", "-framerate", String(fps), "-i", path.join(framesDir, "f%04d.jpg"), "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-b:v", "1200k", path.join(DEMO, "architecture-sim.webm")], (e) => (e ? rej(e) : res()));
        ff.stderr.on("data", () => {});
      });
      console.log(`video written: docs/demo/architecture-sim.webm (${fps} fps, real time)`);
    }
    await rm(framesDir, { recursive: true, force: true });
  }

  // --- 390px phone shot ---
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await cdp.eval(`document.getElementById("sim").scrollIntoView()`);
  await sleep(800);
  await cdp.shot(path.join(SHOTS, "11-sim-phone.png"));
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  chrome.kill();
  server.close();
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
