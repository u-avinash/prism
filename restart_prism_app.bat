:: ╔══════════════════════════════════════════════════════════════════════╗
:: ║                          P  R  I  S  M                               ║
:: ║       Autonomous AI Incident Management System                       ║
:: ╚══════════════════════════════════════════════════════════════════════╝
::
::   Building an Autonomous AI Incident Management System
::   with LangGraph and OpenTelemetry
::
::   Author   : Upadhyayula Avinash
::   GitHub   : https://github.com/u-avinash
::   LinkedIn : https://www.linkedin.com/in/avinash-upadhyayula/
::   Email    : uavinash.csit@gmail.com
::
::   Copyright (c) 2026-2035 Upadhyayula Avinash. All rights reserved.
::
@echo off
setlocal EnableExtensions DisableDelayedExpansion

REM Prism restart helper for Windows.
REM Stops existing Prism servers and starts the bundled OpenTelemetry Collector
REM configuration, ingestion API, and dashboard in separate command windows.
REM
REM For secured ingestion or the Collector-mediated Postman demo, set the
REM project API key before launching this helper:
REM   set PRISM_OTLP_EXPORT_API_KEY=prism_<project-api-key>
REM   restart_prism_app.bat
REM
REM Override OTELCOL_CONTRIB_EXE when otelcol-contrib.exe is not on PATH:
REM   set OTELCOL_CONTRIB_EXE=C:\otelcol-contrib\otelcol-contrib.exe

set "ROOT_DIR=%~dp0"
SET "OTEL_ROOT_DIR=C:\otelcol-contrib_0.161.0_windows_386"

REM Always use the Prism project config, not a copy in the collector directory.
set "OTEL_CONFIG=%ROOT_DIR%config\otel-collector-config.yaml"

REM Project API key forwarded to the OTEL Collector so it can authenticate
REM outbound OTLP/HTTP requests to the Prism ingestion API on port 8000.
REM Incidents ingested via the Collector will be associated with the project
REM that owns this key.  Rotate the key via the Team Admin -> API Keys page.
REM Key ID  : KEY-84B0FE0A
REM Label   : OTEL Collector - Order Processing Service
REM Project : NTT Data (PRJ-5B95A9DB)
REM Created : 2026-10-09  — rotate via Team Admin -> API Keys page.
if not defined PRISM_OTLP_EXPORT_API_KEY (
    set "PRISM_OTLP_EXPORT_API_KEY=prism_mFxw2e95N9xnal3iUkymx4afyqwnKOwiyaEzAr-GEx0"
)

REM Default to the full path inside OTEL_ROOT_DIR so the executable is found
REM even when otelcol-contrib is not on the system PATH.
if not defined OTELCOL_CONTRIB_EXE (
    set "OTELCOL_CONTRIB_EXE=%OTEL_ROOT_DIR%\otelcol-contrib.exe"
)

if not exist "%OTEL_CONFIG%" (
    echo ERROR: Bundled Collector configuration was not found:
    echo        %OTEL_CONFIG%
    exit /b 1
)

echo [1/4] Stopping existing Prism UI and ingestion processes...
for /f "tokens=2 delims==" %%P in ('wmic process where "(Name='python.exe' or Name='py.exe' or Name='pyw.exe') and (CommandLine like '%%ingestion.api:app%%' or CommandLine like '%%ui.server:app%%' or CommandLine like '%%ingestion/api.py%%' or CommandLine like '%%ui/server.py%%')" get ProcessId /value 2^>nul ^| findstr /b "ProcessId="') do (
    echo Stopping PID %%P
    taskkill /pid %%P /f >nul 2>&1
)

REM Sync the Prism project otel-collector-config.yaml to the collector
REM directory so the collector can be launched with a local (no-spaces) path.
REM The Prism config is the authoritative source; the collector directory copy
REM is always overwritten on every restart to pick up config changes.
echo [2/4] Syncing Prism OTEL config to collector directory...
copy /Y "%OTEL_CONFIG%" "%OTEL_ROOT_DIR%\otel-collector-config.yaml" >nul
if errorlevel 1 (
    echo ERROR: Could not copy Prism OTEL config to collector directory.
    echo        Source : %OTEL_CONFIG%
    echo        Target : %OTEL_ROOT_DIR%\otel-collector-config.yaml
    exit /b 1
)
echo        Source : %OTEL_CONFIG%
echo        Target : %OTEL_ROOT_DIR%\otel-collector-config.yaml  [updated]

if defined PRISM_OTLP_EXPORT_API_KEY (
    echo [2/4] Starting OpenTelemetry Collector with the configured project export key...
) else (
    echo [2/4] WARNING: PRISM_OTLP_EXPORT_API_KEY is not set.
    echo       Collector forwarding works only when Prism allows unassigned ingestion.
    echo       Set a project prism_ key before production or secured-demo use.
    echo [2/4] Starting OpenTelemetry Collector...
)

REM Launch otelcol-contrib.exe from its own directory using the local copy of
REM the config (no spaces in path — avoids cmd /k quoting issues).
REM The API key is set explicitly in the child cmd window so the collector
REM process inherits it and substitutes ${env:PRISM_OTLP_EXPORT_API_KEY} in
REM the exported Authorization: Bearer header.
start "Prism OpenTelemetry Collector" /d "%OTEL_ROOT_DIR%" cmd /k "set PRISM_OTLP_EXPORT_API_KEY=%PRISM_OTLP_EXPORT_API_KEY%&& otelcol-contrib.exe --config otel-collector-config.yaml"

cd /d "%ROOT_DIR%"

echo [3/4] Starting ingestion API...
start "Prism Ingestion API" /d "%ROOT_DIR%" cmd /k py -m uvicorn ingestion.api:app --host 0.0.0.0 --port 8000 --reload

echo [4/4] Starting UI server...
start "Prism UI" /d "%ROOT_DIR%" cmd /k py -m uvicorn ui.server:app --host 0.0.0.0 --port 8080 --reload

echo Prism restart sequence completed.
echo Collector config: %OTEL_CONFIG%
exit /b 0
