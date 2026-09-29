# Static, CGO-free build (the SQLite driver is pure Go), so the runtime image needs nothing
# but CA certificates and a non-root user.
FROM golang:1.26-alpine AS build
WORKDIR /src

COPY gateway/go.mod gateway/go.sum ./
RUN go mod download

COPY gateway/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/gateway ./cmd/server

FROM alpine:3.20
RUN apk add --no-cache ca-certificates && adduser -D -u 10001 toothfairy
WORKDIR /app

COPY --from=build /out/gateway /usr/local/bin/gateway
# Demo accounts and cases, loaded idempotently on boot.
COPY assets/seed/ /app/seed/

USER toothfairy
EXPOSE 8081
ENTRYPOINT ["gateway"]
