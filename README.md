# Modelador 3FN

Modelador relacional que convierte requisitos escritos en tablas, un diccionario
de datos y DDL para PostgreSQL. Compara un flujo con agentes especializados
con otro de un solo agente. El núcleo de Python comprueba tercera forma normal
(3FN) respecto de las dependencias funcionales que recibe.

## Instalación

Requiere Python 3.10 o superior. Desde la raíz del repositorio:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
modelador --help
```

Para generar diseños, [Ollama](https://ollama.com/download) debe estar iniciado
y tener un modelo local. El modelo predeterminado se descarga con
`ollama pull qwen3:4b`. Usa `--model` antes del subcomando o configura
`OLLAMA_MODEL` para cambiarlo. Puedes indicar otra instancia con
`OLLAMA_URL` o `--ollama-url`.

La validación del DDL requiere `psql` y acceso a una base de pruebas. El
usuario de la base necesita permiso `CREATE`. La comprobación crea un esquema
dentro de una transacción y ejecuta `ROLLBACK`. Si no configuras PostgreSQL, el
programa sigue generando y auditando el diseño e informa si pudo ejecutar el
DDL. Puedes usar `--postgres-dsn` o las variables de conexión que lee `psql`.

## Uso

Ejecuta estos comandos desde la raíz. Sustituye `modelador_lab` por el nombre
de tu base de pruebas.

```bash
modelador design examples/requirements.txt --mode multi --postgres-dsn modelador_lab
modelador design examples/requirements.txt --mode single
modelador benchmark experiments/cases/reference.json --postgres-dsn modelador_lab
PGDATABASE=modelador_lab modelador serve
```

La interfaz web escucha en `http://127.0.0.1:8765`. También puedes usar
`python -m modelador` en lugar de `modelador`. El CLI y la web muestran el
progreso de las etapas. Cada consulta a Ollama tiene un plazo de 240 segundos,
configurable con `--timeout` después del subcomando. Al cancelar con `Ctrl+C`
durante el diseño por CLI, el JSON registra la cancelación y las etapas ya
completadas.

Los resultados locales aparecen en `runs/`. Cada benchmark crea una
subcarpeta para los JSON y el resumen CSV. La ruta se muestra al terminar.
El benchmark compara dependencias y esquemas con el caso de referencia, y
registra por separado la ejecución del DDL y cualquier recuperación del
codificador.

## Código y evidencia

| Ruta | Contenido |
|---|---|
| [`src/modelador/`](src/modelador/) | Núcleo 3FN, orquestación, agentes, DDL, CLI, web y adaptadores |
| [`tests/`](tests/) | Pruebas de normalización, flujos, reintentos, streaming y benchmark |
| [`examples/`](examples/) | Entrada de ejemplo para el CLI |
| [`experiments/`](experiments/) | Casos de referencia, plantilla de TOAD y resumen de la corrida piloto |
| [`docs/architecture/`](docs/architecture/README.md) | Diagrama y decisión de arquitectura |
| [`docs/article/`](docs/article/) | [Avance IEEE en PDF](docs/article/avance.pdf) y [proyecto LaTeX](docs/article/avance_latex.zip) |
| [`docs/research/`](docs/research/) | Revisión, exportaciones de Scopus y plantilla original |

El [CSV piloto](experiments/results/pilot/summary.csv) proviene de la corrida
`run_20261123T022054_082730Z_85c0f7ca`. Los tres casos son sintéticos. La
[planilla de TOAD](experiments/templates/manual_toad.csv) se reserva para las
mediciones de diseño manual. Si conservas las corridas de la estructura
anterior, sus rutas pasan de `prototype/runs/` a `runs/` sin cambiar los
identificadores de las ejecuciones.

## Pruebas y compilación

Para instalar las herramientas de desarrollo y ejecutar las comprobaciones:

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest
python -m unittest discover -s tests -v
```

Las pruebas usan un modelo simulado y pueden ejecutarse sin Ollama ni una base
PostgreSQL disponible. `unittest` también funciona desde la raíz sin instalar
el paquete. El extra `web` prepara las dependencias de las fases posteriores:
`python -m pip install -e '.[web,dev]'`. El archivo `requirements.txt` se
genera a partir de ese extra con `pip-compile --extra web --strip-extras
--output-file requirements.txt pyproject.toml`; fue resuelto en Linux con
Python 3.14 y debe regenerarse y comprobarse para el Python del contenedor.
Las variables de `.env.example` son ejemplos para fases posteriores; todavía
no habilitan el proveedor OpenAI ni el despliegue.

Para compilar el artículo con LaTeX y `latexmk`:

```bash
cd docs/article
latexmk -pdf -outdir=build avance.tex
```
