# Plan de desarrollo: Modelador 3FN como página web (demo para el profesor)

> Documento de trabajo para el agente de desarrollo. Léelo completo antes de tocar código.
> Plazo disponible: algo más de una semana. El plan está dimensionado a **9 días de trabajo** con un día de colchón.

## 0. Contexto y objetivo

**Qué es el proyecto.** `modelador` convierte requisitos de negocio escritos en lenguaje natural en un esquema relacional en 3FN: tablas, diccionario de datos y DDL para PostgreSQL. Un LLM propone atributos y dependencias funcionales (DF); un núcleo determinista (`core.py`) sintetiza, audita y genera el DDL. Hay dos modos: multiagente (`analyst` → `dictionary` → `coder`) y agente único (línea base experimental).

**Objetivo de esta etapa.** Una **página web desplegada en Render**, con acceso protegido por contraseña, que use un **LLM por API (OpenAI)** con **gasto limitado**, guarde los diseños en una **PostgreSQL en la nube** y valide el DDL en una base **aislada y con permisos mínimos**. Solo la verá el profesor, pero debe funcionar de forma fiable durante la demostración.

**Fuera de alcance** (no lo hagas): registro abierto de usuarios, pagos, múltiples roles, SSE/WebSockets, microservicios, frontend con framework JS y paso de compilación, soporte de otros motores SQL, BCNF.

### Estado actual del código (verificado)

| Archivo | Qué hace | Observación relevante |
|---|---|---|
| `src/modelador/core.py` | DF, cierre, cobertura canónica, claves candidatas, proyección, síntesis 3FN, `audit_model` | Es la parte más sólida. Solo biblioteca estándar. `projected_fds` es O(2^n) (límite 14 atributos por tabla, 30 en total) |
| `src/modelador/agents.py` | Prompts, esquemas JSON, validación de respuestas | Los esquemas ya usan `additionalProperties: false` y todas las claves en `required` |
| `src/modelador/pipeline.py` | `design()`, reintentos con retroalimentación, respaldo del `coder` | **Acoplado a Ollama:** `_agent` y `design()` hacen `isinstance(client, Ollama)` para pasar el esquema y el progreso |
| `src/modelador/sql.py` | `render_ddl` | Las claves foráneas se deducen con una heurística (la PK de otra tabla está contenida en las columnas de esta). No genera UNIQUE, CHECK ni índices. No protege contra palabras reservadas |
| `src/modelador/adapters/ollama.py` | Cliente con subproceso y plazo | Solo para desarrollo local en esta etapa |
| `src/modelador/adapters/postgres.py` | `validate_postgres` con `psql` | Ejecuta el DDL en una transacción con `ROLLBACK` en un esquema temporal |
| `src/modelador/web.py` | Servidor `http.server` con HTML embebido en un string | Se **reemplaza**. Los trabajos viven en memoria |
| `src/modelador/evaluation.py` | Benchmark y métricas | 3 casos sintéticos en `experiments/cases/reference.json` |
| `tests/` | 16 pruebas | Pasan con `PYTHONPATH=src`; **fallan sin instalar el paquete** |

Ejecutar las pruebas hoy: `PYTHONPATH=src python3 -m unittest discover -s tests`.

## 1. Reglas de trabajo para el agente

1. Trabaja en una rama por fase (`fase-0-base`, `fase-1-...`) y haz commits pequeños con mensaje en español o inglés, pero consistente.
2. Después de cada tarea, ejecuta las pruebas. No avances con la suite en rojo.
3. **Nunca** subas secretos al repositorio: claves de API, cadenas de conexión, contraseñas. Comprueba que `.env` esté en `.gitignore` antes del primer commit que lo toque. Entrega `.env.example` con valores falsos.
4. Mantén `core.py` sin dependencias externas. Es el núcleo que se defiende en el artículo.
5. Cada decisión de diseño no trivial va en un ADR corto en `docs/architecture/adr/` (formato de `001-organizacion-modular.md`).
6. Si una tarea marcada **[USUARIO]** bloquea tu avance, deja el resto hecho, escribe en el informe final qué falta y continúa con la siguiente tarea.
7. Prioridades: **P0** = imprescindible para la demo; **P1** = debería entrar; **P2** = solo si sobra tiempo. Si vas retrasado, recorta de abajo hacia arriba.
8. No inventes nombres de modelos ni precios de OpenAI. Todo eso va en variables de entorno que rellena el usuario.

## 2. Decisiones ya tomadas

