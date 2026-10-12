#!/usr/bin/env python3
"""
Bindplane Lab - "Pipeline value" dashboard + lab-companion notebook.

Reuses the scoring rules from build_dashboards.py, so milestones stay in one place.
  python3 build_value.py
writes:
  bindplane-pipeline-value.json   (dashboard; Project selector with * for everyone)
  bindplane-lab-companion.json    (notebook; follow along step by step)
"""
import json
import uuid

from build_dashboards import (
    PAY_LOGS, Board, LAB_SIG, LOOKUP_MAP, MILESTONES, N, PROJ_PREP, SAMPLING_DROP_RATIO,
    dashboard, data, events, label, sampling_part, single, ind,
)

# --------------------------------------------------------------------------------------
# Project selector: multi-select, "*" = everyone, default = a placeholder that matches nobody
# --------------------------------------------------------------------------------------
PICK = "— pick a project —"
ALL = "*"


def sel(field="project"):
    return f'(in("{ALL}", array($Project)) or in({field}, array($Project)))'


P = sel()                 # for logs carrying `project`
PM = sel("m_project")     # for host-level metrics mapped through host.name -> project
LAB = f'({LAB_SIG[1:-1]} or receiver == "netflow")'
SOURCE = '''if(isNotNull(flow.type), "NetFlow",
    else: if(isNotNull(log.file.name), concat("File: ", log.file.name),
    else: if(isNotNull(appname), "Syslog", else: "Other")))'''
KEEP = round(SAMPLING_DROP_RATIO / (1 - SAMPLING_DROP_RATIO))  # 0.9 -> 9 dropped per 1 kept
SAMPLING = next(m for m in MILESTONES if m["kind"] == "proj_sampling")
STATE = ('if(startsWith(bch_ak, "BCHK"), "🔓 raw", else: if(stringLength(bch_ak) >= 64 and stringLength(bch_sk) >= 64, '
         '"🔒 hashed", else: "⚠️ partial"))')
MB = 1048576
OP_PARSED = 'isNotNull(syslog.severity)'
# Payments are keyed by the name in the Kubernetes cluster, not by project
PAYMENTS = PAY_LOGS + '''
| filter in("*", array($Cluster)) or in(participant, array($Cluster))'''
PAID = PAYMENTS + "\n| filter isNotNull(app.payment.transactionId)"


def project_var():
    return {
        "key": "Project", "type": "query", "visible": True, "editable": True, "multiple": True,
        "input": (f"fetch logs\n| filter isNotNull(project) and {LAB_SIG}\n"
                  "| summarize n = count(), by: { project }\n| fields project\n"
                  f'| append [ data record(project = "{ALL}"), record(project = "{PICK}") ]\n'
                  "| sort project asc"),
        "defaultValue": [PICK],
    }


def cluster_var():
    return {
        "key": "Cluster", "type": "query", "visible": True, "editable": True, "multiple": True,
        "input": (PAY_LOGS + "\n| summarize n = count(), by: { participant }\n| fields participant\n"
                  f'| append [ data record(participant = "{ALL}"), record(participant = "{PICK}") ]\n'
                  "| sort participant asc"),
        "defaultValue": [PICK],
    }


def host_metric(metric, agg, by_extra=(), extra=""):
    by = ", ".join(("host.name",) + tuple(by_extra))
    return f'''timeseries v = {agg}({metric}), by: {{ {by} }}
{LOOKUP_MAP}
| filter {PM}{extra}'''


def after_sampling():
    return f'''| lookup [
{ind(sampling_part(False, SAMPLING))}
], sourceField: project, lookupField: project, prefix: "s_"
| filter isNotNull(s_first_ts) and timestamp >= s_first_ts'''


def chart(title, q, viz="lineChart"):
    return data(title, q, viz)


