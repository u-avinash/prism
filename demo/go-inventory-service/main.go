// Intentionally faultable Go inventory service for PRISM demonstrations.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"runtime/debug"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

const serviceName = "go-inventory-service"

var (
	otlpEndpoint    = getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
	environment     = getenv("PRISM_DEMO_ENVIRONMENT", "demo")
	projectName     = getenv("PRISM_DEMO_PROJECT_NAME", "prism-capabilities-demo")
	repositoryURL   = getenv("PRISM_DEMO_REPOSITORY_URL", "https://github.com/your-org/prism-capabilities-demo")
	repositoryBranch = getenv("PRISM_DEMO_REPOSITORY_BRANCH", "main")
	tracer          = otel.Tracer("prism.demo.go.inventory")
)

type inventoryError struct {
	scenario string
	message  string
}

func (e *inventoryError) Error() string {
	return e.message
}

func main() {
	shutdown, err := configureTracing()
	if err != nil {
		log.Fatalf("unable to configure tracing: %v", err)
	}
	defer func() {
		if err := shutdown(context.Background()); err != nil {
			log.Printf("unable to flush telemetry: %v", err)
		}
	}()

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", healthHandler)
	mux.HandleFunc("GET /inventory/{sku}", inventoryHandler)

	server := &http.Server{
		Addr:              ":8082",
		Handler:           recoveryMiddleware(mux),
		ReadHeaderTimeout: 5 * time.Second,
	}

	log.Printf("%s running on %s; OTLP endpoint=%s", serviceName, server.Addr, otlpEndpoint)
	log.Fatal(server.ListenAndServe())
}

func configureTracing() (func(context.Context) error, error) {
	client := otlptracehttp.NewClient(
		otlptracehttp.WithEndpoint(strings.TrimPrefix(strings.TrimPrefix(otlpEndpoint, "http://"), "https://")),
		otlptracehttp.WithInsecure(),
	)
	exporter, err := otlptracehttp.New(context.Background(), client)
	if err != nil {
		return nil, err
	}

	res, err := resource.Merge(
		resource.Default(),
		resource.NewWithAttributes(
			"",
			semconv.ServiceName(serviceName),
			semconv.ServiceVersion("1.0.0-demo"),
			attribute.String("service.namespace", "prism-demo"),
			attribute.String("deployment.environment.name", environment),
			attribute.String("prism.project.name", projectName),
			attribute.String("prism.repository.url", repositoryURL),
			attribute.String("prism.repository.branch", repositoryBranch),
			attribute.String("prism.demo.service", serviceName),
		),
	)
	if err != nil {
		return nil, err
	}

	provider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(provider)
	return provider.Shutdown, nil
}

func healthHandler(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "healthy", "service": serviceName})
}

func inventoryHandler(w http.ResponseWriter, r *http.Request) {
	sku := r.PathValue("sku")
	scenario := r.URL.Query().Get("scenario")
	if scenario == "" {
		scenario = "success"
	}

	ctx, span := tracer.Start(r.Context(), "inventory.lookup")
	defer span.End()
	span.SetAttributes(
		attribute.String("inventory.sku", sku),
		attribute.String("prism.demo.scenario", scenario),
		attribute.Bool("prism.demo.intentional", true),
	)

	if scenario == "success" {
		writeJSON(w, http.StatusOK, map[string]any{"sku": sku, "available": 4})
		return
	}

	err := runScenario(scenario, sku)
	if err == nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{
		"error": "scenario must be one of success, upstream-timeout, nil-pointer, panic, or critical",
		})
		return
	}

	span.RecordError(err)
	span.SetAttributes(attribute.String("error.type", fmt.Sprintf("%T", err)))
	emitOTLPError(ctx, err, scenario, sku)

	status := http.StatusInternalServerError
	if scenario == "upstream-timeout" {
		status = http.StatusGatewayTimeout
	}
	writeJSON(w, status, map[string]string{"error": err.Error(), "scenario": scenario})
}

func runScenario(scenario, sku string) error {
	switch scenario {
	case "upstream-timeout":
		return &inventoryError{
			scenario: scenario,
			message: fmt.Sprintf("warehouse availability API timed out after 20s for SKU %s", sku),
		}
	case "nil-pointer":
		return &inventoryError{
			scenario: scenario,
			message: fmt.Sprintf("inventory cache returned nil product record for SKU %s", sku),
		}
	case "panic":
		panic(fmt.Sprintf("inventory cache corruption for SKU %s", sku))
	case "critical":
		return &inventoryError{
			scenario: scenario,
			message: fmt.Sprintf("negative inventory committed for SKU %s; oversell prevention failed", sku),
		}
	default:
		return nil
	}
}