| Tema | Decisión |
|---|---|
| LLM | API de OpenAI, detrás de una interfaz `LLMClient`. Ollama se conserva solo para desarrollo local |
| Salida estructurada | `response_format` con JSON Schema estricto, reutilizando los esquemas de `agents.py` |
| Backend | FastAPI + Uvicorn |
| Frontend | Plantillas Jinja2 + HTMX o JavaScript simple. **Sin** React ni compilación. Un solo despliegue |
| Diagrama ER | Mermaid.js cargado desde CDN en el navegador |
| Base de datos | PostgreSQL en la nube con dos bases separadas (ver sección 6) |
| Migraciones | Archivos `.sql` numerados y un ejecutor mínimo. Sin Alembic |
| Acceso | Una contraseña compartida y una cookie de sesión firmada |
| Despliegue | Render, Web Service desde `Dockerfile`, con despliegue automático desde GitHub |

## 3. Tareas que solo puede hacer el usuario  [USUARIO]

Pídelas pronto, porque son lo que más suele retrasar.

1. **Clave de API.** Comprobar que tiene una clave de la **plataforma de OpenAI** (empieza por `sk-`), no solo una suscripción de ChatGPT o de Codex. El acceso por suscripción no sirve para un servidor.
2. **Límite de gasto en OpenAI.** Crear un **proyecto** dedicado, generar la clave dentro de ese proyecto y configurar un presupuesto mensual bajo en el panel. Comprobar en la documentación actual si el límite es de corte duro o solo de aviso. **No confiar únicamente en eso:** la sección 5 implementa un tope propio.
3. **Cuenta de Render** conectada al repositorio de GitHub.
4. **PostgreSQL en la nube.** Crear la instancia (Render Postgres o Neon; ambas dan una cadena de conexión estándar). Anotar en las notas del proyecto las condiciones del plan gratuito, porque algunas instancias gratuitas caducan o se suspenden. Antes de la demo, comprobar que sigue activa.
5. **Variables de entorno en Render** (sección 9). El agente las documenta; el usuario las pega en el panel.
6. **Nombre del modelo de OpenAI** y **precios por millón de tokens** vigentes, para `OPENAI_MODEL` y la tabla de precios.

## 4. Calendario

| Día | Fase | Contenido | Prioridad |
|---|---|---|---|
| 1 | 0 | Cimientos del repositorio, interfaz `LLMClient` | P0 |
| 2 | 0–1 | Cliente OpenAI, control de gasto, pruebas | P0 |
| 3 | 2 | Mejoras del modelo relacional (palabras reservadas, FKs, restricciones, nombres) | P0 / P1 |
| 4 | 2 | Diagrama ER y exportaciones | P1 |
| 5 | 3 | Backend FastAPI y persistencia | P0 |
| 6 | 3 | Frontend, edición de DF y regeneración sin LLM | P0 / P1 |
| 7 | 4 | Autenticación, Docker, rol de validación, despliegue en Render | P0 |
| 8 | 5 | Benchmark ampliado con la API y evidencia para el artículo | P1 |
| 9 | 6 | Guion de la demo, README, pruebas finales | P0 |
| 10 | — | Colchón | — |

---

## Fase 0. Cimientos (Día 1)  [P0]

### 0.1 Que las pruebas corran sin instalar el paquete
- Añade a `pyproject.toml` una sección de pytest con `pythonpath = ["src"]` y `testpaths = ["tests"]`, o equivalente.
- Mantén compatibilidad con `python -m unittest discover -s tests`.
- **Criterio de aceptación:** en un clon limpio, `pytest` y `python -m unittest discover -s tests` pasan las 16 pruebas actuales.

### 0.2 Dependencias opcionales
En `pyproject.toml`, `dependencies = []` se mantiene vacío para el núcleo y se añaden extras:
- `[web]`: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `itsdangerous`, `psycopg[binary]`, `httpx` (o el SDK oficial de `openai`).
- `[dev]`: `pytest`, `ruff`.
- Crea `requirements.txt` generado desde el extra `[web]` para el Docker.
- **Criterio:** `pip install -e .[web,dev]` funciona y `modelador --help` sigue funcionando sin los extras web.

### 0.3 Calidad mínima
- Configura `ruff` (reglas por defecto más `I`). No reformatees todo el repositorio de golpe: aplica solo en archivos nuevos o tocados.
- Añade `.github/workflows/ci.yml`: instala `[dev]`, ejecuta `ruff check` y `pytest`.
- Revisa `.gitignore`: debe cubrir `.env`, `.venv/`, `runs/`, `__pycache__/`.

