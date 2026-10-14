# -*- coding: utf-8 -*-
"""
Test: Generate errors from order service (port 8087) -> forward as OTLP -> create incidents in Prism.

Usage:
    py tools/tests/test_generate_errors_to_incidents.py
    py tools/tests/test_generate_errors_to_incidents.py --error-count 5
    py tools/tests/test_generate_errors_to_incidents.py --use-otel-collector
"""
import argparse
import io
import json
import sys
import time
from datetime import datetime, timezone

import requests

# Ensure UTF-8 output on Windows without replacing the stdout stream
# (replacing it causes buffering issues when captured by subprocesses).
import os as _os
if sys.platform == "win32":
    _os.environ.setdefault("PYTHONUTF8", "1")

ORDER_SERVICE_URL = "http://localhost:8087"
PRISM_INGESTION_URL = "http://localhost:8000"
OTEL_COLLECTOR_URL = "http://localhost:4318"
PRISM_UI_URL = "http://localhost:8080"

# Default API key registered for the NTT Data project (KEY-84B0FE0A).
# Override via --api-key or PRISM_OTLP_EXPORT_API_KEY env var.
DEFAULT_API_KEY = _os.getenv(
    "PRISM_OTLP_EXPORT_API_KEY",
    "prism_mFxw2e95N9xnal3iUkymx4afyqwnKOwiyaEzAr-GEx0",
)


# ---------------------------------------------------------------------------
# Step 1: Generate errors from the order service
# ---------------------------------------------------------------------------

def generate_errors(error_count: int = 3) -> dict:
    """Call generate-errors endpoint and return the JSON response."""
    url = f"{ORDER_SERVICE_URL}/generate-errors?errorCount={error_count}"
    print(f"\n[1] Calling {url}")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("errors", [])
    print(f"    [OK] Received {len(errors)} error(s)  orderId={data.get('orderId')}")
    for err in errors:
        sev = err.get("severity", "")
        step = err.get("step", "")
        msg = (err.get("error_message") or "")[:80]
        print(f"      * [{sev}] {step} -- {msg}")
    return data


# ---------------------------------------------------------------------------
# Step 2: Convert order-service errors to OTLP log records
# ---------------------------------------------------------------------------

SEVERITY_TEXT_TO_NUMBER = {
    "TRACE": 1,
    "DEBUG": 5,
    "INFO": 9,
    "WARN": 13,
    "WARNING": 13,
    "ERROR": 17,
    "FATAL": 21,
    "CRITICAL": 21,
    "HIGH": 17,
    "MEDIUM": 13,
    "LOW": 9,
}


def _error_to_otlp_log_record(error: dict, order_id: str) -> dict:
    """Convert a single order-service error dict into an OTLP log record."""
    severity_text = str(error.get("severity", "ERROR")).upper()
    # Map CRITICAL/HIGH -> ERROR for OTLP severity numbers
    otlp_severity_text = "ERROR" if severity_text in ("CRITICAL", "HIGH") else severity_text
    severity_number = SEVERITY_TEXT_TO_NUMBER.get(severity_text, 17)

    ts_str = error.get("timestamp") or datetime.now(timezone.utc).isoformat()
    try:
        if "T" in ts_str:
            # Strip timezone offset for fromisoformat (Python < 3.11 compat)
            ts_clean = ts_str[:26].replace("T", " ")
            ts_dt = datetime.fromisoformat(ts_clean.strip())
        else:
            ts_dt = datetime.now(timezone.utc)
    except Exception:
        ts_dt = datetime.now(timezone.utc)
    time_unix_nano = str(int(ts_dt.timestamp() * 1_000_000_000))

    error_message = error.get("error_message", "")
    error_type = error.get("error_type", error.get("step", "UNKNOWN"))
    step = error.get("step", "UNKNOWN")
    file_name = error.get("file", "order-processing-flows.xml")
    line = str(error.get("line", "0"))

    return {
        "timeUnixNano": time_unix_nano,
        "observedTimeUnixNano": time_unix_nano,
        "severityNumber": severity_number,
        "severityText": otlp_severity_text,
        "body": {
            "stringValue": f"[{step}] {error_type}: {error_message[:200]}"
        },
        "attributes": [
            {"key": "exception.type",       "value": {"stringValue": f"Mule{error_type.title().replace('_', '')}Exception"}},
            {"key": "exception.message",    "value": {"stringValue": error_message[:500]}},
            {"key": "exception.stacktrace", "value": {"stringValue": error_message}},
            {"key": "mule.flow.name",       "value": {"stringValue": step.lower().replace("_", "-") + "-flow"}},
            {"key": "mule.app.name",        "value": {"stringValue": "order-processing-service"}},
            {"key": "error.step",           "value": {"stringValue": step}},
            {"key": "error.file",           "value": {"stringValue": file_name}},
            {"key": "error.line",           "value": {"stringValue": line}},
            {"key": "order.id",             "value": {"stringValue": order_id}},
            {"key": "prism.severity",       "value": {"stringValue": severity_text}},
        ],
        "traceId": "",
        "spanId": "",
        "flags": 1,
    }


