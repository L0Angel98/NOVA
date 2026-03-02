# Roadmap v0.2

Objetivo: consolidar robustez de plataforma y cerrar huecos de especificacion sin romper compatibilidad v0.1.

## 1) Lenguaje y especificacion

- Cerrar gramatica formal (precedencia completa, asociatividad, errores sintacticos canónicos).
- Definir contrato de retorno/flow control (incluyendo semantica formal de finalizacion de bloque).
- Estandarizar esquema de `rst` en runtime y checker.

## 2) Type checker

- Cobertura de `ctx`, `query`, `headers`, `body`, `params` con tipos base estables.
- Mejor diagnostico de rutas y builtins runtime.
- Exhaustividad de `match` mas precisa para mas tipos, manteniendo heuristicas deterministas.

## 3) Runtime

- Modo de observabilidad basico (latencia por ruta, contador de errores).
- Hardening de errores HTTP (catálogo final, payload uniforme por formato).
- Refinamiento de semantica `asy/awt` (sin introducir runtime distribuido).

## 4) TOON

- Reglas canónicas adicionales para celdas complejas y escapes edge-case.
- Set de fixtures de compatibilidad TOON <-> JSON para regression testing.

## 5) Agent Context

- Política formal de versionado de `agent.toon`.
- Validaciones mas estrictas de drift por secciones (no solo snapshot global).
- Plantillas de pack para perfiles (dev/review/release) sin embeddings/vector DB.

## 6) DX

- Guías de migracion v0.1 -> v0.2.
- CLI help expandido con ejemplos por subcomando.
- Matriz de compatibilidad (OS/Python) en CI.

## Fuera de alcance v0.2

- Embeddings
- Vector DB
- SQL raw
- Joins en DB declarativa
- Auth real
- Permisos dinámicos

