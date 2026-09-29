# OpenPipeline: Extracting Fields from Payment Logs

## The problem

The astroshop `paymentservice` logs every transaction it processes. The log arrives in Dynatrace as a structured record, but the commercially important details — order ID, currency, amount, payment provider, and outcome — are buried inside the message string. You can read them, but you cannot filter by them, aggregate them, or alert on them without parsing the string every time in a query.

OpenPipeline can do this parsing once, at ingest, and promote those values into top-level fields. After that, every query, dashboard, and alert in Dynatrace can use `payment.currency` or `payment.amount` directly — just like any other attribute.

## Look at a raw log first

Before writing an extraction rule, inspect what the `paymentservice` is actually logging.

In the Dynatrace **Kubernetes** app, navigate to your cluster → **Namespaces** → `astroshop` → `paymentservice`. Open the workload logs and expand a record. Look at the `content` field — this is the raw log message before any extraction.

A typical payment log looks like this:

```
PaymentService#charge invoked: amount=36.99 currency=USD orderId=a3f9c1b2 provider=stripe result=success
```

The fields you want to promote to attributes are:

| Field in message | Target attribute |
|---|---|
| `amount` | `payment.amount` |
| `currency` | `payment.currency` |
| `orderId` | `payment.order_id` |
| `provider` | `payment.provider` |
| `result` | `payment.result` |

!!! tip "Your logs may look different"
    The exact message format depends on the version of astroshop deployed. Spend a minute reading a few raw records before configuring the extraction — the pattern you write needs to match what is actually there, not what the documentation says should be there.

## Create the OpenPipeline pipeline

### 1. Open OpenPipeline

In Dynatrace, search for **OpenPipeline** or navigate to **Settings** → **Process and Contextualize** → **Logs**.

Click the **Pipelines** tab, then **+ Pipeline**. Name it `astroshop - Payment Enrichment`.

### 2. Add a Field Extraction processor

Expand the **Processors** drawer and click **+ Add**, then select **Field Extraction**.

Give it a descriptive name: `Extract payment fields`.

**Matching condition** — scope this processor to payment logs only:

```
matchesValue(k8s.namespace.name, "astroshop") and matchesValue(k8s.container.name, "paymentservice")
```

**Expression** — use the `parse` function with a pattern that matches the message structure you observed. For the example format above:

```
parse(content, "LD 'amount=' DOUBLE:payment.amount ' currency=' WORD:payment.currency ' orderId=' WORD:payment.order_id ' provider=' WORD:payment.provider ' result=' WORD:payment.result")
```

!!! info "Reading parse patterns"
    `LD` skips any leading text before the first anchor. `DOUBLE` captures a decimal number, `WORD` captures a sequence of non-space characters. Each capture is followed by a colon and the target field name. Dynatrace's [parse function reference](https://docs.dynatrace.com/docs/platform/grail/dynatrace-query-language/functions/dql-functions-parse) covers the full pattern syntax.

**Sample log** — paste one of the raw payment records into the sample input box. Run the preview and confirm the five fields appear in the output before saving.

Click **Save**.

### 3. Add a Dynamic Route

The pipeline exists but nothing is flowing through it yet. Open the **Dynamic Routing** tab and click **+ Dynamic Route**.

| Setting | Value |
|---|---|
| Name | `astroshop payment logs` |
| Matching condition | `matchesValue(k8s.namespace.name, "astroshop") and matchesValue(k8s.container.name, "paymentservice")` |
| Pipeline | `astroshop - Payment Enrichment` |

Save and confirm.

!!! warning "Dynamic routes apply to new records only"
    Records that arrived before the route was created are already stored and will not be reprocessed. Give it a minute for new payment logs to come through, then query.

## Verify the result

Open the Log Viewer and filter to the `paymentservice`. Open a recent record. The extracted fields should appear alongside the standard Kubernetes attributes:

- `payment.amount`
- `payment.currency`
- `payment.order_id`
- `payment.provider`
- `payment.result`

Once those fields exist as first-class attributes, they are queryable, filterable, and available in dashboards without any parsing in the query itself.

## What you can do with extracted fields

**Filter to failed payments in the Log Viewer:**
Select `payment.result = failed` from the filter bar.

**Count transactions by provider and outcome:**
```
fetch logs
| filter isNotNull(payment.provider)
| summarize count(), by: {payment.provider, payment.result}
```

**Find the largest transactions:**
```
fetch logs
| filter isNotNull(payment.amount)
| sort toDouble(payment.amount) desc
| limit 10
| fields timestamp, payment.order_id, payment.amount, payment.currency, payment.provider
```

**Alert on payment failures:**
With `payment.result` as a proper attribute, a Log Metric or custom alert can fire when `payment.result = "failed"` exceeds a threshold — no string matching required.

## Troubleshooting

### The preview shows no extracted fields

The parse pattern did not match the sample log. Check:

- Is the anchor text (`'amount='`) exactly what appears in the log, including case and spacing?
- Does the log use a different separator between fields (comma, pipe) rather than spaces?
- Is the `content` field the right source, or are the values nested inside a `body` subfield?

Adjust the pattern against the real log text until the preview shows the expected output.

### Some records extract correctly, others do not

The payment service may log different message formats for different outcomes (a successful charge versus a declined card versus a currency conversion error). You have two options:

- Add a second Field Extraction processor in the same pipeline with a different pattern and a more specific matching condition, so each format is handled separately.
- Use a more permissive pattern with optional segments, marking optional fields with `[...]` in the parse expression.

### Fields appear in preview but not in stored records

Confirm the Dynamic Route is active and its matching condition evaluates to true for the records you are inspecting. Open a stored record and check whether the `dt.openpipeline.id` attribute names your pipeline — this confirms the record was routed through it.

## Lab exercise

**Goal:** promote payment fields from a buried message string into queryable attributes using OpenPipeline, then use those attributes without writing a parse expression in any query.

1. In the Kubernetes app, open the `paymentservice` logs. Read five records and note the exact format of the message string — the anchor words, separators, and field order.

2. In OpenPipeline, create the `astroshop - Payment Enrichment` pipeline and add the Field Extraction processor. Use the sample input box to test your pattern against a real record before saving.

3. Create the Dynamic Route and wait for new records to arrive (about one minute).

4. Open a new `paymentservice` log record. Confirm `payment.result`, `payment.provider`, and `payment.amount` are present as attributes.

5. Use the Log Viewer filter bar (not a query) to show only records where `payment.result = failed`. How many are there in the last 30 minutes?

6. Navigate to one of the failed payment records. Click its `trace_id` to open the correlated trace. Is the failure visible as an error span?

7. Build a query that summarizes total transaction value by currency for the last hour. Because `payment.amount` is extracted as a string, you will need `toDouble()` — but you write that once here, not in every future query.

    ```
    fetch logs
    | filter isNotNull(payment.amount)
    | summarize total = sum(toDouble(payment.amount)), by: {payment.currency}
    ```

**Checkpoint:** `payment.result`, `payment.provider`, and `payment.amount` appear as attributes on new `paymentservice` records, and you can filter and aggregate on them from the Log Viewer without writing a parse expression.