### 0.4 Interfaz `LLMClient`  (refactor clave)
Hoy `pipeline._agent` y `design()` hacen `isinstance(client, Ollama)`. Elimínalo.
- Crea `src/modelador/adapters/base.py` con un protocolo o clase base:
  ```python
  class LLMClient(Protocol):
      model: str
      progress: Callable[[dict], None] | None
      def ask(self, system: str, user: str, schema: dict | None = None) -> tuple[dict, dict]:
          """Devuelve (respuesta_json, uso). `uso` incluye input_tokens y output_tokens."""
  ```
- Haz que `Ollama` cumpla el protocolo y que `pipeline.py` pase siempre `schema=` y emita eventos de progreso para cualquier cliente.
- Los clientes simulados de `tests/` (que hoy implementan `ask(system, prompt)`) deben seguir funcionando: acepta `schema` como argumento opcional o adapta las pruebas.
- Excepción común: `LLMError`. `OllamaError` pasa a heredar de ella, y `design()` captura `LLMError`.
- **Criterio:** el pipeline no importa nada de Ollama salvo en `cli.py` y el adaptador; las 16 pruebas siguen verdes.

---

## Fase 1. Cliente OpenAI y control de gasto (Día 2)  [P0]

### 1.1 `adapters/openai_client.py`
- Implementa `LLMClient` llamando a la API de OpenAI con salida estructurada (JSON Schema, modo estricto).
- **Compatibilidad del esquema:** el modo estricto exige `additionalProperties: false` y todas las propiedades en `required`. Los esquemas de `agents.py` ya cumplen esto. Verifícalo con una prueba que recorra todos los esquemas. `dictionary_schema` y `coder_schema` generan propiedades dinámicas por atributo: confirma que sus nombres son válidos para la API.
- Parámetros leídos de variables de entorno: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` (opcional), `LLM_TIMEOUT_SECONDS` (por defecto 60).
- `temperature` bajo y `max_output_tokens` desde `MAX_OUTPUT_TOKENS`. Si el modelo elegido no admite `temperature`, omítelo sin fallar.
- Reintenta solo errores transitorios (429 y 5xx) con retroceso exponencial, **máximo 2 reintentos**, y cuéntalos para el control de gasto.
- Devuelve `usage` con `input_tokens` y `output_tokens` reales de la respuesta.
- Nunca registres la clave ni los encabezados en logs o trazas.
- **Criterio:** prueba unitaria con `httpx.MockTransport` (o equivalente) que simule una respuesta válida, un 429 y un 500. No se hacen llamadas reales en las pruebas.

### 1.2 Control de gasto propio  `BudgetGuard`  (obligatorio)
Archivo: `src/modelador/budget.py`. Es independiente del límite del panel de OpenAI.

**Configuración (variables de entorno, con valores conservadores por defecto):**

| Variable | Significado |
|---|---|
| `DAILY_BUDGET_USD` | Tope diario en dólares |
| `TOTAL_BUDGET_USD` | Tope acumulado de toda la demo |
| `MAX_CALLS_PER_RUN` | Máximo de llamadas al LLM por diseño (el modo multi puede hacer hasta ~9 con reintentos) |
| `MAX_RUNS_PER_DAY` | Máximo de diseños por día |
| `MAX_REQUIREMENTS_CHARS` | Longitud máxima del texto de requisitos (por ejemplo 6000) |
| `MAX_OUTPUT_TOKENS` | Tope de tokens de salida por llamada |
| `PRICE_INPUT_PER_MTOK`, `PRICE_OUTPUT_PER_MTOK` | Precios por millón de tokens, **rellenados por el usuario** |

**Comportamiento:**
1. **Antes** de cada llamada: estima el peor caso (tokens de entrada aproximados por longitud del texto + `MAX_OUTPUT_TOKENS`) y rechaza si superaría el tope diario o el total. Lanza `BudgetExceeded` con un mensaje claro en español.
2. **Después** de cada llamada: registra el uso real en la tabla `usage_ledger` (sección 6.3).
3. Rechaza si ya se hicieron `MAX_CALLS_PER_RUN` llamadas en ese diseño o `MAX_RUNS_PER_DAY` diseños ese día.
4. `BudgetGuard` envuelve al cliente (patrón decorador), de modo que el pipeline no sabe que existe.
5. Si faltan los precios, la aplicación **no arranca el modo OpenAI** y lo dice en el log. Nunca asumas un precio por defecto.
6. La interfaz muestra el gasto acumulado y el restante, para que el profesor y tú lo vean.

**Criterios de aceptación (pruebas):**
- Con tope diario de 0.01 USD y un cliente simulado que reporta mucho uso, la segunda llamada falla con `BudgetExceeded`.
- Un diseño que supera `MAX_CALLS_PER_RUN` termina con `status = "error"` y un motivo legible, sin quedar colgado.
- El gasto sobrevive a un reinicio del servidor (está en la base, no en memoria).
- Dos diseños simultáneos no pueden sobrepasar el tope por una condición de carrera (usa una transacción o un bloqueo de fila al reservar presupuesto).

### 1.3 Selección del cliente
En `cli.py` y en la aplicación web: `LLM_PROVIDER=openai|ollama` (por defecto `ollama` en local y `openai` en producción).

---

## Fase 2. Modelo relacional más fiable (Días 3–4)

### 2.1 Palabras reservadas e identificadores  [P0]
Problema real: `IDENT` acepta `user`, `order`, `table`, `group`, `primary`, etc., y el DDL fallaría en PostgreSQL o, peor, cambiaría de significado.
- Añade en `core.py` o en `sql.py` una lista de palabras reservadas de PostgreSQL y rechaza (o renombra con sufijo, de forma determinista y registrada en la traza) los atributos y tablas que coincidan. Alternativa válida: entrecomillar siempre los identificadores con `"` en `render_ddl`. Elige una y documéntala en un ADR.
- **Seguridad:** confirma por prueba que en el DDL **solo** aparecen identificadores validados, tipos de `ALLOWED_TYPES` y nada de texto libre (por ejemplo, las descripciones del diccionario no deben ir al SQL salvo como `COMMENT ON` correctamente escapado, y esto último es P2).
- **Prueba:** un caso con atributos `order`, `user` y `group` genera un DDL que se ejecuta en PostgreSQL.

