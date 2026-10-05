# Dynatrace Assist &mdash; AI-Created Dashboards, Notebooks & Alerts

### Use Dynatrace Assist's agentic AI to generate a Palo Alto focused dashboard, notebook, and alert &mdash; using nothing but a plain-English prompt.

## 1. Open Dynatrace Assist

1. From the left navigation, select **Dynatrace Assist** (the AI icon).

2. Make sure you are in **Agentic** mode &mdash; the toggle should show **Agent**, not **Chat**.


---

## 2. Create the Palo Alto Dashboard

Paste the following prompt into Dynatrace Assist exactly as written:

> **Can you help me create a Palo Alto log focused dashboard? I have a number of logs coming in for my Palo at the moment and want to surface the top talkers / issues and dropped traffic, also any trends we can pull out?**

Dynatrace Assist will:

1. Inspect your available log data and field schema.
2. Draft a set of DQL queries covering top source IPs, top destination IPs, top applications, action breakdown (allow / deny), dropped traffic volume over time, and byte throughput trends.
3. Propose a dashboard layout with tiles for each query.
4. Ask for confirmation before creating the dashboard.

!!! tip "Review before confirming"
    Read through the proposed tiles. If a query references a field you don't have (e.g. `pan.bytes_sent` vs `pan.bytes`), correct it in the chat before confirming.



---

## 3. Copy the DQL into a Dashboard

Dynatrace Assist generates the DQL queries and describes the layout, but the tiles need to be built manually in the **Dashboards** app. For each tile:

1. Open **Dashboards** from the left navigation and create a new dashboard.

2. Add a **DQL** tile.

3. Copy the DQL query from the Assist conversation and paste it into the tile editor.

4. Run the query and pick the visualisation type that best fits the data (bar chart for top talkers, pie for action breakdown, line/area for trends).

5. Tune as needed &mdash; adjust field names if your log schema differs, change the time range, or add a `| limit` to keep counts manageable.

6. Give the tile a clear title, then repeat for each query.

Suggested tiles and the DQL shape to start from:

| Tile | Visualisation | DQL starting point |
|---|---|---|
| Top Talkers &mdash; Source IP | Bar chart | `fetch logs \| filter appname == "PAN-OS" \| summarize count(), by: {pan.src_ip} \| sort count() desc \| limit 10` |
| Top Talkers &mdash; Destination IP | Bar chart | `fetch logs \| filter appname == "PAN-OS" \| summarize count(), by: {pan.dst_ip} \| sort count() desc \| limit 10` |
| Top Applications | Bar chart | `fetch logs \| filter appname == "PAN-OS" \| summarize count(), by: {pan.app} \| sort count() desc \| limit 10` |
| Allow vs Deny | Pie / single value | `fetch logs \| filter isNotNull(pan.action) \| summarize count(), by: {pan.action}` |
| Dropped Traffic Trend | Line / area | `fetch logs \| filter pan.action == "deny" \| makeTimeseries count(), interval: 5m` |
| Byte Throughput | Line / area | `fetch logs \| filter appname == "PAN-OS" \| makeTimeseries sum(toLong(pan.bytes)), interval: 5m` |

<!-- TODO: add screenshot of dashboard with all tiles populated -->

!!! info "Tile not populating?"
    Check the time picker &mdash; the default range may be narrower than your log retention window. Try **Last 2 hours** or **Last 6 hours**. If a field like `pan.bytes` is missing, check that the Parse CSV processor ran and that the log entry has a `TRAFFIC` subtype.

---

## 4. Generate a Notebook for Deeper Investigation

Back in Dynatrace Assist, prompt:

> **Can you create a notebook that lets me investigate the dropped traffic in more detail? I want to see which rules are triggering the most denies and which source/destination pairs are being blocked.**

The agent will create a notebook with annotated DQL sections covering:

- Deny count by rule name
- Blocked source/destination pairs
- Timeline of block events



---

## 5. Create an Alert for Dropped Traffic Spikes

Ask Dynatrace Assist to wire up a metric alert:

> **Can you set up an alert that fires if the number of denied firewall connections spikes significantly compared to the last hour's baseline?**

The agent will:

1. Create a DQL-backed metric or use an existing metric event.
2. Propose an anomaly detection condition.
3. Ask for confirmation before saving the alert configuration.


---

## What Dynatrace Assist Did Under the Hood

| Step | What happened |
|---|---|
| Field discovery | Assist queried your log schema to find available `pan.*` fields |
| Query generation | Wrote DQL for each tile based on your prompt |
| Layout generation | Arranged tiles into a logical dashboard structure |
| Notebook creation | Added explanatory markdown alongside each DQL block |
| Alert wiring | Mapped your intent to a metric anomaly detection rule |

!!! tip "Iterate naturally"
    You don't have to get the prompt perfect first time. Dynatrace Assist understands follow-up requests like *"add a tile for top destination ports"* or *"change the trend tile to show 24 hours"*.
