const readStdin = async () => {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
};

const writeJson = (obj) => {
  process.stdout.write(JSON.stringify(obj));
};

const loadInput = async () => {
  const argvPayload = process.argv[2];
  const raw = argvPayload && argvPayload.trim() !== "" ? argvPayload : await readStdin();
  if (!raw || raw.trim() === "") {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch {
    return { _err: "invalid input json" };
  }
};

const payload = await loadInput();
if (payload._err) {
  writeJson({ err: true, st: 400, msg: payload._err });
  process.exit(0);
}

const url = String(payload.url ?? "").trim();
if (url === "") {
  writeJson({ err: true, st: 400, msg: "http.get requires non-empty url" });
  process.exit(0);
}

const timeoutNum = Number(payload.t ?? 8);
if (!Number.isFinite(timeoutNum) || timeoutNum <= 0) {
  writeJson({ err: true, st: 400, msg: "timeout must be > 0" });
  process.exit(0);
}

const headers = {};
if (payload.h !== undefined && payload.h !== null) {
  if (typeof payload.h !== "object" || Array.isArray(payload.h)) {
    writeJson({ err: true, st: 400, msg: "headers must be object" });
    process.exit(0);
  }
  for (const [key, value] of Object.entries(payload.h)) {
    headers[String(key)] = String(value);
  }
}

if (headers["User-Agent"] === undefined && headers["user-agent"] === undefined) {
  headers["User-Agent"] = "nova/0.1.5-node";
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
  writeJson({ st: Number(res.status), hd, bd });
} catch (err) {
  const msg = err && err.message ? String(err.message) : String(err);
  writeJson({ err: true, st: 0, msg });
} finally {
  clearTimeout(timeoutId);
}