### 2.2 Claves foráneas con fundamento  [P0]
La heurística actual de `render_ddl` puede producir claves foráneas espurias o ciclos.
- Mantén la derivación determinista, pero hazla **más estricta y explicable**: genera la FK solo si la PK completa de la tabla destino aparece en las columnas de la tabla origen **y** no es la propia PK de la origen. Registra para cada FK de dónde sale (`fk_origin`) y expónlo en el resultado.
- Detecta ciclos de referencias y repórtalos como advertencia, no como error.
- **P1:** pide al analista las cardinalidades (1:N, N:M) como dato opcional adicional (`relationships`) y úsalas para validar las FKs derivadas. Si no coinciden, advierte.
- **Prueba:** los 3 casos de `experiments/cases/reference.json` producen exactamente las FKs esperadas (añade `expected_foreign_keys` a cada caso).

### 2.3 Restricciones en el DDL  [P1]
- `UNIQUE` para cada clave candidata que no sea la PK (el auditor ya las calcula).
- Índices sobre columnas de claves foráneas que no sean prefijo de la PK.
- `ON DELETE` fijo y documentado (`RESTRICT`), configurable más adelante.
- **Prueba:** el DDL generado se ejecuta en PostgreSQL con un servicio de CI.

### 2.4 Nombres de tabla  [P1]
`name_tables` cae a `algo_data` si el LLM no devuelve un conjunto de columnas idéntico. Mejora el emparejamiento (mayor coincidencia por solapamiento, de forma determinista) y deja el nombre automático solo como último recurso, marcado como `auto_named: true` para que la interfaz lo señale.

### 2.5 Diagrama ER y exportaciones  [P1, Día 4]
- `src/modelador/export.py`: funciones puras que reciben el artefacto y devuelven
  - texto **Mermaid `erDiagram`** (tablas, columnas, PK, FK),
  - **diccionario de datos** en CSV y en Markdown,
  - **DDL** como `.sql`,
  - el **JSON completo** del resultado.
- **Criterio:** pruebas con el caso de matrícula universitaria; el Mermaid generado es sintácticamente válido (comprueba con un parser sencillo o con una verificación manual documentada).

---

## Fase 3. Backend y persistencia (Días 5–6)

### 3.1 Estructura
Crea el paquete `src/modelador/webapp/`:

```
webapp/
  main.py          # FastAPI app, rutas, plantillas
  auth.py          # contraseña compartida + cookie de sesión
  db.py            # conexión y consultas (psycopg)
  jobs.py          # ejecutor de trabajos con cancelación
  templates/       # Jinja2
  static/
migrations/
  001_init.sql
  002_usage_ledger.sql
```

`modelador serve` debe seguir funcionando (apunta a la nueva aplicación). Elimina `web.py` al final de la fase, no antes.

### 3.2 Esquema de la base de la aplicación (`migrations/001_init.sql`)
```sql
CREATE TABLE designs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    requirements  TEXT NOT NULL,
    mode          TEXT NOT NULL CHECK (mode IN ('multi','single')),
    status        TEXT NOT NULL CHECK (status IN ('queued','running','ok','error','cancelled')),
    model         TEXT,
    seconds       NUMERIC,
    error         TEXT,
    trace         JSONB
);
CREATE TABLE design_versions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    design_id     UUID NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
    version       INTEGER NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source        TEXT NOT NULL CHECK (source IN ('llm','manual_edit')),
    artifact      JSONB NOT NULL,
    postgres_validation JSONB,
    UNIQUE (design_id, version)
);
```
(`gen_random_uuid()` está disponible de serie en PostgreSQL 13 o superior; si no, usa `uuid4()` desde Python.)

### 3.3 Migraciones
Un ejecutor de ~40 líneas: crea la tabla `schema_migrations`, aplica en orden los `.sql` que falten, cada uno en su transacción. Se ejecuta al arrancar la aplicación.

### 3.4 Ejecución de trabajos  (`jobs.py`)  [P0]
- `ThreadPoolExecutor` con **pocos hilos (2)**. El diseño tarda decenas de segundos y no debe correr dentro de la petición.
- **Cancelación real:** una bandera por trabajo que el pipeline consulta entre agentes (pasa un `threading.Event` o un callback `should_cancel`). Hoy solo hay `KeyboardInterrupt`, que no sirve en la web.
- Los eventos de progreso se guardan en memoria con el id del trabajo y se leen por sondeo cada 1–2 s (ya funciona así; no pases a SSE).
- Al arrancar, marca como `error` («reiniciado») cualquier diseño que haya quedado en `running` o `queued`.
- El resultado final se persiste en `designs` y `design_versions` (versión 1, `source = 'llm'`).

### 3.5 Rutas
| Ruta | Función |
|---|---|
| `GET /login`, `POST /login`, `POST /logout` | Acceso con contraseña |
| `GET /` | Lista de diseños y formulario de nuevo diseño |
| `POST /designs` | Crea y lanza un diseño (valida longitud y modo) |
| `GET /designs/{id}` | Página del diseño: progreso, tablas, diccionario, DDL, ER, auditoría |
| `GET /api/designs/{id}/status` | Estado y eventos (para el sondeo) |
| `POST /designs/{id}/cancel` | Cancela |
| `POST /designs/{id}/versions` | Nueva versión por edición manual (3.7) |
| `GET /designs/{id}/export/{ddl,dictionary.csv,dictionary.md,json,er}` | Exportaciones |
| `GET /admin/usage` | Gasto acumulado y restante |
| `GET /healthz` | Para Render (sin autenticación, sin tocar la base de datos de validación) |

### 3.6 Frontend (Jinja2 + HTMX o JS simple)
- Una sola hoja de estilos. Reutiliza la paleta actual (`#123b42`, `#087b72`).
- La página de un diseño muestra: estado por agente, tablas, auditoría de 3FN con una explicación legible de cada violación, diccionario, diagrama ER (Mermaid), DDL con botón de copiar, resultado de la validación en PostgreSQL y las advertencias (respaldo del codificador, nombres automáticos, ciclos de FK).
- Escapa siempre el contenido que viene del LLM o del usuario (Jinja2 lo hace por defecto: no uses `|safe` salvo en Mermaid, y sanea ese texto).
- Mantén el aviso visible: «La 3FN se verifica respecto de las DF declaradas, no de toda la semántica del negocio».

### 3.7 Edición de DF y regeneración **sin LLM**  [P1, valor alto]
Es lo que convierte el prototipo en una herramienta: si el LLM se equivoca en una DF, el usuario la corrige.
- La página muestra las DF inferidas como filas editables (determinante → dependiente): añadir, borrar, modificar.
- `POST /designs/{id}/versions` recibe la lista de DF, reutiliza los atributos y el diccionario de la última versión, vuelve a ejecutar de forma determinista `parse_fds` → `synthesize_3nf` → `audit_model` → `render_ddl` → validación en PostgreSQL, y guarda una nueva versión con `source = 'manual_edit'`. Si aparecen atributos nuevos sin definición, asígnales `TEXT` y `nullable = true`, y avísalo.
- No llama al LLM, así que **no consume presupuesto**.
- Muestra un resumen de cambios respecto a la versión anterior (tablas añadidas, eliminadas y modificadas).
- **Criterio:** en el caso de matrícula, borrar la DF `professor_id → professor_name` produce una versión nueva coherente y el DDL valida.

