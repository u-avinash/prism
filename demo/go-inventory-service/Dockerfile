FROM golang:1.22-alpine AS build

WORKDIR /src

COPY go.mod .
RUN go mod download

COPY main.go .
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/inventory-service .

FROM gcr.io/distroless/static-debian12

COPY --from=build /out/inventory-service /inventory-service

EXPOSE 8082

ENTRYPOINT ["/inventory-service"]
