# NOVA Language Specification v0.1

Estado: Borrador normativo (v0.1)
Alcance: DSL para APIs y scripting, optimizado para IA-first.
No-alcance: compilador, runtime, VM, transporte HTTP real, motor DB real.

## 1. Filosofia IA-first

NOVA v0.1 prioriza:

- Menos tokens por intencion.
- Menos ambiguedad sintactica.
- Keywords canonicas, cortas y estables.
- Flujo declarativo para API + DB.
- Salida estructurada en `json` y `toon`.
- Contexto persistente de proyecto en `agent.toon`.

Reglas IA-first:

- No se permiten sinonimos de keywords canonicas.
- Una keyword tiene un solo rol semantico.
- Se evita sobrecarga de sintaxis (menos magia, mas explicitud).
- Cuando una regla no exista en v0.1, debe declararse como duda abierta.

## 2. Keywords canonicas (abreviadas)

Reservadas en v0.1 (case-sensitive):

- `let`
- `if`
- `els`
- `match`
- `asy`
- `awt`
- `rte`
- `json`
- `toon`
- `tb`
- `whe`
- `lim`
- `ord`
- `rst`
- `err`
- `cap`
- `str`
- `num`
- `tru`
- `fal`
- `nul`

Notas:

- `rst` se escribe en minusculas.
- El resto de keywords se escriben en minusculas.
- Ninguna keyword puede usarse como identificador.

## 3. Literales (`str`/`num`/`tru`/`fal`/`nul`)

### 3.1 `str`

- Cadena entre comillas dobles.
- Ejemplo: `"hola"`.

### 3.2 `num`

- Entero o decimal en base 10.
- Ejemplos: `7`, `3.14`, `-2`.

### 3.3 Booleanos

- `tru` para verdadero.
- `fal` para falso.

### 3.4 Nulo

- `nul` representa ausencia de valor.

## 4. `let` inmutable

`let` declara binding inmutable:

```nova
let nombre = "NOVA"
let max_items = 100
```

Reglas:

- Un `let` no puede reasignarse.
- La mutacion directa de `let` no existe en v0.1.
- Si hay error de redeclaracion en mismo alcance, se reporta como `err`.

Duda abierta v0.1:

- Sombreado (shadowing) entre alcances no esta definido de forma cerrada.

## 5. `if` / `els`

Forma canonica:

```nova
if <condicion> {
  <bloque>
} els {
  <bloque>
}
```

Reglas:

- `els` es opcional.
- La condicion debe evaluar a `tru` o `fal`.
- Encadenamiento se expresa con `els if`.

## 6. `match`

Forma canonica:

```nova
match <expresion> {
  <patron> => <resultado>
  _ => <resultado_default>
}
```

Patrones minimos normativos v0.1:

- Literales (`str`, `num`, `tru`, `fal`, `nul`).
- `_` como comodin.

Reglas:

- Se evalua de arriba hacia abajo.
- Se toma la primera rama que coincide.
- Si no hay coincidencia y no existe `_`, retorna `err` de no coincidencia.

Duda abierta v0.1:

- Patrones estructurales (objetos/tablas) no estan definidos.

## 7. `asy` / `awt`

### 7.1 `asy`

Define bloque asincrono:

```nova
let tarea = asy {
  <bloque>
}
```

### 7.2 `awt`

Espera resultado asincrono:

```nova
let salida = awt tarea
```

Reglas:

- `awt` solo aplica sobre resultado de `asy`.
- Errores internos de `asy` propagan como `err`.

Dudas abiertas v0.1:

- Modelo formal de scheduler/event-loop no definido.
- Politica de cancelacion/timeouts no definida.

## 8. DB declarativa (`tb`, `whe`, `lim`, `ord`)

v0.1 define un bloque declarativo de consulta/operacion sobre tabla:

```nova
tb users
whe id == 1
ord created_at desc
lim 10
```

Semantica minima:

- `tb <identificador>`: tabla objetivo.
- `whe <condicion>`: filtro.
- `ord <campo> <dir>`: orden (`asc` o `desc`).
- `lim <num>`: limite de filas.

Reglas:

