# NOVA skill v0.1.6
# Token-efficient DSL IA-first para APIs y scripting
# Formato nativo: TOON columnar

## LEER PRIMERO (orden obligatorio)
```
1. agent.dictionary.toon  → sintaxis y comandos
2. .nova/idx.toon         → estado del proyecto
3. CHANGELOG.md           → cambios recientes
4. NOVA_LANGUAGE.md       → spec completa
```

## SINTAXIS CORE

```nova
# Modulo
mdl <name> v"<ver>" rst<any, err> { ... }

# Ruta
rte <METHOD> "/path" { ... }
rte <METHOD> "/path/:param" { ... }

# Metodos HTTP
GET  POST  PUT  DEL  PAT  OPT  HED

# Binding
let x = <value>

# Condicional
if x == nul { ... } els { ... }

# Match
match val { "a" => 1  _ => 0 }

# Guard (valida presencia, aborta con err si falla)
grd ctx.b, ctx.b.name : "BAD_REQUEST"

# Respuesta
rst.ok({ key: val })
err { code: "X"  msg: "..." }
```

## CONTEXTO (ctx aliases)
```
ctx.q → query params
ctx.p → path params
ctx.h → headers
ctx.b → body
```

## DB IR
```nova
tb <table>
whe <field> == <val>
ord <field> asc|desc
lim num<N>

# Ops
db.read()    db.create(ctx.b)
db.update(ctx.b)    db.delete()
```

## CAPABILITIES
```nova
cap [db, env]                          # estaticas
cap http.get(url, h?, t?)             # → {st, hd, bd}
cap html.tte(html)                    # → str titulo
cap html.sct(html, css)              # → lista matches
```

## LITERALES
```
"texto"      → string (sin prefijo)
num10        → numero
tru fal nul  → bool/null
```

## FORMATO TOON (nativo)
```toon
@toon v1
@type array
|id|title|status|
|1|"item one"|"new"|
|2|"item two"|"done"|
```
```toon
@toon v1
@type std
|k|v|
|"key"|"value"|
```
- Nested → indentación, sin llaves
- Campos opcionales/irregulares → al final del bloque
- ~61% menos tokens vs JSON equivalente

## CLI COMMANDS
```
nova run <file.nv>
nova build <file.nv> --b llvm|interp|go
nova serve <file.nv> --cap net --port <N>
nova agt init --root .     # crea idx.toon, agent.dictionary.toon, NOVA_LANGUAGE.md
nova agt sync --root .     # actualiza index tras cambios
nova agt check             # valida contexto y reporta estado
nova agt pack              # empaqueta contexto para respuesta
nova --version
```

## NET DRIVERS
```
NOVA_NET_DRIVER=py       # default, requests
NOVA_NET_DRIVER=node     # worker keepalive JSONL (Node 18+)
NOVA_NET_DRIVER=browser  # Playwright Chromium headless
```

## BACKENDS
```
interp  → Python, desarrollo
llvm    → AOT Rust/axum, producción, runtime HTTP nativo
go      → stub pluggable
```

## EJEMPLO MÍNIMO (CRUD JSON)
```nova
mdl users v"0.1.6" rst<any, err> {
  rte POST "/users" {
    grd ctx.b, ctx.b.name : "BAD_REQUEST"
    tb users
    rst.ok(db.create(ctx.b))
  }

  rte GET "/users" {
    tb users
    whe active == tru
    ord id asc
    lim num20
    rst.ok(db.read())
  }

  rte DEL "/users/:id" {
    tb users
    whe id == ctx.p.id
    rst.ok(db.delete())
  }
}
```

## ERRORES RUNTIME (formato TOON)
```toon
@toon v1
@type error
|k|v|
|"code"|"PARSE_ERROR"|
|"msg"|"detalle del error"|
```

## NOTAS PARA EL AGENTE
- Archivos fuente: `.nv`
- Contexto del proyecto: `.nova/idx.toon`
- Diccionario: `agent.dictionary.toon`
- Nunca usar keywords como identificadores
- `ctx` y `db` son namespaces reservados, no declarar como variables
- Siempre terminar cada `rte` con `rst.ok(...)` o `err {...}`
- Tras cualquier cambio al proyecto: ejecutar `nova agt sync`