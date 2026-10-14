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

- Before the first `go get`, copy `go.mod` and `go.sum` aside, for example to `/tmp/<service>.go.mod` and `/tmp/<service>.go.sum`.
- For each guide package, run `go get <module>@<version>` inside the service's module directory.
- Then run the guide's `lockfile_refresh` (`go mod tidy`), so `go.sum` matches.
- If `go get` raises the `go` or `toolchain` line in `go.mod` (it prints `upgraded go`, `added toolchain` or `upgraded toolchain`), or fails with `requires go >=`, stop. Tell the user which module needs which Go version, and ask whether to keep the raised line. If they decline, copy both files back, so `go.mod` and `go.sum` are as they were before `go get`. Never raise the `go` line or the toolchain as a side effect.

## The setup file

- Write the guide's file (`telemetry.go`) in the entrypoint's package directory. Set its `package` clause to that package, usually `main`, so `main()` can call it, even when the guide's `path_hint` points at the module root. Say so in the report when the file lands away from its `path_hint`, and on a re-run, look for it in the entrypoint's package directory.
- Its `load` is `call_in_main`. The guide's second `call_in_main` file, whose `path_hint` is a place in `func main()`, is the call. Paste its contents as they are, as the first statements of `main()`; never write the call yourself. This call is the Go form of the first-import line, so it is a setup edit.
- Add each import the call's `path_hint` names, such as `context` or `log`, to the file that declares `main()`, when that file doesn't import it yet.
- If `main()` already declares a `ctx`, drop the call's `ctx :=` line, so `ctx` is never declared twice, and paste the rest of the call right after the line that declares `main()`'s `ctx`, so `ctx` exists before the call uses it.

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
