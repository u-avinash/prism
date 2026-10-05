# PRISM Capability Demonstration Suite

This directory contains intentional-failure services for demonstrating PRISM's
OpenTelemetry ingestion, incident creation, technology detection, RCA,
recommended fixes/tests, approval workflow, and optional Jira/GitHub/Slack
integrations.

| Service | Port | Technology | Error scenarios |
|---|---:|---|---|
| `python-order-service` | 8081 | Python / FastAPI | validation, payment timeout, missing inventory, critical duplicate charge |
| `go-inventory-service` | 8082 | Go / net/http | warehouse timeout, invalid cache record, recovered panic, critical oversell |
| `mulesoft-fulfillment-api` | 8083 | Mule 4 / DataWeave | downstream timeout, mapping failure, duplicate fulfillment |

## Architecture

```text
Demo service -> OTLP HTTP (logs, traces, metrics) -> OpenTelemetry Collector
             -> Authorization: Bearer project-api-key -> PRISM /v1/*
             -> incident workflow, UI, optional integrations
```

PRISM creates incidents from **OTLP logs at severity ERROR or higher**.
Traces and metrics are also sent to PRISM for observability context. Each
service includes the following resource attributes:

- `service.name`, `service.version`, `service.namespace`
- `deployment.environment.name`
- `prism.project.name`
- `prism.repository.url`, `prism.repository.branch`
- technology-specific attributes such as `mule.flow.name`

The collector owns the sensitive `Authorization` header. Individual services
never contain a PRISM API key.

## Prerequisites

- PRISM ingestion API running at `http://localhost:8000`
- Docker Desktop / Docker Compose v2 for the Python and Go stack
- A PRISM project and its project-scoped API key when ingestion authentication
  is enabled
- MuleSoft Anypoint Studio 7 with Mule 4.6.x only for the Mule demo

## Configuration

1. Create the local configuration file:

   ```powershell
   Copy-Item demo/.env.example demo/.env
   ```

2. Edit `demo/.env`:

   - Set `PRISM_OTLP_EXPORT_API_KEY` to the generated key for the intended
     PRISM project. If your local PRISM ingestion explicitly allows open
     ingestion, it may remain blank.
   - Set `PRISM_INGESTION_ENDPOINT=http://host.docker.internal:8000` when
     PRISM runs on the Windows host and the collector runs in Docker.
   - Replace the repository metadata with the GitHub repository that contains
     these demo sources before using PRISM's code fetch/PR capabilities.

3. Keep LLM, Jira, GitHub, Slack, and Anypoint values blank until the final
   end-to-end integration test. Their placeholders are intentionally located
   in `.env.example`.

> Never commit `demo/.env`; it can contain a project API key or integration
> credentials.

## Run Python and Go with Docker Compose

From this directory:

```powershell
docker compose --env-file .env up --build
```

The collector's health endpoint is available at
`http://localhost:13133/`. It receives OTLP on ports `4317` (gRPC) and `4318`
(HTTP).

### Trigger Python incidents

```powershell
# Normal response: no incident
curl.exe -X POST "http://localhost:8081/orders/ORD-100?scenario=success"

# High-severity Python ValueError, suitable for validation/test-suggestion demo
curl.exe -X POST "http://localhost:8081/orders/ORD-101?scenario=validation"

# Timeout incident and dependency-failure RCA
curl.exe -X POST "http://localhost:8081/orders/ORD-102?scenario=timeout"

# KeyError with Python stack trace and code-location evidence
curl.exe -X POST "http://localhost:8081/orders/ORD-103?scenario=exception"

# Critical duplicate-charge business incident
curl.exe -X POST "http://localhost:8081/orders/ORD-104?scenario=critical"
```

### Trigger Go incidents

```powershell
# Normal response: no incident
curl.exe "http://localhost:8082/inventory/SKU-100?scenario=success"

# Gateway timeout and retry/timeout remediation scenario
curl.exe "http://localhost:8082/inventory/SKU-101?scenario=upstream-timeout"

# Missing-record cache defect with Go stack trace
curl.exe "http://localhost:8082/inventory/SKU-102?scenario=nil-pointer"

# Recovered Go panic with stack trace
curl.exe "http://localhost:8082/inventory/SKU-103?scenario=panic"

# Critical oversell/inventory-integrity scenario
curl.exe "http://localhost:8082/inventory/SKU-104?scenario=critical"
```

## Run the MuleSoft demo

1. In Anypoint Studio, import
   `demo/mulesoft-fulfillment-api` as an existing Mule project.
2. Ensure its `config.yaml` points to a reachable collector:
   - Studio running on the host: set `OTEL_COLLECTOR_HOST=localhost`.
   - Mule runtime in a container on the Compose network: retain
     `otel-collector`.
3. Run the application. It listens on port `8083`.
4. Trigger a scenario:

   ```powershell
   curl.exe -X POST "http://localhost:8083/fulfill/MULE-101?scenario=downstream-timeout"
   curl.exe -X POST "http://localhost:8083/fulfill/MULE-102?scenario=mapping-error"
   curl.exe -X POST "http://localhost:8083/fulfill/MULE-103?scenario=critical"
   ```

The Mule error handler posts a standards-compliant OTLP/JSON log to
`/v1/logs` on the collector. It includes `mule.application.name`,
`mule.flow.name`, the Mule error type, and the DataWeave/Mule diagnostic
message. The collector forwards it to PRISM with the configured project key.

## Expected PRISM demonstration sequence

1. Trigger one failure above and wait a few seconds for batch delivery.
2. Open PRISM's **Incidents** page and select the newly created incident.
3. Demonstrate:
   - OTLP log content, error stack, service/environment, trace and span IDs.
   - Technology detection: Python/FastAPI, Go, or MuleSoft/Mule 4.
   - Severity assessment and recurring-error grouping by invoking an identical
     scenario multiple times.
   - RCA, suggested code change, and test recommendation generation.
   - Approval gate before any repository modification.
4. Populate project integration settings only at the final stage:
   - **LLM** enables richer RCA, code fix, test, and patch content.
   - **GitHub** enables source lookup, branch/PR creation, and verification.
   - **Jira** enables ticket creation.
   - **Slack** enables incident and workflow notifications.
   - **Anypoint** can be configured for Mule deployment/verification.

## Cleanup

```powershell
docker compose --env-file .env down --remove-orphans
```

The suite deliberately uses explicit query parameters to fail; it does not
create background failures or contact external business systems.
