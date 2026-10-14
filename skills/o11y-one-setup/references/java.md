---
title: Java
impact: HIGH
tags: [java, spring-boot, javaagent, dockerfile, procfile, maven, gradle]
---

# Java

Java uses the OpenTelemetry Java agent. It needs no code changes and no new dependencies, only a jar and a JVM flag.

## Guide arguments

- `language`: `java`.
- `framework`: `spring` for Spring Boot, else `none`.
- `service_name` and `service_namespace`: from [service-identity](service-identity.md).

## The agent jar

- Get the jar exactly as the guide's `files` or `start_command` say. Never type a download URL or a version yourself.
- For a `Dockerfile`, download it during the image build, to a fixed path such as `/otel/opentelemetry-javaagent.jar`.
- For local runs, keep it at a path inside the service, and add that path to `.gitignore`. Never commit the jar.

## Where the flag goes

| The service starts with | Change |
| --- | --- |
| `java ... -jar app.jar` or `java ... <main class>` in a `Dockerfile`, `Procfile` or script | Insert `-javaagent:<jar path>` right after `java`, before `-jar` or the main class |
| A command you can't edit, such as a base image entrypoint or a buildpack | Append `-javaagent:<jar path>` to `JAVA_TOOL_OPTIONS`, keeping its current value |
| `./mvnw spring-boot:run` or `./gradlew bootRun`, for local runs | Don't edit the build file. For verify, run the built jar with the flag, as below |

The flag is a start-command flag, in a command or in `JAVA_TOOL_OPTIONS`, so it is a setup edit; list each place in the report.
Every start command from [detect](detect.md) gets the flag. One place missed means one environment with no traces.
[load-order](load-order.md#java) has the examples.

## Already there

These mean telemetry is already set up:
- a `-javaagent` flag or `JAVA_TOOL_OPTIONS` entry for another vendor (`dd-java-agent`, `newrelic.jar`, `elastic-apm-agent`, `applicationinsights-agent`);
- an existing OpenTelemetry agent;
- `io.opentelemetry` dependencies, such as `opentelemetry-spring-boot-starter`.

In each case, follow [partial-instrumentation](partial-instrumentation.md). Never remove what is there, and never add a second OpenTelemetry agent. If the user chooses to run ours alongside a vendor agent, put our flag after the vendor's.

## Run it for verify

1. Build with the project's wrapper, or `mvn` or `gradle` when it has none: `./mvnw -q package -DskipTests` or `./gradlew build -x test`.
2. Export `.env`, then run `java -javaagent:<local jar path> -jar <built jar>`. The built jar is the one in `target/` or `build/libs/` without `-plain` in its name. A start command that already has the flag works too, when its jar path exists here.
3. Never set `JAVA_TOOL_OPTIONS` around `./mvnw` or `./gradlew`. Maven and Gradle run on a JVM too, so the agent attaches to them, and their spans can arrive under this service's name.
4. The agent prints its version when it starts; if that line is missing, the flag didn't reach the JVM. Spring Boot's root span is the route, like `GET /orders`.

To debug a silent run, set `OTEL_JAVAAGENT_DEBUG=true`, which logs every span the agent creates.
