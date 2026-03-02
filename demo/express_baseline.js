const express = require("express");
const app = express();
app.use(express.json());

const ERROR_STATUS = {
  BAD_REQUEST: 400,
  ROUTE_NOT_FOUND: 404,
  METHOD_NOT_ALLOWED: 405,
  CAP_DECLARATION_REQUIRED: 403,
  CAP_FORBIDDEN: 403,
  INTERNAL_ERROR: 500,
};

const RUNTIME_CAPS = new Set(["db"]);

const state = {
  items: [],
  nextId: 1,
  reqCounter: 0,
};

function makeReqId() {
  state.reqCounter += 1;
  return `req-${String(state.reqCounter).padStart(6, "0")}`;
}

function fail(res, code, msg, details = undefined) {
  const status = ERROR_STATUS[code] || 500;
  const out = { ok: false, error: { code, msg } };
  if (details !== undefined) out.error.details = details;
  return res.status(status).json(out);
}

function ok(res, data) {
  return res.status(200).json({ ok: true, data });
}

function requireCap(routeCaps, cap, op) {
  if (!routeCaps.has(cap)) {
    const err = new Error(`${op} requires declared cap '${cap}'`);
    err.code = "CAP_DECLARATION_REQUIRED";
    throw err;
  }
  if (!RUNTIME_CAPS.has(cap)) {
    const err = new Error(`${op} blocked: runtime missing cap '${cap}'`);
    err.code = "CAP_FORBIDDEN";
    throw err;
  }
}

function parseLimit(v, fallback) {
  if (v === undefined || v === null || v === "") return fallback;
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) {
    const err = new Error("lim must be >= 0");
    err.code = "BAD_REQUEST";
    throw err;
  }
  return Math.floor(n);
}

function runQuery({ where, limit, orderField, orderDirection }) {
  let rows = [...state.items];
  if (where) rows = rows.filter(where);
  if (orderField) {
    rows.sort((a, b) => {
      if (a[orderField] === b[orderField]) return 0;
      const cmp = a[orderField] < b[orderField] ? -1 : 1;
      return orderDirection === "desc" ? -cmp : cmp;
    });
  }
  if (typeof limit === "number") rows = rows.slice(0, limit);
  return rows;
}

function route(handler) {
  return (req, res) => {
    try {
      const ctx = {
        request_id: makeReqId(),
        method: req.method,
        path: req.path,
        timestamp_ms: Date.now(),
      };
      return handler(req, res, ctx);
    } catch (e) {
      return fail(res, e.code || "INTERNAL_ERROR", e.message || "unexpected runtime failure");
    }
  };
}

app.get(
  "/ping",
  route((req, res, ctx) => {
    return ok(res, {
      service: "nova-demo",
      version: "0.1.0",
      request_id: ctx.request_id,
      method: ctx.method,
    });
  })
);

app.get(
  "/items",
  route((req, res, ctx) => {
    const caps = new Set(["db"]);
    requireCap(caps, "db", "db.read");

    const lim = parseLimit(req.query.n, 50);
    const rows = runQuery({ where: null, limit: lim, orderField: "id", orderDirection: "asc" });

    return ok(res, {
      items: rows,
      query: req.query,
      headers: req.headers,
      ctx,
    });
  })
);

app.post(
  "/items",
  route((req, res) => {
    const caps = new Set(["db"]);
    requireCap(caps, "db", "db.create");

    if (!req.body) return fail(res, "BAD_REQUEST", "body is required");
    if (req.body.name == null) return fail(res, "BAD_REQUEST", "name is required");

    const row = { ...req.body, id: state.nextId++ };
    state.items.push(row);
    return ok(res, row);
  })
);

app.put(
  "/items/:id",
  route((req, res) => {
    const caps = new Set(["db"]);
    requireCap(caps, "db", "db.update");

    const id = Number(req.params.id);
    let count = 0;
    const updated = [];
    state.items = state.items.map((row) => {
      if (row.id !== id) return row;
      count += 1;
      const next = { ...row, ...(req.body || {}) };
      updated.push(next);
      return next;
    });

    return ok(res, { updated, count });
  })
);

app.delete(
  "/items/:id",
  route((req, res) => {
    const caps = new Set(["db"]);
    requireCap(caps, "db", "db.delete");

    const id = Number(req.params.id);
    const before = state.items.length;
    state.items = state.items.filter((row) => row.id !== id);
    return ok(res, { deleted: before - state.items.length });
  })
);

// Equivalent TOON endpoints still need separate text/toon encoder/decoder wiring.
app.get(
  "/items.toon",
  route((req, res) => {
    const caps = new Set(["db"]);
    requireCap(caps, "db", "db.read");
    const rows = runQuery({ where: null, limit: null, orderField: "id", orderDirection: "asc" });
    return ok(res, rows);
  })
);

app.post(
  "/items.toon",
  route((req, res) => {
    const caps = new Set(["db"]);
    requireCap(caps, "db", "db.create");
    if (!req.body) return fail(res, "BAD_REQUEST", "body is required");
    if (req.body.name == null) return fail(res, "BAD_REQUEST", "name is required");
    const row = { ...req.body, id: state.nextId++ };
    state.items.push(row);
    return ok(res, row);
  })
);

app.use((req, res) => fail(res, "ROUTE_NOT_FOUND", "route not found"));

app.listen(8080, () => {
  console.log("Express baseline listening on :8080");
});
