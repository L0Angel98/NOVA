# INSTALL (Windows, PowerShell)

## Requisitos

- Python >= 3.10
- `pip` actualizado en el mismo Python que usas para instalar

## 1) Diagnostico rapido de entorno

Ejecuta:

```powershell
pip config list
pip config debug
where python
where pip
```

Que revisar en la salida:

- `pip config list`: busca claves conflictivas en `[global]` como `home = ...`, `prefix = ...` o `target = ...`.
- `pip config debug`: identifica **el archivo activo** (`pip.ini`/`pip.cfg`) que realmente esta aplicando la config.
- `where python` y `where pip`: confirma que ambos apuntan a la misma instalacion/venv.

Nota: en algunas consolas `where` puede no mostrar rutas; alternativa equivalente:

```powershell
Get-Command python,pip | Select-Object Name,Source
```

## 2) Reparar pip.ini / pip.cfg

Abre el archivo activo detectado por `pip config debug` (por ejemplo `C:\Users\USER\AppData\Roaming\pip\pip.ini`) y en `[global]` elimina o comenta `home` y `prefix` (y si existe, tambien `target`).

Ejemplo ANTES:

```ini
[global]
home = E:\PythonLibs
prefix = E:\PythonLibs
target = E:\PythonLibs
cache-dir = E:\PythonCache
```

Ejemplo DESPUES (correcto):

```ini
[global]
cache-dir = E:\PythonCache
```

Tambien es valido comentar:

```ini
[global]
# home = E:\PythonLibs
# prefix = E:\PythonLibs
# target = E:\PythonLibs
cache-dir = E:\PythonCache
```

Si el archivo queda vacio, puedes borrarlo.

## 3) Instalacion limpia

### Variante A — Global (sin venv)

```powershell
pip uninstall nova-lang -y
pip install -e .
nova --help
```

### Variante B — Con venv (recomendada para desarrollo)

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
nova --help
```

## 4) Verificacion esperada

Comando:

```powershell
nova --help
```

Salida esperada (inicio):

```text
usage: nova [-h] {parse,fmt,check,serve,agt} ...
```

## 5) Troubleshooting

### Error: `Cannot set --home and --prefix together`

Causa:

- Config global de `pip` con `home`/`prefix` y/o `target` en conflicto con build-isolation.

Solucion:

1. Ejecuta `pip config debug`.
2. Abre el archivo marcado como `exists: True`.
3. Elimina/comenta `home =`, `prefix =` y `target =` (si existe).
4. Reintenta `pip install -e .`.

### Error: `importlib.metadata.PackageNotFoundError: No package metadata was found for nova-lang`

Causa tipica:

- Metadata inconsistente por mezclar backend legacy y/o coexistencia conflictiva de configuraciones de packaging.

Solucion aplicada en este proyecto:

- `pyproject.toml` con backend moderno `setuptools.build_meta`.
- Script de consola definido en `[project.scripts]`.
- Fuente unica de metadata (sin `setup.py` legacy en paralelo).

Reinstalacion recomendada:

```powershell
pip uninstall nova-lang -y
pip install -e .
nova --help
```

## 6) Verificacion post-instalacion

```powershell
nova --help
nova parse demo\app.nv
nova fmt demo\app.nv
nova check demo\app.nv
nova agt chk --root .
```

Si sigue fallando, comparte el output completo del error para continuar el diagnostico.
