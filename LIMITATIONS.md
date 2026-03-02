# Limitaciones conocidas (v0.1)

## Lenguaje

- Gramatica formal no cerrada al 100%.
- Sistema de tipos deliberadamente simple.
- No hay inferencia compleja.

## Checker

- No modela completamente todos los builtins runtime.
- Exhaustividad de `match` parcial fuera de casos base.
- Algunas validaciones operan por heuristica determinista (tradeoff DX vs complejidad).

## Runtime

- Sin auth real.
- `cap` usa allowlist estatica al arranque; sin permisos dinamicos ni overrides.
- `asy/awt` no implementa scheduler/event-loop completo.
- In-memory DB only (sin persistencia).

## DB IR

- Sin SQL raw.
- Sin joins.
- Sin optimizaciones de plan.

## TOON

- Sin transporte binario.
- Cobertura de escapes/casos edge en evolucion.

## Agent Context

- Sin embeddings.
- Sin vector DB.
- Snapshot basado en archivos/AST local (no conocimiento semantico profundo).
