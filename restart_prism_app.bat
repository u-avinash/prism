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
set "OTEL_CONFIG=%OTEL_ROOT_DIR%\otel-collector-config.yaml"
set "PRISM_OTLP_EXPORT_API_KEY=prism_6-qup2JlmoefCPPboOyFILwfBY1pQENGwOK04mwrqwg"

if not defined OTELCOL_CONTRIB_EXE (
    set "OTELCOL_CONTRIB_EXE=otelcol-contrib.exe"
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

if defined PRISM_OTLP_EXPORT_API_KEY (
    echo [2/4] Starting OpenTelemetry Collector with the configured project export key...
) else (
    echo [2/4] WARNING: PRISM_OTLP_EXPORT_API_KEY is not set.
    echo       Collector forwarding works only when Prism allows unassigned ingestion.
    echo       Set a project prism_ key before production or secured-demo use.
    echo [2/4] Starting OpenTelemetry Collector...
)

start "Prism OpenTelemetry Collector" /d "%OTEL_ROOT_DIR%" cmd /k ""%OTELCOL_CONTRIB_EXE%" --config "%OTEL_CONFIG%""
if errorlevel 1 (
    echo ERROR: Unable to start the OpenTelemetry Collector.
    echo        Install otelcol-contrib or set OTELCOL_CONTRIB_EXE to its full path.
    exit /b 1
)

cd /d "%ROOT_DIR%"

echo [3/4] Starting ingestion API...
start "Prism Ingestion API" /d "%ROOT_DIR%" cmd /k py -m uvicorn ingestion.api:app --host 0.0.0.0 --port 8000 --reload

echo [4/4] Starting UI server...
start "Prism UI" /d "%ROOT_DIR%" cmd /k py -m uvicorn ui.server:app --host 0.0.0.0 --port 8080 --reload

echo Prism restart sequence completed.
echo Collector config: %OTEL_CONFIG%
exit /b 0
