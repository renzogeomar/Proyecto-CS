# ADR-002. Contrato para clientes de modelos de lenguaje

**Estado**: aceptado.
**Fecha**: 2026-11-24.

## Contexto

La orquestación dependía del tipo concreto de Ollama para pasar esquemas y
notificar el progreso. Se necesita admitir proveedores futuros sin modificar
el núcleo ni los agentes.

## Alternativas

- Mantener comprobaciones del tipo concreto para cada proveedor.
- Definir un protocolo común e inyectar clientes en la orquestación.

## Decisión

Usamos `LLMClient` y `LLMError` como contrato. Cada cliente recibe el esquema
JSON y devuelve la respuesta junto con los tokens de entrada y salida. La
factoría del paquete de adaptadores conserva Ollama como opción local por
defecto. Los eventos se envían al callback del cliente o al de la ejecución.
Cuando se especifica un callback por ejecución, se copia superficialmente el
cliente para no modificar el callback de la instancia original.

## Consecuencias

Los clientes simulados y los proveedores futuros deben aceptar `schema`.
Ollama mantiene sus métricas originales y añade los nombres de tokens comunes.
El núcleo de normalización sigue sin depender de bibliotecas externas.