# --------------------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------------------
def value_dashboard():
    b = Board()
    b.md(f"""# 🚀 What my Bindplane pipeline did
Pick one or more names in **Project** (or **`*`** for the whole class). The payments section has its own **Cluster** selector, because those logs come from your Kubernetes cluster, not through Bindplane. Every tile below is live data from the pipelines built in the lab: what you collected, how you shaped it at the edge, what you **didn't** have to send or store, and what Dynatrace can do with it once it lands.

| Stage | Bindplane did this at the edge | Why it matters |
|---|---|---|
| 🏷️ Label | `project` stamped on every record | find your data in a busy tenant with one filter |
| 🧩 Parse | 38 named `pan.*` fields from raw CSV | no regex at query time, faster dashboards and alerts |
| ✂️ Reduce | raw CSV removed, routine traffic sampled | less to ship, ingest and store |
| 🔐 Mask | credentials hashed before leaving the host | secrets never reach any backend in clear text |
| 📈 Metrics | log events turned into a time series | cheap, fast trend queries and alerting |
| 🔎 OpenPipeline | syslog parsed **in Dynatrace on ingest** | no collector change needed, severity and fields for free |
| 💳 Business data | payment JSON turned into `app.payment.*` fields | revenue, card mix and loyalty straight from logs |""", h=9)

    # ---------------- KPIs ----------------
    b.md("## ⭐ Headline numbers")
    b.row([
        (single("Records shipped", f"fetch logs\n| filter {P} and {LAB}\n| summarize v = count()", "logs sent to Dynatrace"), 4),
        (single("Sources live", f"fetch logs\n| filter {P} and {LAB}\n| fieldsAdd source = {SOURCE}\n"
                                "| summarize v = countDistinct(source)", "file paths, syslog, NetFlow"), 4),
        (single("Firewall sessions parsed", f'fetch logs\n| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)\n'
                                            "| summarize v = count()", "turned into 38 named fields"), 4),
        (single("Firewall records dropped at the edge", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
{after_sampling()}
| summarize {{ a = countIf(pan.action == "allow"), o = countIf(pan.action != "allow") }}
| fields v = concat(toString(round(100.0 * a * {KEEP} / (a * {KEEP + 1} + o), decimals: 0)), "%")''',
                "since sampling started — every deny kept"), 4),
        (single("Secrets hashed", f'''fetch logs
| filter {P} and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")
{PROJ_PREP}
| filter stringLength(bch_ak) >= 64 and stringLength(bch_sk) >= 64 and not startsWith(bch_ak, "BCHK")
| summarize v = count()''', "records masked before leaving the host"), 4),
        (single("Exposed access keys", host_metric("log.exposed_bch_credentials.count", "sum", ["bch_access_key_id"],
                                                   ' and not startsWith(bch_access_key_id, "BCHK")')
                + "\n| summarize v = countDistinct(bch_access_key_id)", "distinct keys, counted from a metric"), 4),
    ], 3)
    b.row([
        (single("Raw CSV kept off the wire", f'''fetch logs
| filter {P} and appname == "PAN-OS"
| summarize {{
    raw_bytes = avg(if(contains(content, ",TRAFFIC,end,"), stringLength(content))),
    stripped = countIf(isNotNull(pan.action) and (isNull(content) or content == ""))
  }}
| fields v = concat(toString(round(raw_bytes * stripped / {MB}, decimals: 2)), " MB")''',
                "raw message deleted after parsing"), 6),
        (single("At this rate, per day", f'''fetch logs
| filter {P} and appname == "PAN-OS" and pan.action == "allow"
{after_sampling()}
| summarize {{ a = count(), st = min(s_first_ts), lt = max(timestamp) }}, by: {{ project }}
| fieldsAdd per_day = a * {KEEP} / ((lt - st) / 1m) * 1440
| summarize v = concat(toString(round(sum(per_day) / 1000000, decimals: 2)), " M")''',
                "routine firewall records you'd never pay to ingest"), 6),
        (single("Needle in a haystack", f'''fetch logs
| summarize {{ mine = countIf({P} and {LAB}), total = count() }}
| fields v = concat(toString(round(100.0 * mine / total, decimals: 2)), "% of the tenant")''',
                "your data, found with one label filter"), 6),
        (single("Collectors online now", host_metric("otelcol_process_memory_rss", "avg") +
                "\n| fieldsAdd live = isNotNull(arrayLast(v))\n| summarize v = countIf(live)", "reporting self-telemetry"), 6),
    ], 3)

    # ---------------- What you're sending ----------------
    b.md("## 📥 What I'm sending")
    b.row([
        (chart("Records per minute by source", f'''fetch logs
| filter {P} and {LAB}
| fieldsAdd source = {SOURCE}
| makeTimeseries records = count(), by: {{ source }}, interval: 1m'''), 16),
        (chart("Share by source", f'''fetch logs
| filter {P} and {LAB}
| fieldsAdd source = {SOURCE}
| summarize records = count(), by: {{ source }}
| sort records desc''', "categoricalBarChart"), 8),
    ], 7)

    # ---------------- Labels ----------------
    b.md("## 🏷️ Labels — one field makes the data findable")
    b.row([(data("Who sent what (use * to see the class)", f'''fetch logs
| filter {P} and {LAB}
| fieldsAdd source = {SOURCE}
| summarize {{ records = count(), sources = countDistinct(source), first_seen = min(timestamp), last_seen = max(timestamp) }}, by: {{ project }}
| sort records desc''', "table"), 24)], 5)

    # ---------------- Parsing ----------------
    b.md("## 🧩 Parsing — the same firewall log, raw vs structured")
    b.row([
        (data("Raw, as it arrives (one long CSV string)", f'''fetch logs
| filter {P} and appname == "PAN-OS" and contains(content, ",TRAFFIC,end,") and isNull(pan.action)
| sort timestamp desc
| limit 10
| fields timestamp, project, content''', "table"), 12),
        (data("Structured by Bindplane (named fields, no regex)", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
| sort timestamp desc
| limit 10
| fields timestamp, project, pan.action, pan.app, pan.src_user, pan.src_ip, pan.dst_ip, pan.dst_port, pan.bytes, pan.session_end_reason''',
              "table"), 12),
    ], 6)
    b.row([
        (chart("Dynatrace: parsed at query time (schema on read)", f'''fetch logs
| filter {P} and appname == "PAN-OS" and contains(content, ",TRAFFIC,end,")
| fieldsAdd action = splitString(content, ",")[31]
| summarize sessions = count(), by: {{ action }}
| sort sessions desc''', "categoricalBarChart"), 8),
        (chart("Bindplane: parsed at the edge (field already there)", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
| summarize sessions = count(), by: {{ action = pan.action }}
| sort sessions desc''', "categoricalBarChart"), 8),
        (chart("How sessions ended", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
| summarize sessions = count(), by: {{ reason = pan.session_end_reason }}
| sort sessions desc''', "categoricalBarChart"), 8),
    ], 6)
    b.row([
        (chart("Top apps by traffic (MB)", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
| summarize mb = round(sum(toLong(pan.bytes)) / {MB}, decimals: 1), by: {{ app = pan.app }}
| sort mb desc
| limit 10''', "categoricalBarChart"), 8),
        (chart("Busiest users", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.src_user) and pan.src_user != ""
| summarize sessions = count(), by: {{ user = pan.src_user }}
| sort sessions desc
| limit 10''', "categoricalBarChart"), 8),
        (chart("What got blocked, by rule", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action) and pan.action != "allow"
| summarize sessions = count(), by: {{ rule = pan.rule_name, action = pan.action }}
| sort sessions desc
| limit 10''', "categoricalBarChart"), 8),
    ], 6)
    b.row([
        (data("Zone to zone traffic", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
| summarize {{ sessions = count(), mb = round(sum(toLong(pan.bytes)) / {MB}, decimals: 1),
    denied = countIf(pan.action != "allow") }}, by: {{ from_zone = pan.src_zone, to_zone = pan.dst_zone }}
| sort mb desc''', "table"), 12),
        (chart("Top destination ports", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.dst_port)
| summarize sessions = count(), by: {{ port = pan.dst_port, app = pan.app }}
| sort sessions desc
| limit 10''', "categoricalBarChart"), 12),
    ], 6)

    # ---------------- Reduction ----------------
    b.md("## ✂️ Volume reduction — keep every deny, sample the routine")
    b.row([
        (chart("Firewall records per minute — allow vs deny/drop/reset", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
| makeTimeseries {{ allow = countIf(pan.action == "allow"), deny_drop_reset = countIf(pan.action != "allow") }}, interval: 1m'''), 12),
        (chart("Allow share (%) — drops from ~93% when sampling starts", f'''fetch logs
| filter {P} and appname == "PAN-OS" and isNotNull(pan.action)
| makeTimeseries {{ allow = countIf(pan.action == "allow"), total = count() }}, by: {{ project }}, interval: 1m
| fieldsAdd allow_share_pct = 100 * allow[] / total[]
| fields timeframe, interval, project, allow_share_pct'''), 12),
    ], 7)
    b.row([(chart("Raw CSV bytes per minute — gone after Delete Fields", f'''fetch logs
| filter {P} and appname == "PAN-OS"
| fieldsAdd raw_bytes = if(isNotNull(content), stringLength(content), else: 0)
| makeTimeseries raw = sum(raw_bytes), by: {{ project }}, interval: 1m
| fieldsAdd kb = raw[] / 1024
| fields timeframe, interval, project, kb'''), 24)], 6)

    # ---------------- Masking ----------------
    b.md("## 🔐 Masking — leaked cloud credentials, hashed in flight")
    b.row([
        (chart("Credential records per minute — raw vs hashed", f'''fetch logs
| filter {P} and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")
{PROJ_PREP}
| fieldsAdd state = {STATE}
| makeTimeseries records = count(), by: {{ state }}, interval: 1m'''), 12),
        (data("Before vs after the redaction rollout", f'''fetch logs
| filter {P} and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")
{PROJ_PREP}
| fieldsAdd state = {STATE}
| summarize {{ records = count(), first_seen = min(timestamp), last_seen = max(timestamp) }}, by: {{ project, state }}
| sort project asc, first_seen asc''', "table"), 12),
    ], 6)
    b.row([(data("Latest credential records — what actually reached Dynatrace", f'''fetch logs
| filter {P} and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")
{PROJ_PREP}
| fieldsAdd state = {STATE}
| sort timestamp desc
| limit 15
| fields timestamp, project, state, content''', "table"), 24)], 6)

    # ---------------- Logs to metrics ----------------
    b.md("## 📈 Logs → metrics — impact assessment without scanning logs")
    b.row([
        (chart("Exposed credential sightings over time (metric)",
               host_metric("log.exposed_bch_credentials.count", "sum", ["bch_access_key_id"])
               + "\n| fields timeframe, interval, bch_access_key_id, v"), 12),
        (data("Same answer, two ways — log scan vs metric", f'''fetch logs
| filter {P} and isNotNull(bch_access_key_id)
| summarize from_logs = count(), by: {{ bch_access_key_id }}
| lookup [
{ind(host_metric("log.exposed_bch_credentials.count", "sum", ["bch_access_key_id"])
     + chr(10) + "| fieldsAdd t = arraySum(v)" + chr(10)
     + "| summarize from_metric = sum(t), by: { bch_access_key_id }")}
], sourceField: bch_access_key_id, lookupField: bch_access_key_id, prefix: "m_"
| fields hashed_access_key = bch_access_key_id, from_logs, from_metric = m_from_metric
| sort from_logs desc''', "table"), 12),
    ], 7)

    # ---------------- NetFlow ----------------
    b.md("## 🌐 NetFlow — who is talking to whom")
    NF = f'{P} and receiver == "netflow"'
    b.row([
        (chart("NetFlow bytes per minute (MB)", f'''fetch logs
| filter {NF}
| makeTimeseries b = sum(flow.io.bytes), by: {{ protocol = network.transport }}, interval: 1m
| fieldsAdd mb = b[] / {MB}
| fields timeframe, interval, protocol, mb'''), 12),
        (chart("Top destination ports by bytes", f'''fetch logs
| filter {NF}
| summarize mb = round(sum(flow.io.bytes) / {MB}, decimals: 1), by: {{ port = destination.port }}
| sort mb desc
| limit 10''', "categoricalBarChart"), 12),
    ], 6)
    b.row([
        (data("Top talkers", f'''fetch logs
| filter {NF}
| summarize {{ flows = count(), mb = round(sum(flow.io.bytes) / {MB}, decimals: 1), packets = sum(flow.io.packets) }},
    by: {{ source = source.address, destination = destination.address, port = destination.port }}
| sort mb desc
| limit 15''', "table"), 12),
        (chart("Traffic by source network (ASN)", f'''fetch logs
| filter {NF}
| summarize mb = round(sum(flow.io.bytes) / {MB}, decimals: 1), by: {{ source_asn = toString(flow.src_as) }}
| sort mb desc
| limit 10''', "categoricalBarChart"), 12),
    ], 6)

    # ---------------- Syslog & files ----------------
    b.md("## 🧾 Syslog streams and host files")
    b.row([
        (chart("Syslog records by application", f'''fetch logs
| filter {P} and isNotNull(appname)
| summarize records = count(), by: {{ appname }}
| sort records desc''', "categoricalBarChart"), 12),
        (chart("Log levels by source", f'''fetch logs
| filter {P} and {LAB}
| fieldsAdd source = {SOURCE}
| summarize records = count(), by: {{ source, loglevel }}
| sort records desc''', "categoricalBarChart"), 12),
    ], 6)

    # ---------------- OpenPipeline: syslog ----------------
    b.md("## 🔎 OpenPipeline — parsing in Dynatrace on ingest (host syslog file)")
    SYS = f'{P} and log.file.name == "syslog"'
    b.row([
        (chart("Syslog file records per minute — raw vs parsed by OpenPipeline", f'''fetch logs
| filter {SYS}
| fieldsAdd state = if({OP_PARSED}, "🔎 parsed by OpenPipeline", else: "📄 raw")
| makeTimeseries records = count(), by: {{ state }}, interval: 1m'''), 12),
        (chart("Severity found by OpenPipeline", f'''fetch logs
| filter {SYS}
| summarize records = count(), by: {{ loglevel }}
| sort records desc''', "categoricalBarChart"), 6),
        (data("Which OpenPipeline pipeline handled my logs", f'''fetch logs
| filter {P} and {LAB}
| fieldsAdd pipeline = dt.openpipeline.pipelines[0], source = {SOURCE}
| summarize records = count(), by: {{ project, source, pipeline }}
| sort project asc, records desc''', "table"), 6),
    ], 6)
    b.row([
        (data("Raw syslog lines (before your pipeline)", f'''fetch logs
| filter {SYS} and not ({OP_PARSED})
| sort timestamp desc
| limit 10
| fields timestamp, project, loglevel, content''', "table"), 12),
        (data("Parsed by OpenPipeline (all fields it added)", f'''fetch logs
| filter {SYS} and {OP_PARSED}
| sort timestamp desc
| limit 10
| fieldsRemove "dt.*", "flow.*", "pan.*", deployment.environment, os.type''', "table"), 12),
    ], 6)

    # ---------------- OpenPipeline: payments ----------------
    b.md("## 💳 Business data from logs — astroshop payments (pick your name in **Cluster**)")
    b.row([
        (single("Payments decoded", PAID + "\n| summarize v = count()", "transactions with app.payment.* fields"), 6),
        (single("Revenue made visible", PAID + '''
| summarize total = sum(toDouble(app.payment.amount)), by: { app.payment.currencyCode }
| sort total desc
| limit 1
| fields v = concat(app.payment.currencyCode, " ", toString(round(total, decimals: 0)))''', "top currency, from plain log lines"), 6),
        (single("Average basket", PAID + '''
| summarize v = round(avg(toDouble(app.payment.amount)), decimals: 0)''', "units per transaction"), 6),
        (single("Extraction coverage", PAYMENTS + '''
| summarize { e = countIf(isNotNull(app.payment.transactionId)), t = count() }
| fields v = concat(toString(round(100.0 * e / t, decimals: 0)), "%")''', "of payment logs now carry fields"), 6),
    ], 3)
    b.row([
        (chart("Revenue per minute by currency", PAID + '''
| makeTimeseries revenue = sum(toDouble(app.payment.amount)), by: { app.payment.currencyCode }, interval: 1m'''), 12),
        (chart("Transactions by card type", PAID + '''
| summarize transactions = count(), by: { card = app.payment.cardType }
| sort transactions desc''', "categoricalBarChart"), 6),
        (chart("Transactions by loyalty tier", PAID + '''
| summarize transactions = count(), by: { tier = app.payment.loyaltyLevel }
| sort transactions desc''', "categoricalBarChart"), 6),
    ], 6)
    b.row([
        (data("Raw payment log (JSON in content)", PAYMENTS + '''
| filter isNull(app.payment.transactionId)
| sort timestamp desc
| limit 10
| fields timestamp, participant, content''', "table"), 12),
        (data("Extracted payment fields", PAID + '''
| sort timestamp desc
| limit 10
| fields timestamp, participant, app.payment.transactionId, app.payment.cardType,
    app.payment.amount, app.payment.currencyCode, app.payment.loyaltyLevel''', "table"), 12),
    ], 6)

    # ---------------- Collector self-telemetry ----------------
    b.md("## 🛠️ The collector watching itself (Bindplane self-telemetry)")
    b.row([
        (chart("Collector memory (MB)", host_metric("otelcol_process_memory_rss", "avg")
               + f"\n| fieldsAdd mb = v[] / {MB}\n| fields timeframe, interval, collector = m_project, mb"), 8),
        (chart("Collector CPU (% of one core)", host_metric("otelcol_process_cpu_seconds", "sum")
               + "\n| fieldsAdd cpu_pct = v[] / 60 * 100\n| fields timeframe, interval, collector = m_project, cpu_pct"), 8),
        (chart("Records accepted per receiver type", host_metric("otelcol_receiver_accepted_log_records", "sum", ["receiver"])
               + '\n| fieldsAdd receiver_type = splitString(receiver, "/")[0]'
               + "\n| fields timeframe, interval, series = concat(m_project, \" · \", receiver_type), v"), 8),
    ], 6)
    b.row([
        (chart("Sent to Dynatrace vs failed", host_metric("otelcol_exporter_sent_log_records", "sum")
               + "\n| fields timeframe, interval, collector = m_project, sent = v"
               + "\n| append [\n" + ind(host_metric("otelcol_exporter_send_failed_log_records", "sum")
                                       + "\n| fields timeframe, interval, collector = m_project, failed = v") + "\n]"), 12),
        (data("Busiest pipeline components (items per processor type)", host_metric(
            "otelcol_processor_incoming_items", "sum", ["processor"],
            ' and not startsWith(processor, "throughputmeasurement/") and not startsWith(processor, "snapshotprocessor")')
            + '''
| fieldsAdd processor_type = splitString(processor, "/")[0], items = arraySum(v)
| summarize items = sum(items), by: { collector = m_project, processor_type }
| sort items desc''', "table"), 12),
    ], 7)
    return dashboard(b, [project_var(), cluster_var()])


