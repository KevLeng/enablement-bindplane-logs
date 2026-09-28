# Logs in Context

## The problem

A microservices application like astroshop handles a single user request by calling half a dozen services in sequence. Each service logs what it did, but the logs land in separate pods, separate namespaces, and separate streams. When something goes wrong, the question is always the same: which logs belong to the request that failed?

Without coordination, the only tool you have is timestamps. You filter by time, guess which pod was involved, and hope the error message is specific enough to narrow it down. On a busy cluster, a narrow time window still returns hundreds of candidates.

**Logs in context** solves this by embedding the distributed trace identifier directly in every log line. Every log written during a request carries the `trace_id` and `span_id` of the span active at the time. Dynatrace uses this to stitch logs together automatically—across services, pods, and namespaces—without any manual query or join.

## How it works with astroshop

[Astroshop](https://opentelemetry.io/docs/demo/) is the OpenTelemetry community's reference demo application: a microservices e-commerce platform where every service is instrumented with the OpenTelemetry SDK. The SDK's log bridge automatically injects `trace_id` and `span_id` into log records at emit time. No application code changes are required.

The services write structured JSON logs to stdout. The **Dynatrace Kubernetes Operator** deploys OneAgent as a DaemonSet, which automatically discovers every pod on the node and collects its container logs. OneAgent parses `trace_id` and `span_id` from the JSON body and stores them as first-class attributes—making the correlation available everywhere in Dynatrace without any manual pipeline configuration.

## Orient yourself in the Kubernetes app

Before looking at logs, get a picture of what is running. Open the Dynatrace **Kubernetes** app and find your cluster.

### 1. Find your cluster

The Kubernetes app shows every cluster reporting to this Dynatrace tenant. Use the filter bar at the top to narrow it down to yours — your cluster is named after your assigned username (for example, `user05`).

Once filtered, select your cluster. The overview shows node health, workload status, and any active problems across the cluster.

### 2. Navigate to the astroshop namespace

Click **Namespaces** in the left panel and select `astroshop`. You will see all the workloads that make up the demo application — each one is a microservice.

### 3. Drill into a workload

Click on the `checkoutservice` workload. The detail view shows pod health, CPU and memory usage, and any active problems detected by OneAgent.

### 4. Open logs from the service

Click the **Logs** button in the workload detail view. The Log Viewer opens pre-filtered to logs from that service — Dynatrace already knows which pods belong to this workload and applies the filter automatically.

!!! tip "Logs are already there"
    The Kubernetes Operator deployed OneAgent as a DaemonSet, which is already collecting container logs from every pod in the cluster. The correlation to cluster, namespace, workload, and pod happens automatically at collection time — you did not have to configure any of it.

## From a log to a trace

Every log record from an OTel-instrumented service carries a `trace_id`. Dynatrace surfaces this as a clickable link directly in the Log Viewer.

Open a log record from the `checkoutservice`. In the attributes panel on the right, find the `trace_id` field. Click it — Dynatrace opens the correlated distributed trace directly.

The trace shows the full call graph for the request that produced the log: every service called, every span, and the time spent in each. Click the **Logs** tab within the trace to see every log record written across all services for that single request, stitched together in timeline order.

!!! info "How Dynatrace links logs to traces"
    Dynatrace reads `trace_id` at ingest time and uses it to join logs to spans. No query is needed — the link is built when the log arrives. OneAgent parses the field automatically from structured JSON logs.

## From a trace back to logs

The reverse path is equally direct. Open the **Distributed Traces** app and find any trace from the astroshop services. Click the **Logs** tab on the trace overview to see all logs for the full request, or click into an individual span and open its **Logs** tab to scope the view to just that span.

This makes it easy to answer questions like:

- Which service logged an error during this request?
- How many log records did the payment service write before the failure?
- Did the database call produce any warnings?

None of these require knowing a pod name or writing a filter — Dynatrace already knows which logs belong to which span.

## Troubleshooting

### `trace_id` is present but the link does not appear in the Log Viewer

Dynatrace correlates on `trace_id` using the W3C TraceContext format: 32 lowercase hex characters, no dashes. If the field arrives formatted differently (for example as a UUID with dashes), the correlation silently fails.

Open a log record and inspect the raw `trace_id` value. It should look like `4bf92f3577b34da6a3ce929d0e0e4736`, not `4bf92f35-77b3-4da6-a3ce-929d0e0e4736`.

### `trace_id` is absent from log records

| Symptom | Cause |
|---|---|
| Log body is plain text | Service uses a non-OTel logger — trace context cannot be injected without source changes |
| Body is JSON but `trace_id` is missing | OTel log bridge not initialized in the service |
| Field exists as `traceId` (camelCase) | Non-standard field name — the clickable link will not appear, but the field is still queryable |

## Lab exercise

**Goal:** follow a single user request in astroshop from service logs to the distributed trace and back, using only the Dynatrace UI.

1. Open the astroshop storefront and place an order.

2. In the Dynatrace **Kubernetes** app, filter to your cluster and navigate to **Namespaces** → `astroshop` → `checkoutservice`. Open the workload's logs.

3. Find a log record from around the time of your order. Open it and confirm the `trace_id` field is present in the attributes panel.

4. Click the `trace_id` to open the correlated trace. How many services are represented as spans in the trace?

5. In the trace view, click the **Logs** tab. You should see log records from multiple services for this single request. Which service produced the most log records?

6. Click into the span for `checkoutservice`. Open that span's **Logs** tab. How many log records were written during just that span?

7. Navigate back to the workload logs view. Find a record with a WARN or ERROR level. Click its `trace_id`. Does the trace show a failure span? Does the span's time range overlap with the log's timestamp?

8. Return to the `astroshop` namespace view. Pick a different workload — such as `productcatalogservice` — and open its logs. Open a record and follow its `trace_id` to the trace. Is the `checkoutservice` span present in the same trace?

**Checkpoint:** you can start from any astroshop service's logs, follow the trace link to see the full call graph, and scope logs to a specific span — all without writing a query or knowing which pod handled the request.

---

## Optional: from a user session to logs

If Real User Monitoring is enabled for the astroshop frontend, you can start the investigation from the user's perspective rather than from infrastructure.

Open the **Session Replay** or **User Sessions** app. Find a session where the user placed an order or encountered an error. From the session timeline, click on a user action (such as a button click or page load) to open the associated backend request.

Dynatrace links the frontend user action to the backend trace via the `dt.rum.session_id` and the injected trace context. From the backend trace, open the **Logs** tab to see every log record written across all services for that specific user interaction.

This gives you the full picture end to end:

```
User clicks "Place Order"
    → frontend user action (Session Replay)
        → backend distributed trace (Distributed Traces)
            → logs from every service that handled the request (Logs)
```

No ticket number, no pod name, no timestamp hunting — just follow the links.

!!! info "Prerequisite"
    The astroshop frontend must have the Dynatrace RUM JavaScript snippet injected, and the backend services must propagate the `traceparent` header so Dynatrace can correlate the frontend action to the backend trace.
