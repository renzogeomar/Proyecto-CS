# Modelador autónomo 3FN

Prototipo para el artículo **Modelado de Datos Autónomo: Sistemas Multi-Agente para Normalización 3NF y Generación de Esquemas**. Convierte requisitos escritos en español en dependencias funcionales, tablas en 3FN, diccionario de datos y DDL PostgreSQL. Incluye un flujo de un solo agente para comparar resultados.

## Requisitos

- Python 3.10 o superior. El prototipo usa solo la biblioteca estándar.
- [Ollama](https://ollama.com/download) funcionando localmente y un modelo descargado. Configuración sugerida: `ollama pull qwen3:4b`. El modelo puede cambiarse con `--model` o `OLLAMA_MODEL`.
- PostgreSQL y `psql` para la validación ejecutable del DDL. Si no están disponibles, el diseño y la auditoría formal funcionan; el resultado indicará que la prueba PostgreSQL no se pudo completar.

En esta máquina de trabajo, `ollama` no estaba instalado y PostgreSQL no respondía cuando se preparó el prototipo. Por eso los resultados de pruebas locales usan un modelo simulado y **no son resultados experimentales de IA**.

## Uso

Desde este directorio:

```bash
PYTHONPATH=. python3 -m modelador serve
```

Abra `http://127.0.0.1:8765`. Para usar la línea de comandos:

```bash
PYTHONPATH=. python3 -m modelador design requisitos.txt --mode multi --output runs
PYTHONPATH=. python3 -m modelador design requisitos.txt --mode single --output runs
PYTHONPATH=. python3 -m modelador benchmark cases/reference.json --output runs/benchmark
```

Cada consulta a Ollama tiene un plazo predeterminado de 240 segundos. El CLI muestra qué agente está trabajando y el tiempo transcurrido; también puede ajustarse, por ejemplo, con `design example_requirements.txt --timeout 360`. El servicio usa streaming y desactiva el modo de razonamiento (`think: false`) para el modelo local. Estas opciones quedan registradas en cada JSON. `Ctrl+C` guarda un resultado con estado `cancelled` y las etapas ya completadas. La interfaz web muestra el progreso mientras se ejecuta cada agente.

La opción `--model` debe ponerse antes del subcomando, por ejemplo `python3 -m modelador --model qwen3:4b design requisitos.txt`. `OLLAMA_URL` permite apuntar a otro servidor local. Para verificar SQL, configure las variables estándar `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` o pase `--postgres-dsn`. La validación crea un esquema temporal dentro de una transacción y ejecuta `ROLLBACK`; la cuenta PostgreSQL necesita permiso `CREATE` en la base de pruebas.

Cada ejecución guarda un JSON con requisitos, modelo, tiempo, respuestas de los agentes, auditoría y DDL. Cada benchmark crea una subcarpeta única bajo `--output` con los JSON y `summary.csv`; la ruta exacta se imprime al terminar. Los tres casos de `cases/reference.json` son **casos de referencia creados para probar el software**, no especificaciones reales ni evidencia empírica suficiente para el artículo. Agregue casos reales y revise sus dependencias esperadas antes de publicar resultados.

## Arquitectura y límites

1. El analista local extrae atributos y dependencias funcionales del texto.
2. El normalizador calcula una cobertura mínima y sintetiza tablas 3FN.
3. El auditor proyecta dependencias por tabla, calcula claves candidatas y comprueba 3FN, cobertura de atributos y preservación de dependencias.
4. Un agente documenta columnas y otro propone tipos para el DDL; el compilador genera SQL usando únicamente identificadores y tipos permitidos.
5. El flujo de referencia pide a un solo agente todo el esquema y lo somete a la misma auditoría.

La prueba de 3FN es **condicional a las dependencias funcionales declaradas**. Una dependencia semántica omitida o inventada por el modelo puede hacer que un esquema formalmente válido sea incorrecto para el negocio. El benchmark compara también las dependencias inferidas con las esperadas. Las tablas se auditan exactamente hasta 14 atributos cada una; un caso mayor debe separarse en dominios más pequeños. El sistema no ejecuta automáticamente migraciones permanentes.

Los agentes piden a Ollama respuestas estructuradas según un esquema JSON y el programa valida cada etapa. Si una respuesta copia la entrada o carece de campos, queda registrada como `rejected` con su motivo; se repite únicamente la etapa fallida hasta dos veces. Si persiste el problema, el CLI muestra el error y guarda todas las respuestas para inspección.

El diccionario exige exactamente una definición por atributo aprobado, aunque un atributo aparezca en varias tablas. Una respuesta con columnas faltantes, desconocidas o con el formato anterior se rechaza con nombres concretos; el agente puede corregirla en el siguiente intento.

Los nombres de entidades se convierten a `snake_case` sin cambiar las dependencias funcionales; la respuesta original queda en la traza. Si el agente codificador no entrega tipos válidos después de tres intentos, el programa genera el DDL con los tipos ya validados del diccionario y registra `coder_status: fallback`. El benchmark informa por separado `schema_success` y `full_agent_success` para no contar esa recuperación como acierto de todos los agentes.

El archivo `manual_toad.csv` es una plantilla para registrar mediciones humanas con TOAD Data Modeler. No se debe llenar con tiempos simulados. Para comparar métodos, use los mismos requisitos, registre fecha, persona, inicio y fin, y evalúe ambos esquemas con el mismo conjunto de dependencias esperadas.

## Pruebas

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```