### 3.8 Pruebas de la fase
- Pruebas de rutas con `TestClient` de FastAPI y un LLM simulado.
- Prueba de persistencia: crear un diseño, reiniciar la aplicación (nueva instancia), recuperarlo.
- Prueba de cancelación y de presupuesto agotado desde la API.

---

## Fase 4. Seguridad, Docker y despliegue en Render (Día 7)  [P0]

### 4.1 Autenticación
- Contraseña única en `APP_PASSWORD` (comparación en tiempo constante con `hmac.compare_digest`), cookie de sesión firmada con `SESSION_SECRET` (`itsdangerous`), `HttpOnly`, `Secure` y `SameSite=Lax`, caducidad de 12 h.
- Todas las rutas exigen sesión, salvo `/login` y `/healthz`.
- Límite de intentos de login (por ejemplo, 5 fallos por IP y 10 minutos, en memoria).
- Protección CSRF para los `POST` (un token por sesión en los formularios, o `SameSite=Strict` más comprobación del encabezado `Origin`).
- Cabeceras: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. Si cargas Mermaid desde un CDN, añade una `Content-Security-Policy` que lo permita expresamente y nada más.
- **Criterio:** sin cookie, `GET /` redirige a `/login`; con contraseña incorrecta no se crea sesión; hay pruebas de ambos casos.

### 4.2 Aislamiento de la validación del DDL  (la tarea de «media hora»)  [P0]
**Riesgo:** el sitio ejecuta DDL derivado de un LLM contra una base en la nube. La defensa es de varias capas.

1. **Una base de datos distinta** para validar (`modelador_validation`), separada de la de la aplicación (`modelador_app`). Si en tu proveedor no puedes crear una segunda base, usa un esquema aparte y el rol de abajo, pero la base separada es lo preferible.
2. **Dos roles:**
   - `app_user`: dueño de las tablas de `modelador_app`. Sin acceso a la base de validación.
   - `validator`: sin acceso alguno a `modelador_app`; en `modelador_validation` solo puede crear esquemas y objetos dentro de ellos.
3. **Script `scripts/setup_validator_role.sql`** (el agente lo escribe y lo documenta; lo ejecuta el usuario con el rol administrador):
   ```sql
   CREATE ROLE validator LOGIN PASSWORD :'validator_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
   -- Dentro de la base modelador_validation:
   REVOKE ALL ON DATABASE modelador_app FROM validator;      -- por si acaso
   REVOKE ALL ON SCHEMA public FROM validator;
   GRANT CONNECT, CREATE ON DATABASE modelador_validation TO validator;
   ALTER ROLE validator SET statement_timeout = '10s';
   ALTER ROLE validator SET lock_timeout = '3s';
   ALTER ROLE validator SET idle_in_transaction_session_timeout = '15s';
   ALTER ROLE validator CONNECTION LIMIT 3;
   ```
   Ajusta los nombres según el proveedor (algunos limitan qué se puede revocar).
4. **Reescribe `validate_postgres`** para usar `psycopg` en lugar del subproceso `psql` (así el contenedor no necesita el cliente `psql`):
   - Conecta con `VALIDATION_DATABASE_URL` (rol `validator`).
   - `BEGIN` → `CREATE SCHEMA modelador_test_<hex>` → `SET LOCAL search_path` → ejecutar DDL → `ROLLBACK`. Siempre `ROLLBACK`, también ante error (usa `try/finally`).
   - Rechaza antes de ejecutar un DDL mayor que un tamaño razonable (por ejemplo 100 KB) y limita el número de sentencias.
   - Comprueba **en el código** que el DDL solo contiene sentencias `CREATE TABLE` y `ALTER TABLE ... ADD FOREIGN KEY` / `CREATE INDEX` / `ADD UNIQUE` producidas por `render_ddl`. Cualquier otra cosa se rechaza sin ejecutarse. Esto es una **lista blanca** y es una defensa adicional, no la única.
   - Mantén la misma forma del resultado (`passed`, `failed`, `unavailable`, con `detail`).