- `tb` es obligatorio en operaciones DB.
- `whe`, `ord`, `lim` son opcionales.
- `lim` debe ser `num` entero positivo.

CRUD en v0.1:

- Convencion provisional v0.1: la accion CRUD se expresa en el payload (`op`) del bloque de formato (`json` o `toon`) para evitar introducir keywords no especificadas.
- Valores permitidos para `op` en esta convencion: `"create"`, `"read"`, `"update"`, `"delete"`.

Dudas abiertas v0.1:

- No se define SQL exacto generado.
- No se define transaccionalidad.
- No se define validacion de esquema fisico.

## 9. Routes (`rte`)

Forma canonica:

```nova
rte "/path" "METHOD" <formato> {
  <bloque>
}
```

Donde:

- Convencion provisional v0.1: `"METHOD"` es `"GET"`, `"POST"`, `"PUT"`, `"PATCH"` o `"DELETE"`.
- `<formato>` es `json` o `toon`.

Reglas:

- Cada `rte` define una unidad declarativa de endpoint.
- `cap` puede declararse dentro del `rte` para control de capacidades.
- Una `rte` retorna `rst`.

Duda abierta v0.1:

- Resolucion de conflictos entre rutas superpuestas no definida.

## 10. Formats (`json`, `toon`)

## 10.1 `json`

Bloque estructurado estilo objeto:

```nova
json {
  op: "read"
  data: { id: 1, name: "Ada" }
}
```

## 10.2 `toon`

Formato tabular orientado a lectura por IA/humano.

Forma minima v0.1:

```nova
toon users {
| id | name | active |
| 1  | "Ada" | tru |
}
```

Reglas TOON:

- Primera fila: cabecera.
- Filas siguientes: registros.
- Numero de celdas por fila debe coincidir con cabecera.

Dudas abiertas v0.1:

- Escape avanzado de celdas TOON no definido.
- Tipado implicito de celdas TOON no definido en detalle.

## 11. Errors (`rst`, `err`)

`rst` encapsula salida exitosa o error.

Contrato minimo:

- Exito: variante `ok` con valor `json` o `toon`.
- Falla: `err` con `code` y `msg`.

Forma de error:

```nova
err {
  code: "NOT_FOUND"
  msg: "user not found"
}
```

Reglas:

- Toda `rte` finaliza en `rst`.
- Cualquier fallo de parseo/validacion/capacidad retorna `err`.

Duda abierta v0.1:

- Forma canonica exacta de serializacion de `rst` no cerrada.

## 12. Capabilities (`cap`)

`cap` declara permisos requeridos para ejecutar un bloque/ruta.

Forma canonica:

```nova
cap ["users.read", "users.write"]
```

Reglas:

- Si falta una capacidad requerida, el resultado es `err` de autorizacion.
- `cap` aplica antes de DB/side-effects.

Duda abierta v0.1:

- Modelo de herencia/composicion de capacidades no definido.

## 13. Agent context (`agent.toon`)

`agent.toon` es memoria de proyecto y contexto operativo para IA.

Objetivo:

- Mantener decisiones de arquitectura del DSL.
- Guardar convenciones de rutas, formatos y capacidades.
- Registrar dudas abiertas y acuerdos de equipo.

Reglas minimas:

- Debe existir en la raiz del proyecto.
- Debe usar formato `toon` tabular.
- Debe ser legible por humano e IA con bajo costo de tokens.

## 14. Dudas abiertas v0.1 (sin inventar)

Los siguientes puntos quedan explicitamente fuera por falta de definicion en el requerimiento:

- Gramatica formal completa (precedencia de operadores y asociatividad).
- Sistema de tipos mas alla de literales basicos.
- Parametros de ruta (`/users/:id`) y binding formal.
- Esquema formal de entrada/salida por metodo HTTP.
- Manejo de transacciones y aislamiento DB.
- Versionado de API y estrategia de migraciones.
- Modelo exacto de concurrencia para `asy`.
- Interoperabilidad binaria o FFI.

Mientras estos puntos no se definan, NOVA v0.1 debe tratarse como especificacion funcional minima, no como definicion cerrada de implementacion.

