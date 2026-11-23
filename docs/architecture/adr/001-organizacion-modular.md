# ADR-001. Organización modular del Modelador 3FN

**Estado**: aceptado.
**Fecha**: 2026-11-23.

## Contexto

El prototipo reúne síntesis relacional, consultas a un modelo local, validación
en PostgreSQL y evaluación experimental. El archivo del flujo combinaba los
prompts, el transporte a Ollama y la generación de DDL. El código, los casos
y el material académico también tenían rutas distintas de ejecución.

## Alternativas

- Ordenar las carpetas y mantener el flujo en un solo módulo.
- Empaquetar una aplicación Python y asignar un módulo a cada responsabilidad.

## Decisión

Empaquetamos una aplicación Python con dos entradas, CLI y web local. El núcleo
de normalización trabaja con atributos y dependencias. El flujo coordina las
etapas y llama a los adaptadores cuando necesita Ollama. La validación del DDL
usa el adaptador de PostgreSQL. Organizamos los casos y la evidencia fuera del
paquete instalable.

## Consecuencias

Podemos probar el núcleo con datos en memoria y sustituir el cliente del
modelo durante las pruebas. Las dependencias externas se configuran cuando
se ejecuta un diseño real. La instalación editable en un entorno virtual
permite usar el comando `modelador` desde cualquier carpeta.