def build_otlp_payload(errors_response: dict) -> dict:
    """Wrap all errors from the order service into a single OTLP logs payload."""
    order_id = errors_response.get("orderId", "unknown")
    errors = errors_response.get("errors", [])

    log_records = [_error_to_otlp_log_record(err, order_id) for err in errors]

    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name",             "value": {"stringValue": "order-processing-service"}},
                        {"key": "deployment.environment",   "value": {"stringValue": "production"}},
                        {"key": "cloudhub.application.name","value": {"stringValue": "order-processing-service"}},
                        {"key": "mule.app.version",         "value": {"stringValue": "1.0.0"}},
                        {"key": "order.processing.order_id","value": {"stringValue": order_id}},
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {
                            "name": "order-processing-service",
                            "version": "1.0.0",
                        },
                        "logRecords": log_records,
                    }
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# Step 3: Send OTLP payload to Prism
# ---------------------------------------------------------------------------

def _auth_headers(api_key: str) -> dict:
    """Build Authorization header if an API key is provided."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def send_to_prism_direct(otlp_payload: dict, api_key: str = "") -> dict:
    """POST OTLP payload directly to Prism ingestion API on port 8000."""
    url = f"{PRISM_INGESTION_URL}/v1/logs"
    record_count = len(otlp_payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"])
    key_label = f" (key={api_key[:18]}...)" if api_key else " (no API key)"
    print(f"\n[2] Sending {record_count} log record(s) directly to Prism -> {url}{key_label}")
    resp = requests.post(url, json=otlp_payload,
                         headers=_auth_headers(api_key),
                         timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_to_otel_collector(otlp_payload: dict, api_key: str = "") -> dict:
    """POST OTLP payload to the OTEL Collector on port 4318 (it forwards to Prism)."""
    url = f"{OTEL_COLLECTOR_URL}/v1/logs"
    record_count = len(otlp_payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"])
    print(f"\n[2] Sending {record_count} log record(s) via OTEL Collector -> {url}")
    # The Collector adds the Authorization header itself from its env var;
    # do NOT send the key here to avoid double-auth.
    resp = requests.post(url, json=otlp_payload,
                         headers={"Content-Type": "application/json"},
                         timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Step 4: Verify incidents in Prism
# ---------------------------------------------------------------------------

def verify_incidents(result: dict) -> list:
    """Print ingestion result and return list of created incident IDs."""
    print(f"\n[3] Prism ingestion result:")
    print(f"    Status  : {result.get('status')}")
    print(f"    Message : {result.get('message')}")

    stats = result.get("stats", {})
    if stats:
        print(f"    Stats:")
        for k, v in stats.items():
            print(f"      {k}: {v}")

    created = result.get("created_incidents", [])
    dupes = result.get("duplicate_incidents", [])
    failed = result.get("failed_incidents", [])

    if created:
        print(f"\n    [OK] Created {len(created)} incident(s):")
        for inc in created:
            sev = inc.get("severity", "")
            iid = inc.get("incident_id", "")
            title = (inc.get("error_title") or "")[:70]
            print(f"      * [{sev}] {iid} -- {title}")
    if dupes:
        print(f"\n    [INFO] {len(dupes)} duplicate(s) found (occurrence counts updated):")
        for d in dupes:
            print(f"      * {d.get('incident_id')} (occurrence #{d.get('occurrence_count')})")
    if failed:
        print(f"\n    [FAIL] {len(failed)} failed:")
        for f_ in failed:
            title = (f_.get("error_title") or "")
            err = (f_.get("error") or "")[:100]
            print(f"      * {title} -- {err}")

    return [inc["incident_id"] for inc in created]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate order-service errors and forward them to Prism as OTLP logs"
    )
    parser.add_argument("--error-count", type=int, default=3,
                        help="Number of errors to generate (default: 3)")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY,
                        help="Project API key (Authorization: Bearer). Defaults to "
                             "PRISM_OTLP_EXPORT_API_KEY env var or the NTT Data project key.")
    parser.add_argument("--no-api-key", action="store_true",
                        help="Send without an API key (incidents will have project_id=None)")
    parser.add_argument("--use-otel-collector", action="store_true",
                        help="Route through OTEL Collector on port 4318 instead of direct to Prism")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the OTLP payload without sending it")
    args = parser.parse_args()

    api_key = "" if args.no_api_key else args.api_key

    route_label = "via OTEL Collector (4318)" if args.use_otel_collector else "Direct to Prism (8000)"
    key_label = (api_key[:18] + "...") if api_key else "none (project_id=None)"

    print("=" * 70)
    print("  Prism Test: generate-errors -> OTLP -> incidents")
    print("=" * 70)
    print(f"  Order service  : {ORDER_SERVICE_URL}")
    print(f"  Prism ingestion: {PRISM_INGESTION_URL}")
    print(f"  Prism UI       : {PRISM_UI_URL}")
    print(f"  Error count    : {args.error_count}")
    print(f"  Route          : {route_label}")
    print(f"  API key        : {key_label}")
    print("=" * 70)

    # --- Step 1: generate errors ---
    try:
        errors_response = generate_errors(args.error_count)
    except requests.exceptions.ConnectionError as exc:
        print(f"\n[FAIL] Cannot reach order service at {ORDER_SERVICE_URL}: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FAIL] generate-errors failed: {exc}")
        sys.exit(1)

    # --- Step 2: build OTLP payload ---
    otlp_payload = build_otlp_payload(errors_response)
    record_count = len(otlp_payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"])
    print(f"\n    Built OTLP payload with {record_count} log record(s)")

    if args.dry_run:
        print("\n[DRY RUN] OTLP payload that would be sent:")
        print(json.dumps(otlp_payload, indent=2))
        return

    # --- Step 3: send to Prism ---
    try:
        if args.use_otel_collector:
            result = send_to_otel_collector(otlp_payload, api_key)
        else:
            result = send_to_prism_direct(otlp_payload, api_key)
    except requests.exceptions.ConnectionError as exc:
        target = "OTEL Collector (4318)" if args.use_otel_collector else "Prism ingestion API (8000)"
        print(f"\n[FAIL] Cannot reach {target}: {exc}")
        sys.exit(1)
    except requests.exceptions.HTTPError as exc:
        print(f"\n[FAIL] HTTP error from ingestion API: {exc}")
        body = exc.response.text[:500] if exc.response else "no response"
        print(f"  Response body: {body}")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FAIL] Ingestion failed: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # --- Step 4: verify incidents ---
    incident_ids = verify_incidents(result)

    # --- Step 5: summary ---
    print("\n" + "=" * 70)
    if incident_ids:
        print(f"  [OK] SUCCESS -- {len(incident_ids)} incident(s) created in Prism")
        print(f"\n  View in UI: {PRISM_UI_URL}/incidents")
        for iid in incident_ids:
            print(f"    -> {PRISM_UI_URL}/incidents/{iid}")
    else:
        errors_count = len(errors_response.get("errors", []))
        dupes_count = len(result.get("duplicate_incidents", []))
        skipped_count = result.get("stats", {}).get("skipped_low_severity", 0)
        if dupes_count:
            print(f"  [INFO] No new incidents -- all {dupes_count} were duplicates (occurrence counts updated)")
        elif skipped_count:
            print(f"  [INFO] No new incidents -- {skipped_count} log(s) below ERROR severity threshold")
        else:
            print(f"  [FAIL] No incidents created from {errors_count} error(s) -- check logs above")
    print("=" * 70)


if __name__ == "__main__":
    main()
