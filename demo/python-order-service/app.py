"""Intentionally faultable Python order service for PRISM demonstrations."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
SERVICE_NAME = "python-order-service"
ENVIRONMENT = os.getenv("PRISM_DEMO_ENVIRONMENT", "demo")
PROJECT_NAME = os.getenv("PRISM_DEMO_PROJECT_NAME", "prism-capabilities-demo")
REPOSITORY_URL = os.getenv(
    "PRISM_DEMO_REPOSITORY_URL",
    "https://github.com/your-org/prism-capabilities-demo",
)
REPOSITORY_BRANCH = os.getenv("PRISM_DEMO_REPOSITORY_BRANCH", "main")

RESOURCE = Resource.create(
    {
        "service.name": SERVICE_NAME,
        "service.version": "1.0.0-demo",
        "service.namespace": "prism-demo",
        "deployment.environment.name": ENVIRONMENT,
        "prism.project.name": PROJECT_NAME,
        "prism.repository.url": REPOSITORY_URL,
        "prism.repository.branch": REPOSITORY_BRANCH,
        "prism.demo.service": SERVICE_NAME,
    }
)


def configure_observability() -> None:
    """Configure OTLP HTTP exporters to the PRISM demo collector."""
    trace_provider = TracerProvider(resource=RESOURCE)
    trace_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces"))
    )
    trace.set_tracer_provider(trace_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{OTLP_ENDPOINT}/v1/metrics"),
        export_interval_millis=5_000,
    )
    metrics.set_meter_provider(
        MeterProvider(resource=RESOURCE, metric_readers=[metric_reader])
    )

    logger_provider = LoggerProvider(resource=RESOURCE)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{OTLP_ENDPOINT}/v1/logs"))
    )
    set_logger_provider(logger_provider)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider))


configure_observability()
logger = logging.getLogger("prism.demo.python.orders")
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)
failure_counter = meter.create_counter(
    "prism.demo.failures",
    description="Intentionally generated failures for PRISM demonstrations",
)


class PaymentGatewayTimeout(Exception):
    """Simulated upstream payment gateway failure."""


class OrderValidationError(ValueError):
    """Simulated order validation defect."""


def error_attributes(scenario: str, order_id: str) -> dict[str, str]:
    """Produce useful incident metadata for PRISM RCA and code lookup."""
    return {
        "prism.demo.scenario": scenario,
        "prism.demo.intentional": "true",
        "order.id": order_id,
        "http.route": "/orders/{order_id}",
        "http.request.method": "POST",
        "logger.name": logger.name,
    }


def emit_failure(exception: Exception, scenario: str, order_id: str) -> None:
    """Export an OTLP ERROR log and its Python stack trace."""
    attributes = error_attributes(scenario, order_id)
    failure_counter.add(1, attributes)
    logger.error(
        "%s\nScenario: %s\nOrder ID: %s",
        exception,
        scenario,
        order_id,
        exc_info=(type(exception), exception, exception.__traceback__),
        extra=attributes,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Python order demo service started; OTLP endpoint=%s", OTLP_ENDPOINT)
    yield
    trace.get_tracer_provider().shutdown()
    metrics.get_meter_provider().shutdown()


app = FastAPI(
    title="PRISM Python Order Service Demo",
    description="Deliberately creates observable errors for PRISM demonstrations.",
    lifespan=lifespan,
)
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness endpoint that never generates an incident."""
    return {"status": "healthy", "service": SERVICE_NAME}


@app.post("/orders/{order_id}")
async def create_order(
    order_id: str,
    scenario: str = Query(
        "success",
        pattern="^(success|validation|timeout|exception|critical)$",
        description="Choose an error scenario to generate OTLP telemetry for PRISM.",
    ),
) -> dict[str, str]:
    """
    Run a deterministic, intentionally failing order scenario.

    Each error is logged at ERROR/FATAL severity with OpenTelemetry exception
    attributes and a trace correlation ID, but the application remains running
    so the same demonstration can be repeated.
    """
    with tracer.start_as_current_span("order.create") as span:
        span.set_attribute("prism.demo.scenario", scenario)
        span.set_attribute("order.id", order_id)
        span.set_attribute("prism.demo.intentional", True)

        if scenario == "success":
            return {"order_id": order_id, "status": "accepted"}

        try:
            if scenario == "validation":
                raise OrderValidationError(
                    f"Order {order_id} is invalid: shipping postal code is missing"
                )

            if scenario == "timeout":
                await asyncio.sleep(0.05)
                raise PaymentGatewayTimeout(
                    f"Payment gateway timed out after 30s while authorizing order {order_id}"
                )

            if scenario == "exception":
                inventory: dict[str, int] = {"SKU-001": 3}
                requested_sku = "SKU-404"
                available = inventory[requested_sku]
                return {"order_id": order_id, "inventory": str(available)}

            if scenario == "critical":
                raise RuntimeError(
                    f"Order {order_id} was charged twice; manual financial reconciliation required"
                )
        except Exception as exception:
            span.record_exception(exception)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exception)))
            emit_failure(exception, scenario, order_id)
            status_code = 503 if scenario == "timeout" else 500
            if scenario == "validation":
                status_code = 422
            if scenario == "critical":
                logger.critical(
                    "Critical payment integrity incident for order %s", order_id,
                    extra=error_attributes(scenario, order_id),
                )
                status_code = 500
            raise HTTPException(status_code=status_code, detail=str(exception)) from exception

    raise HTTPException(status_code=500, detail="Unexpected demo state")
