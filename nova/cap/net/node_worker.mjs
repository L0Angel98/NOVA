import { createInterface } from "node:readline";

const write = (obj) => {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
};

const normalizeHeaders = (value) => {
  if (value === undefined || value === null) {
    return {};
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    throw new Error("headers must be object");
  }
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    out[String(key)] = String(item);
  }
  if (out["User-Agent"] === undefined && out["user-agent"] === undefined) {
    out["User-Agent"] = "nova/0.1.5.1-node-worker";
  }
  return out;
};

const handleRequest = async (request) => {
  const id = Number.isInteger(request?.id) ? request.id : null;
  if (!request || request.op !== "get") {
    write({ id, ok: false, st: 400, msg: "unsupported op" });
    return;
  }

  const url = String(request.u ?? "").trim();
  if (url === "") {
    write({ id, ok: false, st: 400, msg: "http.get requires non-empty url" });
    return;
  }

  const timeoutNum = Number(request.t ?? 8);
  if (!Number.isFinite(timeoutNum) || timeoutNum <= 0) {
    write({ id, ok: false, st: 400, msg: "timeout must be > 0" });
    return;
  }

  let headers = {};
  try {
    headers = normalizeHeaders(request.h);
  } catch (err) {
    const msg = err && err.message ? String(err.message) : String(err);
    write({ id, ok: false, st: 400, msg });
    return;
  }

  const controller = new AbortController();
  const timeoutMs = Math.round(timeoutNum * 1000);
  const timeoutId = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const res = await fetch(url, {
      method: "GET",
      headers,
      signal: controller.signal,
      redirect: "follow",
    });
    const hd = {};
    for (const [key, value] of res.headers.entries()) {
      hd[key] = value;
    }
    const bd = await res.text();
    write({ id, ok: true, st: Number(res.status), hd, bd });
  } catch (err) {
    const msg = err && err.message ? String(err.message) : String(err);
    write({ id, ok: false, st: 0, msg });
  } finally {
    clearTimeout(timeoutId);
  }
};

const rl = createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
  terminal: false,
});

let chain = Promise.resolve();
rl.on("line", (line) => {
  chain = chain
    .then(async () => {
      const text = String(line ?? "").trim();
      if (text === "") {
        return;
      }
      let request;
      try {
        request = JSON.parse(text);
      } catch {
        write({ id: null, ok: false, st: 400, msg: "invalid json" });
        return;
      }
      await handleRequest(request);
    })
    .catch(() => {});
});

process.stdin.on("end", () => {
  process.exit(0);
});

