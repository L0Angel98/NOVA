# NOVA Language Specification v0.1.2

Status: normative standard contract (minimum v0.1).
Scope: IA-first DSL for APIs and scripting.
Non-scope: VM internals, transport implementation details, and physical DB engine semantics.

## Overview / Goals

NOVA v0.1 standardizes a compact surface for human + AI collaboration:

- Fewer tokens per intent.
- Stable canonical keywords (no synonyms in source standard).
- Declarative API + DB flow.
- Predictable response contract with `rst`/`err`.
- Low-friction context access via short aliases.

Design rules for v0.1:

- One keyword, one semantic role.
- No keyword overloading.
- If behavior is not defined here, it is out of standard scope.

## Versioning (v0.1.2 notes)

- `v0.1.0`: initial language surface (`rte`, `tb/whe/lim/ord`, `cap`, `rst/err`).
- `v0.1.1`: `str"..."` removed from canonical syntax (plain `"..."` is canonical).
- `v0.1.2`: breaking change: HTTP methods are keywords (no quoted method strings).

v0.1.2 source rule for routes:

```nova
rte "/path" GET json {
  rst.ok({ ok: tru })
}
```

## Lexical structure

### Source units

- Source file extension: `.nv`.
- Newlines and `;` can separate statements.
- Comments:
  - `# ...`
  - `// ...`
  - `/* ... */`

### Identifiers

- Pattern: letter/underscore start, then alphanumeric/underscore.
- Case-sensitive.
- Identifiers cannot reuse reserved keywords.
- Runtime namespaces `ctx` and `db` are reserved and cannot be declared as user variables.

### Literals

- `str`: `"text"`
- `num`: `7`, `-2`, `3.14`, or prefixed compact forms like `num50`
- `bool`: `tru`, `fal`
- `nul`: null literal

### Core statements (minimum v0.1)

- Immutable bind: `let`
- Branching: `if ... els ...`
- Pattern matching: `match`
- Async primitives: `asy`, `awt`
- Capability declaration: `cap`

## Keywords (reserved)

Reserved keywords in v0.1.2:

- Module/system: `mdl`, `imp`, `pub`, `fn`
- Control flow: `let`, `if`, `els`, `match`, `asy`, `awt`
- API/runtime: `rte`, `rst`, `err`, `grd`, `cap`
- DB IR: `tb`, `whe`, `lim`, `ord`
- Literals: `tru`, `fal`, `nul`
- HTTP method keywords: `GET`, `POST`, `PUT`, `DEL`, `PAT`, `OPT`, `HED`

Rules:

- Reserved keywords cannot be used as identifiers.
- `mdl` and `grd` are reserved language keywords.
- Long context names (`query`, `params`, `headers`, `body`) are not reserved keywords.

## Runtime namespaces & builtins (standard v0.1)

Standard runtime contract requires these names:

- `ctx`: request context namespace (reserved).
- `db`: database facade namespace (reserved).
- `to_num(value)`: builtin numeric conversion.

Rules:

- `ctx` and `db` must not be used as user variable names.
- `to_num` is a standard builtin available in route/module execution scope.
- Standard `ctx` metadata keys include `request_id`, `method`, `path`, and `timestamp_ms`.
- Standard `db` facade exposes `read`, `create`, `update`, `delete`, and `plan`.

## HTTP routing (rte + methods)

Canonical route form in v0.1.2:

```nova
rte "/users" GET json {
  rst.ok(db.read())
}

rte "/users" POST json {
  grd ctx.b, ctx.b.name : "BAD_REQUEST"
  rst.ok(db.create(ctx.b))
}
```

Method-first reference notation (docs shorthand):

```nova
rte GET "/path" { ... }
rte POST "/path" { ... }
```

Method list supported by the v0.1.2 standard:

- `GET`
- `POST`
- `PUT`
- `DEL`
- `PAT`
- `OPT`
- `HED`

Compatibility note:

- Implementations may accept legacy aliases (`PATCH`, `DELETE`) for backward compatibility.

Rules:

- Methods are keywords, not quoted strings.
- Route format is `json` or `toon`.
- A route must end in a response value (`rst` or `err`).

## Responses (rst) + Error format

`rst` is the response envelope contract.

Success form:

```nova
rst.ok({ id: 1 })
```

Error form:

```nova
err {
  code: "NOT_FOUND"
  msg: "user not found"
}
```

Rules:

- `err` payload minimum keys: `code`, `msg`.
- `rst`/`err` values are final route outputs.
- Runtime serialization can target `json` or `toon`, but semantic fields must remain stable.

## DB Query IR (tb/whe/lim/ord)

Declarative query IR is built from these statements:

```nova
tb users
whe active == tru
ord created_at desc
lim num10
```

Semantics:

- `tb <target>`: required DB target declaration.
- `whe <condition>`: optional filter.
- `ord <field> <asc|desc>`: optional sort.
- `lim <num>`: optional positive row limit.

Block shorthand is valid for query composition:

```nova
tb users.q {
  whe active == tru
  ord id asc
  lim num5
}
```

## Context access (aliases 1 silaba)

### Context aliases (standard)

Standard aliases (fixed mapping):

- `ctx.q` => query
- `ctx.p` => params
- `ctx.h` => headers
- `ctx.b` => body

Standard rules:

- Source code should use `ctx.q/ctx.p/ctx.h/ctx.b` in canonical examples and guides.
- Long names may exist internally in implementations, but the language standard uses aliases.
- `query`, `params`, `headers`, `body` are not reserved keywords.

## Open items out of v0.1 scope

- Full formal operator precedence spec.
- Full type system beyond v0.1 primitives and result envelope.
- Exact transaction/isolation DB semantics.
- Route conflict resolution policy for overlapping patterns.
- Scheduler/cancellation semantics for async execution.