# --------------------------------------------------------------------------------------
# Notebook
# --------------------------------------------------------------------------------------
ME = "TonyStark"


def me_q(q):
    return q.replace("$Me", f'"{ME}"')


def notebook():
    sections = []

    def md(text):
        sections.append({"id": str(uuid.uuid4()), "type": "markdown", "markdown": text})

    def dql(q, viz="table"):
        sections.append({"id": str(uuid.uuid4()), "type": "dql", "showTitle": False,
                         "state": {"input": {"value": q, "timeframe": {"from": "now()-2h", "to": "now()"}},
                                   "visualization": viz, "visualizationSettings": {}}})

    change = f'// ✏️ change "{ME}" to your project name'
    md(f"""# 🧭 Bindplane Lab — companion notebook
Scroll through this notebook as you work through the lab. Each step says **what you just did**, **what should now be true in Dynatrace**, and gives you a query to **prove it**.

**Before you start:** every query below uses `"{ME}"`. Replace it with the project name you choose in step 3 (use exactly the same spelling everywhere). Until step 3 there is no project name yet, so steps 1–2 find you by your collector's host name instead.

Run a section with ▶ (or Shift + Enter). Timeframe is the last 2 hours; widen it if you started earlier.""")

    md("""## Step 1 — Install the collector and roll out the configuration
**You did:** installed the Bindplane collector, built a configuration with four sources (File, Syslog, NetFlow, Bindplane Collector) and a Dynatrace destination, and rolled it out.

**Now true:** logs from your Codespace are arriving. You don't have a label yet, so find your collector by its **host name** (your Codespace name). Lab traffic is the only data with `appname == "PAN-OS"` or the lab's file names.""")
    dql(f'''fetch logs, from: now()-10m
| filter {LAB_SIG}
| summarize records = count(), last_seen = max(timestamp), by: {{ host.name }}
| sort last_seen desc''')
    md("✅ **Success:** your Codespace name appears with a rising `records` count. ❌ Nothing? Check the collector's error logs in Bindplane (destination URL or token).")

    md("""## Step 2 — Cumulative to delta
**You did:** added the cumulative-to-delta processor to the Bindplane Collector source.

**Why:** Dynatrace accepts **delta** metrics over OTLP. The collector reports its own metrics as cumulative counters, so without this processor they are rejected. With it, your collector's self-telemetry starts flowing.""")
    dql('''timeseries rss = avg(otelcol_process_memory_rss), by: { host.name }, from: now()-30m
| fieldsAdd memory_mb = rss[] / 1048576
| fields timeframe, interval, host.name, memory_mb''', "lineChart")
    md("✅ **Success:** a line for your host name. ❌ No line after 2–3 minutes? Make sure the processor is on the Bindplane Collector source and the rollout finished.")

    md(f"""## Step 3 — Add a field: your project label
**You did:** added an **Add Fields** processor with `project = <your name>`.

**Why:** a busy tenant holds data from many teams. One consistent label lets you (and OpenPipeline, dashboards, alerts and permissions) find exactly your data with a single filter.""")
    dql(f'''fetch logs, from: now()-10m
| filter project == "{ME}"   {change}
| fieldsAdd source = {SOURCE}
| summarize records = count(), by: {{ source }}
| sort records desc''')
    md("✅ **Success:** rows for **Syslog**, **File: syslog / audit.log / fail2ban.log** and **NetFlow**. If a source is missing, check that Add Fields is on the processor node in front of the Dynatrace destination and that you rolled it out.")

    md("""## Step 4 — Parse CSV
**You did:** added **Parse CSV** to the Syslog source for PAN-OS `TRAFFIC,end` records.

**Why:** the firewall sends one long comma-separated string. Parsed at the edge, it arrives with 38 named `pan.*` fields, so every query, dashboard and alert can use them directly.

**Dynatrace can also parse at query time** (schema on read). Both answers below should match. The difference is that the first one re-parses every record on every query, and the second just reads a field.""")
    dql(f'''// Query-time parsing: works on raw records too
fetch logs, from: now()-30m
| filter project == "{ME}" and appname == "PAN-OS" and contains(content, ",TRAFFIC,end,")   {change}
| fieldsAdd action = splitString(content, ",")[31]
| summarize sessions = count(), by: {{ action }}''')
    dql(f'''// Edge parsing: the field is already there
fetch logs, from: now()-10m
| filter project == "{ME}" and appname == "PAN-OS" and isNotNull(pan.action)   {change}
| sort timestamp desc
| limit 5
| fieldsKeep timestamp, "pan.*"''')
    md("✅ **Success:** records with `pan.action`, `pan.app`, `pan.src_ip`… ❌ No `pan.*` fields? Check the two conditions (`appname` **equals** `PAN-OS`, `message` **contains** `,TRAFFIC,end,`) and that you rolled out.")

    md("""## Step 5 — Delete the raw message
**You did:** added **Delete Fields** to remove `body.message` from parsed records.

**Why:** after parsing, every record carried the same data twice: the raw CSV and the named fields. Dropping the raw copy cuts the size of every firewall record you ship and store.""")
    dql(f'''fetch logs, from: now()-15m
| filter project == "{ME}" and appname == "PAN-OS" and isNotNull(pan.action)   {change}
| fieldsAdd raw_csv = if(isNull(content) or content == "", "removed ✅", else: "still present")
| summarize records = count(), last_seen = max(timestamp), by: {{ raw_csv }}''')
    md("✅ **Success:** new records show **removed ✅** while `pan.*` fields are still there.")

    md("""## Step 6 — Sample routine traffic (drop ratio 0.9)
**You did:** added **Sample Logs** for `pan.action == "allow"` with a drop ratio of **0.9**.

**Why:** about 93% of firewall sessions are routine allows. Keeping 1 in 10 of those, and **every** deny/drop/reset, cuts volume sharply without losing what security analysts need.""")
    dql(f'''fetch logs, from: now()-30m
| filter project == "{ME}" and appname == "PAN-OS" and isNotNull(pan.action)   {change}
| makeTimeseries {{ allow = countIf(pan.action == "allow"), total = count() }}, interval: 1m
| fieldsAdd allow_share_pct = 100 * allow[] / total[]
| fields timeframe, interval, allow_share_pct''', "lineChart")
    md("✅ **Success:** the line drops from about **93%** to about **55–60%**. Denies are untouched; only routine allows are sampled.")

    md("""## Step 7 — Mask the leaked credentials
**You did:** added **Redact Sensitive Data** with hashing, and a **Routing** connector so only credential-bearing logs go through it.

**Why:** a deploy script put cloud keys on the command line, and `auditd` logged them. Hashing them at the edge means the secret never reaches any backend, but the same key still produces the same hash, so you can count and track exposures.""")
    dql(f'''fetch logs, from: now()-1h
| filter project == "{ME}" and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")   {change}
{PROJ_PREP}
| fieldsAdd state = {STATE}
| summarize records = count(), first_seen = min(timestamp), last_seen = max(timestamp), by: {{ state }}''')
    md("✅ **Success:** **🔓 raw** stops and **🔒 hashed** starts at your rollout time. ⚠️ **partial** means only one of the two regex rules matched.")

    md("""## Step 8 — Extract the access key
**You did:** added **Parse with Regex** to pull the (now hashed) access key into the `bch_access_key_id` attribute.""")
    dql(f'''fetch logs, from: now()-30m
| filter project == "{ME}" and isNotNull(bch_access_key_id)   {change}
| summarize sightings = count(), by: {{ bch_access_key_id }}''')
    md("✅ **Success:** long hex values, never anything starting with `BCHK`. If you see `BCHK…`, your regex runs **before** the masking: move it after.")

    md("""## Step 9 — Signal to metric
**You did:** added a **Signal to Metric** connector that counts each credential sighting as `log.exposed_bch_credentials.count`, split by the hashed key.

**Why:** "how many keys leaked, and how often, over the last week?" is a time-series question. A metric answers it instantly and cheaply, and can drive alerts, without scanning logs.""")
    dql('''timeseries sightings = sum(log.exposed_bch_credentials.count), by: { bch_access_key_id, host.name }, from: now()-1h
| fieldsAdd total = arraySum(sightings)''')
    md("✅ **Success:** one row per exposed (hashed) key on your host. Compare `total` with step 8: same answer, from a metric instead of a log scan.")

    md("""## Step 10 — Parse host syslog with OpenPipeline (finish line 🏁)
**You did:** created an OpenPipeline **pipeline** with the **Syslog technology bundle** (matching `log.file.name == "syslog"`), and a **dynamic route** sending logs with your `project` to it.

**Why:** not every parsing job belongs on the collector. OpenPipeline parses **in Dynatrace, on ingest**: no rollout to hosts, and the result is stored with the record. Your host syslog lines arrive with a real severity instead of `NONE`, plus `syslog.appname`, `syslog.proc_id`, `syslog.severity`, `syslog.facility` and `syslog.message`.""")
    dql(f'''fetch logs, from: now()-30m
| filter project == "{ME}" and log.file.name == "syslog"   {change}
| fieldsAdd state = if({OP_PARSED}, "🔎 parsed by OpenPipeline", else: "📄 raw")
| fieldsAdd pipeline = dt.openpipeline.pipelines[0]
| summarize records = count(), first_seen = min(timestamp), last_seen = max(timestamp), by: {{ state, pipeline }}''')
    dql(f'''fetch logs, from: now()-10m
| filter project == "{ME}" and log.file.name == "syslog" and {OP_PARSED}   {change}
| sort timestamp desc
| limit 5''')
    md("✅ **Success:** new records show **🔎 parsed by OpenPipeline** with `syslog.*` fields and your pipeline's name instead of `opp_default`. ❌ Still `opp_default`? Your route condition doesn't match: check `matchesValue(project, \"<yourname>\")` uses exactly your project name. ❌ Routed but still `NONE`? Check the bundle's matching condition is `matchesValue(log.file.name, \"syslog\")`.")

    md("""## 💳 Payment challenge — extract payment fields (separate leaderboard)
**You did:** added an **Add fields** processor to your pipeline that parses the astroshop payment JSON into `app.payment.*` fields.

**Why:** the payment service logs a JSON blob per transaction. Extracted on ingest, it becomes business data: revenue by currency, card mix, loyalty tiers, all queryable without touching the app.

These logs come from your Kubernetes cluster, not through Bindplane, so they don't carry `project`. They're scored on their own **Payment challenge** table, under the name in your cluster (`bindplane-logs-<name>-<date>`).""")
    dql('''fetch logs, from: now()-30m
| filter k8s.namespace.name == "astroshop" and matchesPhrase(content, "Transaction complete.")
| filter contains(k8s.cluster.name, "tony-stark")   // ✏️ change to part of your cluster name
| fieldsAdd state = if(isNotNull(app.payment.transactionId), "💳 extracted", else: "📄 raw JSON")
| summarize records = count(), first_seen = min(timestamp), last_seen = max(timestamp), by: { state }''')
    dql('''fetch logs, from: now()-30m
| filter k8s.namespace.name == "astroshop" and isNotNull(app.payment.transactionId)
| filter contains(k8s.cluster.name, "tony-stark")   // ✏️ change to part of your cluster name
| summarize transactions = count(), revenue = sum(toDouble(app.payment.amount)),
    by: { app.payment.cardType, app.payment.currencyCode }
| sort revenue desc''')
    md("✅ **Success:** **💳 extracted** records with card type, currency and amount. ❌ Nothing extracted? Check the route also matches your cluster (`k8s.cluster.name`) and the processor's condition matches namespace `astroshop`, container `payment`.")

    md("""## 🌐 Bonus — explore your NetFlow
NetFlow arrives as logs with structured `flow.*`, `source.*` and `destination.*` fields. Who is talking to whom?""")
    dql(f'''fetch logs, from: now()-30m
| filter project == "{ME}" and receiver == "netflow"   {change}
| summarize flows = count(), mb = round(sum(flow.io.bytes) / 1048576, decimals: 1),
    by: {{ source.address, destination.address, destination.port }}
| sort mb desc
| limit 10''')

    md("""## 🛠️ Bonus — your collector's health
Bindplane reports on itself: memory, CPU, records received and sent.""")
    dql('''timeseries accepted = sum(otelcol_receiver_accepted_log_records), by: { host.name, receiver }, from: now()-30m
| fieldsAdd receiver_type = splitString(receiver, "/")[0], total = arraySum(accepted)
| fields host.name, receiver_type, total''')

    md(f"""## ✅ My scorecard
Every milestone you have earned so far, from data that actually arrived in Dynatrace. Change `"{ME}"` to your name in the query (it appears several times: use find and replace).""")
    recs = ",\n  ".join(f'record(milestone = "{label(m)}")' for m in MILESTONES)
    dql(me_q(f'''data
  {recs}
| lookup [
{ind(events(me=True))}
], sourceField: milestone, lookupField: milestone, prefix: "e_"
| fieldsAdd status = if(isNull(e_first_ts), "⬜ Not yet", else: "✅ Done")
| fields milestone, status, achieved_at = e_first_ts'''))

    return {"version": "7", "defaultTimeframe": {"from": "now()-2h", "to": "now()"}, "sections": sections}


if __name__ == "__main__":
    for name, d in [("bindplane-pipeline-value.json", value_dashboard()),
                    ("bindplane-lab-companion.json", notebook())]:
        with open(name, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        n = len(d.get("tiles", d.get("sections", [])))
        print(f"wrote {name}: {n} {'tiles' if 'tiles' in d else 'sections'}")
