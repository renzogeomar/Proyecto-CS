# Modelador 3FN

Prototipo de modelado relacional que convierte requisitos escritos en dependencias
funcionales, tablas, un diccionario de datos y DDL para PostgreSQL.

## Inicio

Desde la raíz, con Python 3.10 o superior:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
modelador --help
python -m unittest discover -s tests -v
```

Para generar diseños, inicia Ollama con `qwen3:4b` descargado. Para validar el
DDL, indica una base de pruebas PostgreSQL accesible con `psql`.

```bash
modelador design examples/requirements.txt
modelador benchmark experiments/cases/reference.json --postgres-dsn modelador_lab
modelador serve
```

La interfaz web escucha por defecto en `http://127.0.0.1:8765`. También se
puede usar `python -m modelador`. Los archivos generados se guardan en
`runs/`. El [avance IEEE](docs/article/avance.pdf) y el
[resumen piloto](experiments/results/pilot/summary.csv) están versionados.