5. **Pruebas** (con PostgreSQL del servicio de CI):
   - Un DDL válido pasa y no deja objetos tras el `ROLLBACK`.
   - Un DDL con una sentencia no permitida (`DROP TABLE designs`, `CREATE EXTENSION`, `COPY ... PROGRAM`) se rechaza **sin ejecutar**.
   - El rol `validator` no puede leer `designs` (prueba de integración documentada, aunque se ejecute a mano).
- **Criterio de aceptación:** documentado en `docs/seguridad.md` con el modelo de amenazas en 10 líneas y cómo se verificó cada capa.

### 4.3 Docker
`Dockerfile` en la raíz:
- Imagen base `python:3.12-slim` (o la versión que esté probada en el CI).
- Usuario no root, `pip install --no-cache-dir .[web]`, `EXPOSE` del puerto indicado por la variable `PORT` que inyecta Render.
- Comando: `uvicorn modelador.webapp.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
- `.dockerignore` que excluya `docs/`, `runs/`, `.git`, `.venv`, `experiments/results`.
- **Criterio:** `docker build` y `docker run` locales arrancan, `GET /healthz` responde 200 y las migraciones se aplican contra una base local.

### 4.4 Render
- Archivo `render.yaml` (Blueprint) con un Web Service de tipo Docker, `healthCheckPath: /healthz` y las variables de entorno declaradas con `sync: false` para los secretos.
- Variables de entorno (todas documentadas en `.env.example`):

| Variable | Contenido |
|---|---|
| `APP_PASSWORD` | Contraseña compartida de la demo |
| `SESSION_SECRET` | Cadena aleatoria larga |
| `DATABASE_URL` | Base `modelador_app` (rol `app_user`) |
| `VALIDATION_DATABASE_URL` | Base `modelador_validation` (rol `validator`) |
| `LLM_PROVIDER` | `openai` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Del usuario |
| `PRICE_INPUT_PER_MTOK`, `PRICE_OUTPUT_PER_MTOK` | Del usuario |
| `DAILY_BUDGET_USD`, `TOTAL_BUDGET_USD`, `MAX_CALLS_PER_RUN`, `MAX_RUNS_PER_DAY`, `MAX_REQUIREMENTS_CHARS`, `MAX_OUTPUT_TOKENS` | Topes de la sección 1.2 |

- Nota sobre el plan gratuito de Render: el servicio puede suspenderse tras un tiempo sin tráfico y la primera visita tarda en responder. Documenta en el README que hay que abrir la página unos minutos antes de la demo. Los trabajos largos se pierden si el servicio se reinicia a mitad: ya está cubierto por el marcado de «reiniciado» (3.4).
- **Criterio:** la URL de Render muestra el login, entra con la contraseña, crea un diseño real con el modelo de OpenAI, lo guarda y sigue apareciendo tras reiniciar el servicio.

---

## Fase 5. Evidencia para el artículo (Día 8)  [P1]

El piloto actual (3 casos, un modelo, una semilla) es delgado, y sus casos redactan las DF casi literalmente («student_id determina student_name»), con lo que se mide poco más que copiar la frase.

1. **Amplía `experiments/cases/reference.json` a 10–15 casos** con tres niveles de dificultad:
   - *explícito* (como los actuales),
   - *implícito* (las DF se deducen del texto sin enunciarlas),
   - *ambiguo* (falta información; el sistema debería declarar supuestos).
   Cada caso lleva `expected` y `expected_foreign_keys`. Mantén los casos en español.
2. **Métricas nuevas en `evaluation.py`:** exactitud de claves foráneas, número de llamadas y de reintentos por caso, tokens de entrada y salida, **costo estimado** y tiempo.
3. **Repeticiones:** ejecuta cada caso y modo **3 veces** y reporta media y rango. Una sola semilla no demuestra nada.
4. **Control de costo:** el benchmark pasa por `BudgetGuard`. Antes de lanzarlo, el agente calcula y muestra el costo estimado y pide confirmación al usuario si supera un umbral.
5. Genera `experiments/results/<fecha>/summary.csv` y una tabla en Markdown lista para el artículo (`docs/article/`).
6. **No cambies las cifras del artículo existente sin avisar.** Entrega las nuevas en un archivo aparte y deja que el usuario decida qué incorporar.

---

## Fase 6. Cierre y demostración (Día 9)  [P0]

1. **README** actualizado: instalación local, variables de entorno, cómo ejecutar pruebas, cómo desplegar en Render, cómo configurar la base y el rol de validación.
2. **`docs/demo.md`: guion de la demostración** de 5–7 minutos:
   1. Entrar con la contraseña.
   2. Pegar el caso de matrícula universitaria; ejecutar el modo multiagente; mostrar el progreso por agente.
   3. Revisar tablas, diagrama ER, auditoría de 3FN y la validación en PostgreSQL.
   4. Editar una DF y regenerar sin LLM; comparar versiones.
   5. Mostrar la comparación multiagente frente a agente único.
   6. Enseñar el panel de gasto.
   Incluye **un plan B**: un diseño ya guardado por si la API o la red fallan durante la demo, y capturas de pantalla.
3. **Prueba de humo final contra la URL de Render**, con una lista de comprobación (login, diseño real, cancelación, edición de DF, exportaciones, panel de gasto, reinicio del servicio).
4. **Informe final del agente** (`INFORME.md`): qué se hizo, qué quedó fuera, qué pasos manuales faltan por parte del usuario y problemas conocidos.

---

## 5. Lista de verificación final (todo debe cumplirse antes de la demo)

- [ ] `pytest` verde en el CI, incluida la prueba con PostgreSQL real.
- [ ] Ningún secreto en el repositorio (`git log -p | grep -i "sk-"` sin resultados; `.env` ignorado).
- [ ] La aplicación no arranca el modo OpenAI sin precios ni topes configurados.
- [ ] El tope de gasto detiene una ejecución en una prueba real con un valor mínimo.
- [ ] El rol `validator` no puede leer las tablas de la aplicación.
- [ ] Un DDL con sentencias no permitidas se rechaza sin ejecutarse.
- [ ] Sin sesión, ninguna ruta devuelve datos de diseños.
- [ ] El servicio de Render responde tras un reinicio y los diseños persisten.
- [ ] El guion de la demo se ha ensayado una vez completo contra la URL pública.
- [ ] Hay un diseño guardado de respaldo para el plan B.

## 6. Anexos

### 6.1 Variables de entorno: `.env.example`
```
APP_PASSWORD=cambia-esto
SESSION_SECRET=cadena-aleatoria-larga
DATABASE_URL=postgresql://app_user:***@host:5432/modelador_app
VALIDATION_DATABASE_URL=postgresql://validator:***@host:5432/modelador_validation
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=
PRICE_INPUT_PER_MTOK=
PRICE_OUTPUT_PER_MTOK=
DAILY_BUDGET_USD=1.00
TOTAL_BUDGET_USD=5.00
MAX_CALLS_PER_RUN=12
MAX_RUNS_PER_DAY=30
MAX_REQUIREMENTS_CHARS=6000
MAX_OUTPUT_TOKENS=2000
LLM_TIMEOUT_SECONDS=60
```
Los valores numéricos son puntos de partida conservadores; el usuario los ajusta.

### 6.2 Orden de recorte si hay retraso
Se recorta en este orden: 5 (benchmark ampliado) → 2.5 (exportaciones salvo el DDL) → 2.4 → 2.3 → 3.7 → 2.2 (cardinalidades). **No se recorta nunca:** 0.4, 1.1, 1.2, 3.4, 4.1, 4.2, 4.4 y 6.

### 6.3 Tabla del libro de uso (`migrations/002_usage_ledger.sql`)
```sql
CREATE TABLE usage_ledger (
    id             BIGSERIAL PRIMARY KEY,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    design_id      UUID REFERENCES designs(id) ON DELETE SET NULL,
    agent          TEXT,
    model          TEXT NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    cost_usd       NUMERIC(12,6) NOT NULL
);
CREATE INDEX usage_ledger_ts_idx ON usage_ledger (ts);
```

### 6.4 Riesgos conocidos
| Riesgo | Mitigación |
|---|---|
| El plan gratuito de la base o de Render se suspende | Comprobar antes de la demo; plan B con capturas y diseño guardado |
| El modelo devuelve DF erróneas | Edición manual de DF (3.7); el artículo debe declarar que la 3FN es relativa a las DF declaradas |
| Costo mayor al previsto por reintentos | `MAX_CALLS_PER_RUN`, topes diario y total, límite del proveedor |
| `projected_fds` es exponencial | Mensaje claro al superar el límite de atributos; no ampliar el límite ahora |
| Condición de carrera en el presupuesto | Reserva con transacción y bloqueo de fila (1.2) |
