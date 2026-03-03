# NOVA v0.1.6

NOVA es un DSL IA-first para APIs y scripting con IR estable y backends pluggable.

## Para agentes IA
Onboarding: lee contexto en este orden antes de analizar o modificar código.
1. `nova_skill.md`: sintaxis core, flujo operativo y comandos del proyecto.
2. `agent.dictionary.toon`: diccionario actual de keywords, contratos y ejemplos.
3. `.nova/idx.toon`: estado del repo (rutas, caps, mapa de archivos, cambios, hashes).
4. `CHANGELOG.md`: cambios recientes y alcance real por versión.
Inicializar contexto (si falta o es nuevo): `nova agt init --root .`
Verificar estado del contexto: `nova agt check`
TOON es el formato nativo de contexto (columnar/determinista), ~61% menos tokens que JSON.

## Instalacion

```bash
pip install -e .
nova --version
```

Instalacion sin clonar repositorio:

```bash
pip install "nova-lang @ git+https://github.com/L0Angel98/NOVA.git@v0.1.6"
nova --version
```

## v0.1.6

### Backends

- `interp`: runtime Python para desarrollo.
- `llvm`: AOT con runtime HTTP nativo en binario (`axum` + caps nativas).
- `go`: stub pluggable.

### Net drivers

- `py` (default): `requests`
- `node`: worker keepalive JSONL (Node.js 18+)
- `browser`: Playwright Chromium headless con keepalive

Selector por entorno:

```bash
export NOVA_NET_DRIVER=py
nova serve demo/llvm_serve_profile.nv --cap net
```

```bash
export NOVA_NET_DRIVER=node
nova serve demo/llvm_serve_profile.nv --cap net
```

```bash
export NOVA_NET_DRIVER=browser
nova serve demo/llvm_serve_profile.nv --cap net
```

PowerShell:

```powershell
$env:NOVA_NET_DRIVER="browser"
nova serve demo/llvm_serve_profile.nv --cap net
```

Requisito browser driver (una vez):

```bash
python -m playwright install chromium
```

Contrato de `http.get` (sin cambios):

- `http.get(url, h?, t?) -> {st, hd, bd}`

### Agent Context Index

```bash
nova agt init --root .
nova agt sync --root .
```

Nota para agente: `agt init` crea `.nova/idx.toon`, `agent.dictionary.toon` y `NOVA_LANGUAGE.md`; flujo recomendado: leer esos archivos, ejecutar `agt sync` tras cambios y usar `agt pack` antes de responder solo si no tienes suficiente contexto del proyecto.

## Demos

```bash
nova build demo/llvm_serve_profile.nv --b llvm
./out/llvm_serve_profile --cap net --port 3000
curl http://127.0.0.1:3000/profile
```

```bash
nova build demo/llvm_db.nv --b llvm
./out/llvm_db --cap db --port 3001
curl http://127.0.0.1:3001/db
```

## Testing

```bash
python -m unittest discover -s tests -v
cd compiler/llvm && cargo test
```
