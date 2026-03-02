# NOVA Language Specification v0.1.2

Estado: contrato normativo minimo para v0.1.
Alcance: DSL IA-first para APIs y scripting.
No alcance: detalles internos de runtime, transporte HTTP real y motor DB fisico.

## Overview / Goals

NOVA v0.1.2 define una superficie estable para codigo orientado a IA:

- Menos tokens por intencion.
- Menos ambiguedad sintactica.
- Keywords canonicas y cortas.
- Flujo declarativo para rutas y DB IR.
- Salida consistente mediante `rst` y `err`.

## Versioning (v0.1.2 notes)

- `v0.1.0`: base de lenguaje (`rte`, `tb/whe/lim/ord`, `cap`, `rst/err`).
- `v0.1.1`: `str"..."` deja de ser sintaxis canonica.
- `v0.1.2`: breaking change: metodos HTTP son keywords sin comillas.

## Lexical structure

- Extensiones de fuente: `.nv`.
- Separadores de sentencia: salto de linea o `;`.
- Comentarios: `# ...`, `// ...`, `/* ... */`.
- Identificadores: case-sensitive, no pueden reutilizar keywords reservadas.

## Keywords (reserved)

Keywords reservadas en v0.1.2:

- Control: `let`, `if`, `els`, `match`, `asy`, `awt`
- Modulo/API: `mdl`, `grd`, `rte`, `cap`, `rst`, `err`
- DB IR: `tb`, `whe`, `lim`, `ord`
- Formatos/literales: `json`, `toon`, `tru`, `fal`, `nul`
- HTTP methods: `GET`, `POST`, `PUT`, `DEL`, `PAT`, `OPT`, `HED`

Reglas:

- `mdl` y `grd` son keywords reservadas.
- Ninguna keyword reservada puede usarse como identificador.

## Runtime namespaces & builtins (standard v0.1)

Elementos estandar del runtime:

- Namespaces reservados: `ctx`, `db`.
- Builtin: `to_num(value)`.

Reglas:

- `ctx` y `db` no pueden declararse como variables de usuario.
- `to_num` es parte del contrato minimo de runtime.

## HTTP routing (rte + methods)

Forma canonica v0.1.2:

```nova
rte GET "/path" {
  rst.ok({ ok: tru })
}

rte POST "/path" {
  grd ctx.b : "BAD_REQUEST"
  rst.ok({ ok: tru })
}
```

Lista explicita de metodos soportados en el estandar:

- `GET`
- `POST`
- `PUT`
- `DEL`
- `PAT`
- `OPT`
- `HED`

Reglas:

- Los metodos son keywords (no string literals).
- Cada `rte` debe terminar en un valor de respuesta (`rst` o `err`).

## Responses (rst) + Error format

`rst` encapsula respuesta de exito o error.

Exito:

```nova
rst.ok({ id: 1 })
```

Error:

```nova
err {
  code: "NOT_FOUND"
  msg: "resource not found"
}
```

Contrato minimo de `err`:

- `code: str`
- `msg: str`

## DB Query IR (tb/whe/lim/ord)

Bloques declarativos DB en v0.1:

```nova
tb users
whe active == tru
ord id asc
lim num10
```

Semantica minima:

- `tb`: tabla objetivo.
- `whe`: filtro opcional.
- `ord`: orden opcional (`asc` o `desc`).
- `lim`: limite opcional (entero positivo).

## Context aliases (standard v0.1.2)

Mapeo oficial:

- `ctx.q` => query
- `ctx.p` => params
- `ctx.h` => headers
- `ctx.b` => body

Reglas de estandar:

- Los ejemplos oficiales deben usar `ctx.q`, `ctx.p`, `ctx.h`, `ctx.b`.
- `query`, `params`, `headers`, `body` NO son keywords ni nombres reservados del lenguaje.
- Aunque implementaciones internas mantengan nombres largos, la sintaxis estandar para demos/docs usa aliases `ctx.*`.
