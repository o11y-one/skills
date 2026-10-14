---
title: Go
impact: HIGH
tags: [go, net-http, gin, echo, otelhttp, go-modules]
---

# Go

## Guide arguments

- `language`: `go`.
- `framework`: `net_http`, `gin` or `echo`, or `none` for a worker or a CLI.
- `service_name` and `service_namespace`: from [service-identity](service-identity.md).

## Install

- For each guide package, run `go get <module>@<version>` inside the service's module directory.
- Then run the guide's `lockfile_refresh` (`go mod tidy`), so `go.sum` matches.
- If `go get` raises the `go` or `toolchain` line in `go.mod` (it prints `upgraded go`, `added toolchain` or `upgraded toolchain`), or fails with `requires go >=`, stop. Tell the user which module needs which Go version, and that keeping a raised line is their call. Never raise the `go` line or the toolchain as a side effect.

## The setup file

- Write the guide's file (`telemetry.go`) in the entrypoint's package directory. Set its `package` clause to that package, usually `main`, so `main()` can call it, even when the guide's `path_hint` points at the module root. Say so in the report when the file lands away from its `path_hint`.
- Its `load` is `call_in_main`: call the setup function as the first statement of `main()`, and defer the shutdown it returns. This call is the Go form of the first-import line, so it is a setup edit.

```go
func main() {
	ctx := context.Background()
	shutdown, err := setupOTel(ctx)
	if err != nil {
		log.Fatal(err)
	}
	defer shutdown(ctx)

	// the rest of main, unchanged
}
```

The function's name and signature come from the guide's file; `setupOTel` is only an example.

## Handlers

- `net/http`: wrap the handler passed to the server with `otelhttp.NewHandler`, at the outermost level.
- gin: call `r.Use(otelgin.Middleware(<service name>))` before any route is registered.
- echo: call `e.Use(otelecho.Middleware(<service name>))` before the routes.

List the `main()` call and each of these changes in the report.

Outgoing HTTP carries the trace only through a client with `Transport: otelhttp.NewTransport(http.DefaultTransport)`.
Changing the app's clients is outside the setup edits, so ask the user first, and list it in the report.

[load-order](load-order.md#go) has the examples and the reasons.

## Run it for verify

1. Run the guide's `verify` commands, usually `go build ./...` and `go vet ./...`.
2. Build the main package to a temporary path, `go build -o /tmp/<service> ./<path to the main package>`, then run that binary with `.env` exported. Don't start `go run` in the background: stopping it leaves the program it built still running.
3. A worker or CLI that ends with `os.Exit` or `log.Fatal` skips the deferred shutdown and loses its buffered spans. Changing how `main` exits is outside the setup edits, so ask the user first. A server sends its spans while it runs, so this doesn't affect its verify.