// emitOTLPError sends a standard OTLP/JSON LogsData request. The collector adds
// the project authorization key when forwarding it to PRISM.
func emitOTLPError(ctx context.Context, err error, scenario, sku string) {
	spanContext := traceIDFromContext(ctx)
	attributes := []otlpAttribute{
		stringAttribute("exception.type", fmt.Sprintf("%T", err)),
		stringAttribute("exception.message", err.Error()),
		stringAttribute("exception.stacktrace", string(debug.Stack())),
		stringAttribute("logger.name", "prism.demo.go.inventory"),
		stringAttribute("prism.demo.scenario", scenario),
		stringAttribute("prism.demo.intentional", "true"),
		stringAttribute("inventory.sku", sku),
		stringAttribute("http.route", "/inventory/{sku}"),
		stringAttribute("http.request.method", "GET"),
	}
	if scenario == "upstream-timeout" {
		attributes = append(attributes, stringAttribute("error.kind", "timeout"))
	}

	payload := otlpLogsPayload{
		ResourceLogs: []otlpResourceLogs{{
			Resource: otlpResource{Attributes: demoResourceAttributes()},
			ScopeLogs: []otlpScopeLogs{{
				Scope: otlpScope{Name: "prism.demo.go.inventory"},
				LogRecords: []otlpLogRecord{{
					TimeUnixNano:  fmt.Sprintf("%d", time.Now().UnixNano()),
					SeverityNumber: 17,
					SeverityText:   "ERROR",
					Body:           otlpValue{StringValue: err.Error()},
					Attributes:     attributes,
					TraceID:        spanContext.traceID,
					SpanID:         spanContext.spanID,
				}},
			}},
		}},
	}

	data, marshalErr := json.Marshal(payload)
	if marshalErr != nil {
		log.Printf("unable to marshal OTLP error: %v", marshalErr)
		return
	}
	response, requestErr := http.Post(
		strings.TrimRight(otlpEndpoint, "/")+"/v1/logs",
		"application/json",
		bytes.NewReader(data),
	)
	if requestErr != nil {
		log.Printf("unable to export OTLP error: %v", requestErr)
		return
	}
	defer response.Body.Close()
	if response.StatusCode >= http.StatusMultipleChoices {
		log.Printf("collector rejected OTLP error: %s", response.Status)
	}
}

func demoResourceAttributes() []otlpAttribute {
	return []otlpAttribute{
		stringAttribute("service.name", serviceName),
		stringAttribute("service.version", "1.0.0-demo"),
		stringAttribute("service.namespace", "prism-demo"),
		stringAttribute("deployment.environment.name", environment),
		stringAttribute("prism.project.name", projectName),
		stringAttribute("prism.repository.url", repositoryURL),
		stringAttribute("prism.repository.branch", repositoryBranch),
		stringAttribute("prism.demo.service", serviceName),
	}
}

type traceContext struct{ traceID, spanID string }

func traceIDFromContext(ctx context.Context) traceContext {
	spanContext := otel.SpanFromContext(ctx).SpanContext()
	if !spanContext.IsValid() {
		return traceContext{}
	}
	return traceContext{
		traceID: spanContext.TraceID().String(),
		spanID:  spanContext.SpanID().String(),
	}
}

func recoveryMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil {
				err := errors.New(fmt.Sprintf("unexpected Go panic: %v", recovered))
				emitOTLPError(r.Context(), err, "panic", r.PathValue("sku"))
				writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func writeJSON(w http.ResponseWriter, status int, response any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(response)
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

type otlpLogsPayload struct {
	ResourceLogs []otlpResourceLogs `json:"resourceLogs"`
}
type otlpResourceLogs struct {
	Resource  otlpResource    `json:"resource"`
	ScopeLogs []otlpScopeLogs `json:"scopeLogs"`
}
type otlpResource struct {
	Attributes []otlpAttribute `json:"attributes"`
}
type otlpScopeLogs struct {
	Scope      otlpScope       `json:"scope"`
	LogRecords []otlpLogRecord `json:"logRecords"`
}
type otlpScope struct {
	Name string `json:"name"`
}
type otlpLogRecord struct {
	TimeUnixNano  string          `json:"timeUnixNano"`
	SeverityNumber int             `json:"severityNumber"`
	SeverityText   string          `json:"severityText"`
	Body           otlpValue       `json:"body"`
	Attributes     []otlpAttribute `json:"attributes"`
	TraceID        string          `json:"traceId,omitempty"`
	SpanID         string          `json:"spanId,omitempty"`
}
type otlpAttribute struct {
	Key   string    `json:"key"`
	Value otlpValue `json:"value"`
}
type otlpValue struct {
	StringValue string `json:"stringValue"`
}

func stringAttribute(key, value string) otlpAttribute {
	return otlpAttribute{Key: key, Value: otlpValue{StringValue: value}}
}
