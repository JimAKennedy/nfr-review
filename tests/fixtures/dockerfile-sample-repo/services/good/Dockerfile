FROM golang:1.22.3@sha256:c4fb952e712efd8f787b3af5a92ce035011f30b8de3e9c0d17b6a8e2329c3874 AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /app ./cmd/server

FROM gcr.io/distroless/static:nonroot

COPY --from=builder /app /app

USER nonroot:nonroot

EXPOSE 8080
ENTRYPOINT ["/app"]
