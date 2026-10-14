---
title: Agent frameworks
impact: HIGH
tags: [agents, langchain, langgraph, openai-agents, vercel-ai-sdk, crewai, llamaindex, openinference, gen-ai]
---

# Agent frameworks

An agent trace shows each run as a tree: the agent or chain at the root, with the model calls, tool calls and retrievals under it.

## Conventions

- Python and JavaScript agent frameworks are instrumented with OpenInference instrumentations, which write `llm.*`, `input.*`, `output.*` and `openinference.span.kind` attributes.
- The Vercel AI SDK writes its own `ai.*` attributes.
- o11y.one maps both onto the OpenTelemetry GenAI semantic conventions (`gen_ai.*`) when it ingests them, so model, token and tool fields line up across frameworks. Don't add a second GenAI instrumentation to get `gen_ai.*` names.

## Per framework

Pass `agent_framework` to `get_instrumentation_guide.v1`. When the agent runs inside a web service, pass `framework` too, in the same call.

| Framework | `agent_framework` | What you get | Watch for |
| --- | --- | --- | --- |
| LangChain, LangGraph | `langchain` | Chain, graph node, tool, retriever and model spans | The instrumentor must run before chains or graphs are built, so load the setup first, as its `load` value says |
| OpenAI Agents SDK | `openai_agents` | Agent, handoff, tool and model spans | The SDK's own tracing to OpenAI keeps running; leave its settings alone |
| Vercel AI SDK | `vercel_ai` | A span for each AI SDK call | It is opt-in per call; see below |
| CrewAI | `crewai` | Crew, agent, task and tool spans | The guide may answer `unsupported`; see below |
| LlamaIndex | `llamaindex` | Query, retrieval, synthesis, model and embedding spans | The same load rule as LangChain |

## Vercel AI SDK

1. The setup is the OpenTelemetry Node.js SDK from the guide, or `@vercel/otel` in `instrumentation.ts` for Next.js. Never use a browser SDK: these calls run on the server.
2. Add `experimental_telemetry: { isEnabled: true }` to each `generateText` and `streamText` call, and to any other AI SDK call the guide names. A call without it sends no span.
3. These edits are part of the setup. List every call site you changed in the report.

```ts
// BAD: no span for this call
const { text } = await generateText({ model, prompt })

// GOOD
const { text } = await generateText({ model, prompt, experimental_telemetry: { isEnabled: true } })
```

## When the guide says unsupported

The guide answers `unsupported` rather than name a package it hasn't confirmed, and CrewAI can get that answer.
When that happens:

1. Tell the user the guide's reason, word for word.
2. Never install a package the guide didn't list, whatever its name suggests.
3. Offer the manual route, and wait for a yes:
   - Call `get_instrumentation_guide.v1` again with the same `language` and `framework` but no `agent_framework`, and set up the plain SDK it returns.
   - Wrap the agent's entry call (`crew.kickoff()`, `agent.run()`, or the function the entrypoint calls) in a span with the OpenTelemetry API, so that each run arrives as one trace:

     ```python
     from opentelemetry import trace

     tracer = trace.get_tracer("agent")

     with tracer.start_as_current_span("crew.kickoff"):
         result = crew.kickoff()
     ```

   - The wrap is outside the setup edits, so it needs that yes. List it in the report.
   - Model calls inside the run appear as child spans only if the guide covered the model client.

## Content capture

- OpenInference captures prompts, completions, tool arguments and tool results by default: every `OPENINFERENCE_HIDE_*` setting defaults to false.
  - `OPENINFERENCE_HIDE_INPUTS=true` and `OPENINFERENCE_HIDE_OUTPUTS=true` turn it off.
  - Finer switches, such as `OPENINFERENCE_HIDE_INPUT_MESSAGES`, exist too.
- The Vercel AI SDK records inputs and outputs whenever telemetry is on. `recordInputs: false` and `recordOutputs: false` inside `experimental_telemetry` turn that off, per call.
- Don't change these defaults, and keep any value the repo already sets. In the report, tell the user that content is captured, and how to turn it off.

## Run it for verify

- An agent run calls its model provider, so it needs that provider's key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or the like) in the environment. If it isn't set, or holds a placeholder, never invent one: ask the user to run one task, then poll.
- A Python script agent that exits after one task still sends its spans, because the SDK flushes on exit.
- The root span is the agent, crew or chain run, or the request span when the agent runs inside a web service.
