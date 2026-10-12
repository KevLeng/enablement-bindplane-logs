#!/usr/bin/env python3
"""
Bindplane Lab Race - dashboard generator.

Generates two Dynatrace dashboards from ONE milestone definition list:
  - bindplane-race-trainer.json      (leaderboard, prizes, who needs help)
  - bindplane-race-my-progress.json  (participant self-check with evidence)

To add a milestone (e.g. an OpenPipeline step), append an entry to MILESTONES
and re-run:  python3 build_dashboards.py

Milestone kinds
  host_first_log  first lab log seen from a collector host (pre-label; credited via host->project map)
  host_metric     first data point of a metric on a lab host (credited via host->project map)
  proj_log        first lab log for a project that satisfies `cond` (evaluated per record)
  proj_sampling   first minute where allow share < SAMPLING_MAX_SHARE with >= SAMPLING_MIN_RECORDS
  proj_metric     first data point of a metric that carries a `project` dimension
                  (use this for OpenPipeline metric extraction - keep `project` as a dimension)

Scoring principle: a milestone counts only when its EFFECT is visible in Dynatrace,
not when a component is merely configured. Bucket-based milestones (metrics, sampling)
are stamped at the END of the first qualifying minute, so nobody is credited early.
"""
import json

# --------------------------------------------------------------------------------------
# Lab signature: positive include filter (no exclude lists - the tenant changes)
# --------------------------------------------------------------------------------------
LAB_SIG = '(appname == "PAN-OS" or in(log.file.name, array("syslog", "audit.log", "fail2ban.log")))'

SAMPLING_MAX_SHARE = 0.80   # baseline ~93% allow; 0.9 drop ratio -> ~57%
SAMPLING_MIN_RECORDS = 30   # per minute, so a quiet minute can't trigger it

EXCLUDE_DEFAULT = ["MACK"]
SENTINEL = "— none —"       # lets the trainer deselect everyone without an empty selection

# Pre-processing applied once in the per-project log scan (credential parsing for masking)
PROJ_PREP = r'''| parse content, "LD 'BCH_ACCESS_KEY_ID=' NSPACE:bch_ak SPACE 'BCH_SECRET_ACCESS_KEY=' NSPACE:bch_sk"
| fieldsAdd bch_sk = replaceString(bch_sk, "\"", "")'''

MILESTONES = [
    dict(id="01", name="Pipeline live", kind="host_first_log",
         proof="First lab log (PAN-OS syslog or syslog/audit.log/fail2ban.log file) from your collector host"),
    dict(id="02", name="Cumulative to delta", kind="host_metric",
         metric="otelcol_process_memory_rss", agg="avg", by=[], cond="isNotNull(v[])",
         proof="Collector self-metrics reach Dynatrace (they are rejected until delta temporality)"),
    dict(id="03", name="Project tagged", kind="proj_log", cond="true",
         proof="First lab log carrying your project attribute"),
    dict(id="04", name="Parse CSV", kind="proj_log",
         cond='appname == "PAN-OS" and isNotNull(pan.action)',
         proof="PAN-OS records arrive with named pan.* fields"),
    dict(id="05", name="Delete body.message", kind="proj_log",
         cond='appname == "PAN-OS" and isNotNull(pan.action) and (isNull(content) or content == "")',
         proof="Parsed PAN-OS records arrive without the raw CSV"),
    dict(id="06", name="Sampling", kind="proj_sampling",
         proof=f"Allow share of parsed traffic drops below {int(SAMPLING_MAX_SHARE*100)}% (baseline ~93%)"),
    dict(id="07", name="Masking", kind="proj_log",
         cond='log.file.name == "audit.log" and isNotNull(bch_ak) and not startsWith(bch_ak, "BCHK") '
              'and stringLength(bch_ak) >= 64 and stringLength(bch_sk) >= 64',
         proof="BCH access key and secret arrive hashed (64+ hex chars), never raw"),
    dict(id="08", name="Parse regex", kind="proj_log",
         cond='isNotNull(bch_access_key_id) and not startsWith(bch_access_key_id, "BCHK")',
         proof="bch_access_key_id attribute extracted from the hashed value"),
    dict(id="09", name="Signal to metric", kind="host_metric",
         metric="log.exposed_bch_credentials.count", agg="sum", by=["bch_access_key_id"],
         pre_filter='isNotNull(bch_access_key_id) and not startsWith(bch_access_key_id, "BCHK")',
         cond="v[] > 0",
         proof="log.exposed_bch_credentials.count arrives with a hashed key dimension"),
    dict(id="10", name="OpenPipeline syslog", kind="proj_log",
         cond='log.file.name == "syslog" and isNotNull(syslog.severity)',
         proof="Host syslog records (file source) arrive with syslog.* fields from the OpenPipeline Syslog bundle"),
    # Example for later (OpenPipeline metric extraction that keeps `project` as a dimension):
    # dict(id="10", name="OpenPipeline metric", kind="proj_metric",
    #      metric="log.lab.some_metric", agg="sum", cond="v[] > 0",
    #      proof="Metric extracted by OpenPipeline arrives for your project"),
]

N = len(MILESTONES)


def label(m):
    return f'{m["id"]} {m["name"]}'


def ind(s, n=2):
    return "\n".join(" " * n + line for line in s.splitlines())


def appendq(q):
    return f"\n| append [\n{ind(q)}\n]"


# --------------------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------------------
# host.name -> project, using the project with the most records on that host
# (a host that briefly used a typo still maps to the name it settled on)
MAP = f'''fetch logs
| filter isNotNull(project) and isNotNull(host.name) and {LAB_SIG}
| summarize n = count(), by: {{ host.name, project }}
| sort n desc
| summarize project = takeFirst(project), by: {{ host.name }}'''

LOOKUP_MAP = f'''| lookup [
{ind(MAP)}
], sourceField: host.name, lookupField: host.name, prefix: "m_"'''


# --------------------------------------------------------------------------------------
# Payment challenge (separate from the race). Astroshop payment logs come from each
# participant's Kubernetes cluster, not through Bindplane, so they carry no `project`.
# They are keyed by the name inside the cluster: bindplane-logs-<name>-<yyyymmdd> -> <name>.
# --------------------------------------------------------------------------------------
ASTRO_NS = "astroshop"
CLUSTER_PREFIX = "bindplane-logs-"
_P = len(CLUSTER_PREFIX)
WHO = (f'if(startsWith(k8s.cluster.name, "{CLUSTER_PREFIX}") and stringLength(k8s.cluster.name) > {_P + 9}, '
       f'substring(k8s.cluster.name, from: {_P}, to: stringLength(k8s.cluster.name) - 9), else: k8s.cluster.name)')
PAY_LOGS = f'''fetch logs
| filter k8s.namespace.name == "{ASTRO_NS}" and matchesPhrase(content, "Transaction complete.")
| fieldsAdd participant = {WHO}'''
PAY_EXCL = "not in(participant, array($ExcludeCluster))"
PAY_DONE = "isNotNull(app.payment.transactionId)"
PAY_DEFAULT_EXCLUDE = ["amrith-raj"]


def exclude_cluster_var(visible=True):
    return {
        "key": "ExcludeCluster", "type": "query", "visible": visible, "editable": True, "multiple": True,
        "input": (PAY_LOGS + "\n| summarize n = count(), by: { participant }\n| fields participant\n"
                  '| append [ data record(participant = "— none —") ]\n| sort participant asc'),
        "defaultValue": PAY_DEFAULT_EXCLUDE,
    }


def payment_board():
    """One row per cluster name: who got payment field extraction working, and when."""
    return PAY_LOGS + f'''
| filter {PAY_EXCL}
| summarize {{
    payment_logs = count(),
    extracted = countIf({PAY_DONE}),
    first_seen = min(timestamp),
    first_extracted = min(if({PAY_DONE}, timestamp)),
    clusters = collectDistinct(k8s.cluster.name)
  }}, by: {{ participant }}
| fieldsAdd pending = if(isNull(first_extracted), 1, else: 0)
| fieldsAdd status = if(pending == 0, "✅ extracting", else: "⬜ not yet")
| fieldsAdd coverage_pct = round(100.0 * extracted / payment_logs, decimals: 0)
| sort pending asc, first_extracted asc'''


def bucket_first(cond):
    return (f"| fieldsAdd idx = arrayFirst(arrayRemoveNulls(iCollectArray(if({cond}, iIndex()))))\n"
            f"| filter isNotNull(idx)")


def host_part(me):
    parts = []
    for m in MILESTONES:
        if m["kind"] == "host_first_log":
            parts.append(f'''fetch logs
| filter isNotNull(host.name) and {LAB_SIG}
| summarize first_ts = min(timestamp), by: {{ host.name }}
| fields host.name, milestone = "{label(m)}", first_ts''')
        elif m["kind"] == "host_metric":
            by = ", ".join(["host.name"] + m.get("by", []))
            pf = f'\n| filter {m["pre_filter"]}' if m.get("pre_filter") else ""
            parts.append(f'''timeseries v = {m["agg"]}({m["metric"]}), by: {{ {by} }}, interval: 1m{pf}
{bucket_first(m["cond"])}
| fields host.name, milestone = "{label(m)}", first_ts = timeframe[start] + interval * (idx + 1)''')
    if not parts:
        return None
    q = parts[0] + "".join(appendq(p) for p in parts[1:])
    q += f"\n{LOOKUP_MAP}\n| filter isNotNull(m_project)\n| fields project = m_project, milestone, first_ts"
    if me:
        q += "\n| filter project == $Me"
    return q


def proj_log_part(me):
    pm = [m for m in MILESTONES if m["kind"] == "proj_log"]
    if not pm:
        return None
    mf = " and project == $Me" if me else ""
    aggs = ",\n    ".join(f'm{m["id"]} = min(if({m["cond"]}, timestamp))' for m in pm)
    recs = ",\n    ".join(f'record(milestone = "{label(m)}", first_ts = m{m["id"]})' for m in pm)
    return f'''fetch logs
| filter isNotNull(project){mf} and {LAB_SIG}
{PROJ_PREP}
| summarize {{
    {aggs}
  }}, by: {{ project }}
| fieldsAdd ev = array(
    {recs})
| expand ev
| fields project, milestone = ev[milestone], first_ts = ev[first_ts]
| filter isNotNull(first_ts)'''


def sampling_part(me, m):
    mf = " and project == $Me" if me else ""
    return f'''fetch logs
| filter isNotNull(project){mf} and appname == "PAN-OS" and isNotNull(pan.action)
| makeTimeseries {{ allow = countIf(pan.action == "allow"), total = count() }}, by: {{ project }}, interval: 1m
{bucket_first(f"total[] >= {SAMPLING_MIN_RECORDS} and allow[] / total[] < {SAMPLING_MAX_SHARE}")}
| fields project, milestone = "{label(m)}", first_ts = timeframe[start] + interval * (idx + 1)'''


def proj_metric_part(me, m):
    mf = " and project == $Me" if me else ""
    return f'''timeseries v = {m["agg"]}({m["metric"]}), by: {{ project }}, filter: {{ isNotNull(project){mf} }}, interval: 1m
{bucket_first(m["cond"])}
| fields project, milestone = "{label(m)}", first_ts = timeframe[start] + interval * (idx + 1)'''


def events(me=False):
    """Long format: one row per (project, milestone) with first_ts."""
    parts = [p for p in [host_part(me), proj_log_part(me)] if p]
    for m in MILESTONES:
        if m["kind"] == "proj_sampling":
            parts.append(sampling_part(me, m))
        elif m["kind"] == "proj_metric":
            parts.append(proj_metric_part(me, m))
    q = parts[0] + "".join(appendq(p) for p in parts[1:])
    q += "\n| summarize first_ts = min(first_ts), by: { project, milestone }"
    return q


EXCL = "not in(project, array($Exclude))"


# Milestones stamped to the second (log-based). Bucket-based ones are stamped to the minute,
# so `last_precise` breaks ties when two people finish in the same minute.
PRECISE = [label(m) for m in MILESTONES if m["kind"] in ("host_first_log", "proj_log")]
PRECISE_ARR = "array(" + ", ".join(f'"{p}"' for p in PRECISE) + ")"
RANK_SORT = "score desc, last asc, last_precise asc"


def wide(exclude=True):
    cols = ",\n    ".join(f'c{m["id"]} = min(if(milestone == "{label(m)}", first_ts))' for m in MILESTONES)
    q = events()
    if exclude:
        q += f"\n| filter {EXCL}"
    q += f'''
| summarize {{
    score = countDistinct(milestone),
    started = min(first_ts),
    last = max(first_ts),
    last_precise = max(if(in(milestone, {PRECISE_ARR}), first_ts)),
    {cols}
  }}, by: {{ project }}'''
    return q


def ranked():
    """Wide leaderboard plus a `rank` column (ties share a rank)."""
    return wide() + '''
| summarize { rows = collectArray(record(rp = project, rs = score, rl = last, rlp = last_precise, rst = started)) }
| fieldsAdd others = rows
| expand rows
| expand others
| fieldsAdd behind = if(others[rs] > rows[rs]
      or (others[rs] == rows[rs] and others[rl] < rows[rl])
      or (others[rs] == rows[rs] and others[rl] == rows[rl] and others[rlp] < rows[rlp]), 1, else: 0)
| fieldsAdd project = rows[rp], score = rows[rs], last = rows[rl], last_precise = rows[rlp], started = rows[rst]
| summarize { ahead = sum(behind) }, by: { project, score, last, last_precise, started }
| fieldsAdd rank = ahead + 1
| sort rank asc, project asc'''


# --------------------------------------------------------------------------------------
# Tile helpers
# --------------------------------------------------------------------------------------
class Board:
    def __init__(self):
        self.tiles, self.layouts, self.y, self.i = {}, {}, 0, 0

    def add(self, tile, x, w, h):
        k = str(self.i)
        self.tiles[k] = tile
        self.layouts[k] = {"x": x, "y": self.y, "w": w, "h": h}
        self.i += 1

    def row(self, items, h):
        x = 0
        for tile, w in items:
            self.add(tile, x, w, h)
            x += w
        self.y += h

    def md(self, text, h=1):
        self.row([({"type": "markdown", "content": text}, 24)], h)


def data(title, query, viz, settings=None):
    t = {"title": title, "type": "data", "query": query, "visualization": viz,
         "visualizationSettings": settings or {}}
    return t


def single(title, query, label_):
    return data(title, query, "singleValue",
                {"singleValue": {"label": label_, "recordField": "v"}})


def alert_single(title, query, label_):
    return data(title, query, "singleValue", {
        "singleValue": {"label": label_, "recordField": "v", "colorThresholdTarget": "background"},
        "coloring": {"colorRules": [
            {"value": 0, "comparator": ">", "field": "v", "colorMode": "custom-color",
             "customColor": {"Default": "var(--dt-colors-charts-status-critical-default, #c4233b)"}},
            {"value": 0, "comparator": "≤", "field": "v", "colorMode": "custom-color",
             "customColor": {"Default": "var(--dt-colors-charts-status-ideal-default, #2f6862)"}}]}})


def exclude_var(visible=True):
    return {
        "key": "Exclude", "type": "query", "visible": visible, "editable": True, "multiple": True,
        "input": (f"fetch logs\n| filter isNotNull(project) and {LAB_SIG}\n"
                  f"| summarize n = count(), by: {{ project }}\n| fields project\n"
                  f'| append [ data record(project = "{SENTINEL}") ]\n| sort project asc'),
        "defaultValue": EXCLUDE_DEFAULT,
    }


def me_var():
    return {
        "key": "Me", "type": "query", "visible": True, "editable": True, "multiple": False,
        "input": (f"fetch logs\n| filter isNotNull(project) and {LAB_SIG}\n"
                  f"| summarize n = count(), by: {{ project }}\n| fields project\n| sort project asc"),
    }


def milestone_table_md():
    rows = "\n".join(f'| {m["id"]} | {m["name"]} | {m["proof"]} |' for m in MILESTONES)
    return f"| # | Milestone | Counts when… |\n|---|---|---|\n{rows}"


def dashboard(board, variables):
    return {"version": 21, "variables": variables, "tiles": board.tiles, "layouts": board.layouts,
            "settings": {"defaultTimeframe": {"value": {"from": "now()-4h", "to": "now()"}, "enabled": True}},
            "importedWithCode": False}


# --------------------------------------------------------------------------------------
# Trainer dashboard
# --------------------------------------------------------------------------------------
def trainer():
    b = Board()
    b.md(f"""# 🏁 Bindplane Lab Race — trainer view
Each participant is identified by their **`project`** value. A milestone counts the first time its **effect** reaches Dynatrace, not when it is configured. Collector-level milestones (pipeline live, cumulative to delta, signal to metric) are credited through the collector's `host.name`, mapped to the project it sends.

**Before the session:** set the timeframe to start at the session start (rehearsal data must not count), and pick trainers/colleagues in **Exclude**. Ranking = most milestones, then earliest time of the last milestone.

{milestone_table_md()}""", h=12)

    W = wide()
    b.md("## Class overview")
    b.row([
        (single("Participants", W + "\n| summarize v = count()", "on the board"), 4),
        (single("Online now", f"fetch logs, from: now()-5m\n| filter isNotNull(project) and {LAB_SIG} and {EXCL}\n"
                              "| summarize v = countDistinct(project)", "sending in last 5 min"), 4),
        (single("Finished", W + f"\n| summarize v = countIf(score == {N})", f"all {N} milestones"), 4),
        (single("Average progress", W + "\n| summarize v = round(avg(score), decimals: 1)",
                f"milestones out of {N}"), 4),
        (single("Current leader", W + f"\n| sort {RANK_SORT}\n| limit 1\n| fields v = project",
                "most milestones, earliest"), 4),
        (alert_single("Untagged collectors",
                      f"fetch logs\n| filter isNotNull(host.name) and {LAB_SIG}\n"
                      "| summarize tagged = countIf(isNotNull(project)), by: { host.name }\n"
                      "| filter tagged == 0\n| summarize v = count()", "lab hosts with no project yet"), 4),
    ], 3)

    b.md("## 🏆 Leaderboard")
    ticks = ",\n    ".join(f'`{m["name"]}` = if(isNull(c{m["id"]}), "⬜", else: "✅")' for m in MILESTONES)
    tick_names = ", ".join(f'`{m["name"]}`' for m in MILESTONES)
    b.row([(data("Leaderboard — ranked by milestones, then by who got there first", W + f'''
| fieldsAdd finished = if(score == {N}, last)
| fieldsAdd
    {ticks}
| sort {RANK_SORT}
| fields participant = project, score, {tick_names}, last_milestone_at = last, finished''', "table"), 24)], 10)

    b.row([
        (data("🏆 Podium — first to finish everything", W + f'''
| filter score == {N}
| sort last asc, last_precise asc
| limit 3
| fields participant = project, finished_at = last, time_taken = last - started''', "table"), 12),
        (data("🥇 First to each milestone", events() + f'''
| filter {EXCL}
| sort first_ts asc
| summarize {{ winner = takeFirst(project), achieved_at = takeFirst(first_ts), completed_by = count() }}, by: {{ milestone }}
| sort milestone asc''', "table"), 12),
    ], 8)

    b.md("## Progress")
    b.row([
        (data("Participants per milestone", events() + f'''
| filter {EXCL}
| summarize participants = count(), by: {{ milestone }}
| sort milestone asc''', "categoricalBarChart"), 12),
        (data("🏎️ The race — milestones completed over time", events() + f'''
| filter {EXCL}
| makeTimeseries m = count(), by: {{ project }}, time: first_ts, interval: 5m
| fieldsAdd m = arrayCumulativeSum(m)''', "lineChart"), 12),
    ], 8)
    b.row([(data("📣 Activity feed — newest first", events() + f'''
| filter {EXCL}
| sort first_ts desc
| fields achieved_at = first_ts, participant = project, milestone''', "table"), 24)], 8)

    b.md("## 🛟 Who needs help")
    missing = '"🎉 Finished"'
    for m in reversed(MILESTONES):
        missing = f'if(isNull(c{m["id"]}), "{m["name"]}", else: {missing})'
    b.row([
        (data("Stuck or slow — next milestone and idle time", W + f'''
| filter score < {N}
| fieldsAdd next_milestone = {missing}
| fieldsAdd idle_min = round((now() - last) / 1m, decimals: 0)
| sort idle_min desc
| fields participant = project, score, next_milestone, last_milestone_at = last, idle_min''', "table"), 12),
        (data("Collector identity — typos, duplicates, untagged", f'''fetch logs
| filter isNotNull(host.name) and {LAB_SIG}
| summarize {{ projects = collectDistinct(project), last_seen = max(timestamp) }}, by: {{ host.name }}
| fieldsAdd n = arraySize(projects)
| fieldsAdd issue = if(n == 0, "❌ No project yet",
    else: if(n > 1, "⚠️ Host sent more than one project name", else: "✅ OK"))
| sort issue asc
| fields issue, host.name, projects, last_seen''', "table"), 12),
    ], 8)
    b.row([
        (data("Project names used by more than one host (duplicate names)", f'''fetch logs
| filter isNotNull(project) and isNotNull(host.name) and {LAB_SIG}
| summarize hosts = collectDistinct(host.name), by: {{ project }}
| filter arraySize(hosts) > 1''', "table"), 12),
        (data("Sampling check — allow share per participant (should drop to ~57%)", f'''fetch logs
| filter isNotNull(project) and {EXCL} and appname == "PAN-OS" and isNotNull(pan.action)
| makeTimeseries {{ allow = countIf(pan.action == "allow"), total = count() }}, by: {{ project }}, interval: 1m
| fieldsAdd allow_share_pct = 100 * allow[] / total[]
| fields timeframe, interval, project, allow_share_pct''', "lineChart"), 12),
    ], 8)
    b.row([
        (data("💳 Payment challenge — OpenPipeline payment field extraction (separate from the race)", payment_board() + '''
| fields status, participant, first_extracted, payment_logs, extracted, coverage_pct, clusters''', "table"), 24),
    ], 7)
    return dashboard(b, [exclude_var(visible=True), exclude_cluster_var(visible=True)])


# --------------------------------------------------------------------------------------
# Participant dashboard
# --------------------------------------------------------------------------------------
def participant():
    b = Board()
    E = events(me=True)
    b.md("""# 🧪 My Bindplane lab — proof of work
Pick **your project name** in the **Me** selector above. Every tick below is earned from your data actually arriving in Dynatrace, so it proves your pipeline works, not just that you configured it.""", h=3)

    rank_q = wide(exclude=True) + '''
| summarize {
    rows = collectArray(record(s = score, l = last)),
    ms = max(if(project == $Me, score)),
    ml = max(if(project == $Me, last)),
    n = count()
  }
| expand rows
| summarize { ahead = countIf(rows[s] > ms or (rows[s] == ms and rows[l] < ml)), n = takeAny(n) }
| fields v = concat(toString(ahead + 1), " of ", toString(n))'''

    b.row([
        (single("My milestones", E + f'\n| summarize c = countDistinct(milestone)\n| fields v = concat(toString(c), " / {N}")',
                "completed"), 6),
        (single("My position", rank_q, "on the leaderboard"), 6),
        (single("Time in the lab", E + "\n| summarize { s = min(first_ts), l = max(first_ts) }\n| fields v = l - s",
                "first to latest milestone"), 6),
        (single("Credentials I exposed (hashed)", f'''timeseries v = sum(log.exposed_bch_credentials.count), by: {{ host.name, bch_access_key_id }}
{LOOKUP_MAP}
| filter m_project == $Me and not startsWith(bch_access_key_id, "BCHK")
| summarize v = countDistinct(bch_access_key_id)''', "distinct access keys"), 6),
    ], 3)

    recs = ",\n  ".join(f'record(milestone = "{label(m)}", how_it_is_verified = "{m["proof"]}")' for m in MILESTONES)
    b.row([(data("✅ My checklist", f'''data
  {recs}
| lookup [
{ind(E)}
], sourceField: milestone, lookupField: milestone, prefix: "e_"
| fieldsAdd status = if(isNull(e_first_ts), "⬜ Not yet", else: "✅ Done")
| fields milestone, status, achieved_at = e_first_ts, how_it_is_verified''', "table"), 24)], 8)

    b.md("## Parsing and field removal")
    b.row([(data("My parsed firewall records (latest 20)", '''fetch logs
| filter project == $Me and appname == "PAN-OS" and isNotNull(pan.action)
| sort timestamp desc
| limit 20
| fieldsAdd raw_csv = if(isNull(content) or content == "", "removed ✅", else: "still present")
| fields timestamp, pan.action, pan.app, pan.src_ip, pan.dst_ip, pan.dst_port, pan.bytes, pan.session_end_reason, raw_csv''',
                 "table"), 24)], 7)

    b.md("## Volume reduction")
    b.row([
        (data("My firewall traffic per minute — allow vs everything else", '''fetch logs
| filter project == $Me and appname == "PAN-OS" and isNotNull(pan.action)
| makeTimeseries { allow = countIf(pan.action == "allow"), deny_drop_reset = countIf(pan.action != "allow") }, interval: 1m''',
              "lineChart"), 12),
        (data("My allow share (%) — drops when sampling kicks in", '''fetch logs
| filter project == $Me and appname == "PAN-OS" and isNotNull(pan.action)
| makeTimeseries { allow = countIf(pan.action == "allow"), total = count() }, interval: 1m
| fieldsAdd allow_share_pct = 100 * allow[] / total[]
| fields timeframe, interval, allow_share_pct''', "lineChart"), 12),
    ], 7)

    b.md("## Masking and metrics")
    state = ('if(startsWith(bch_ak, "BCHK"), "raw", else: if(stringLength(bch_ak) >= 64 and stringLength(bch_sk) >= 64, '
             '"hashed", else: "partial"))')
    b.row([
        (data("Credential records — raw vs hashed per minute", f'''fetch logs
| filter project == $Me and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")
{PROJ_PREP}
| fieldsAdd state = {state}
| makeTimeseries {{ raw = countIf(state == "raw"), hashed = countIf(state == "hashed"), partial = countIf(state == "partial") }}, interval: 1m''',
              "lineChart"), 12),
        (data("Exposed credentials (hashed) — how often each appeared", f'''timeseries v = sum(log.exposed_bch_credentials.count), by: {{ host.name, bch_access_key_id }}
{LOOKUP_MAP}
| filter m_project == $Me
| fieldsAdd occurrences = arraySum(v)
| fields bch_access_key_id, occurrences
| sort occurrences desc''', "table"), 12),
    ], 7)
    b.row([(data("My latest credential records", f'''fetch logs
| filter project == $Me and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")
{PROJ_PREP}
| fieldsAdd state = {state}
| sort timestamp desc
| limit 10
| fields timestamp, state, content''', "table"), 24)], 6)

    b.md("## My pipeline")
    b.row([
        (data("Records I sent, by source", '''fetch logs
| filter project == $Me
| fieldsAdd source = if(isNotNull(flow.type), "NetFlow",
    else: if(isNotNull(log.file.name), concat("File: ", log.file.name),
    else: if(isNotNull(appname), concat("Syslog: ", appname), else: "Other")))
| summarize records = count(), by: { source }
| sort records desc''', "categoricalBarChart"), 12),
        (data("My collector memory (self-telemetry)", f'''timeseries v = avg(otelcol_process_memory_rss), by: {{ host.name }}
{LOOKUP_MAP}
| filter m_project == $Me
| fields timeframe, interval, host.name, v''', "lineChart"), 12),
    ], 7)
    return dashboard(b, [me_var(), exclude_var(visible=False)])


# --------------------------------------------------------------------------------------
# Results ceremony dashboard
# --------------------------------------------------------------------------------------
SAMPLING_DROP_RATIO = 0.9   # what participants were told to use; drives the "records saved" estimate


def awards():
    b = Board()
    R = ranked()
    W = wide()
    E = events() + f"\n| filter {EXCL}"
    lab_records = f'(isNotNull(project) and {EXCL} and ({LAB_SIG[1:-1]} or receiver == "netflow"))'
    sampling = next(m for m in MILESTONES if m["kind"] == "proj_sampling")
    keep_factor = round(SAMPLING_DROP_RATIO / (1 - SAMPLING_DROP_RATIO))  # 0.9 -> 9 dropped per 1 kept
    bar_full, bar_empty = "█" * N, "░" * N
    state_hashed = 'stringLength(bch_ak) >= 64 and stringLength(bch_sk) >= 64 and not startsWith(bch_ak, "BCHK")'

    b.md("""# 🏆 Bindplane Lab Race — Results
Ranked by milestones completed, then by who reached their last milestone first. Every milestone was earned from data that actually arrived in Dynatrace.""", h=2)

    # Stepped podium in classic 2 - 1 - 3 order: the winner is wider, taller and starts highest.
    def medal_tile(title, query, color):
        return data(title, query + "\n| fieldsAdd r = 1", "singleValue", {
            "singleValue": {"label": "", "showLabel": False, "recordField": "v", "colorThresholdTarget": "background"},
            "coloring": {"colorRules": [{"value": 0, "comparator": ">", "field": "r", "colorMode": "custom-color",
                                         "customColor": {"Default": color}}]}})

    def name_q(rank):
        return R + f"\n| filter rank == {rank}\n| limit 1\n| fields v = project"

    def stat_q(rank):
        return R + f'''
| filter rank == {rank}
| limit 1
| fields v = concat(if(score == {N}, "✅ all {N}", else: concat(toString(score), " / {N}")),
    " · ", toString(round((last - started) / 1m, decimals: 0)), " min")'''

    GOLD, SILVER, BRONZE = "#D4AF37", "#B8BEC6", "#C88A53"
    top = b.y
    #            title,           rank, colour, x,  w,  name_y_offset, name_h
    for title, rank, color, x, w, dy, h in [
        ("🥇 Champion",    1, GOLD,   7, 10, 0, 6),
        ("🥈 Runner-up",   2, SILVER, 0, 7,  2, 4),
        ("🥉 Third place", 3, BRONZE, 17, 7, 3, 3),
    ]:
        b.y = top + dy
        b.add(medal_tile(title, name_q(rank), color), x, w, h)
        b.y = top + dy + h
        b.add(medal_tile(" ", stat_q(rank), color), x, w, 2)
    b.y = top + 8

    b.row([(data("🏆 Podium details", R + f'''
| filter rank <= 3
| fieldsAdd medal = if(rank == 1, "🥇", else: if(rank == 2, "🥈", else: "🥉"))
| fieldsAdd finished = if(score == {N}, "✅ all {N}", else: concat(toString(score), " / {N}"))
| fields medal, participant = project, finished,
    minutes_taken = round((last - started) / 1m, decimals: 0), last_milestone_at = last''', "table"), 24)], 5)

    b.md("## 🙌 Everyone who raced")
    b.row([(data("Final standings", R + f'''
| fieldsAdd place = if(rank == 1, "🥇", else: if(rank == 2, "🥈", else: if(rank == 3, "🥉", else: toString(rank))))
| fieldsAdd progress = concat(substring("{bar_full}", from: 0, to: score), substring("{bar_empty}", from: 0, to: {N} - score))
| fields place, participant = project, progress, milestones = score,
    minutes_taken = round((last - started) / 1m, decimals: 0), last_milestone_at = last''',
                 "table"), 24)], 12)

    b.md("## 📊 By the numbers")
    b.row([
        (single("Racers", W + "\n| summarize v = count()", "took part"), 4),
        (single("Crossed the finish line", W + f'\n| summarize {{ f = countIf(score == {N}), n = count() }}\n'
                f'| fields v = concat(toString(f), " (", toString(round(100.0 * f / n, decimals: 0)), "%)")',
                f"completed all {N}"), 4),
        (single("Milestones earned", E + "\n| summarize v = count()", "across the whole class"), 4),
        (single("Records shipped", f"fetch logs\n| filter {lab_records}\n| summarize v = count()",
                "logs sent to Dynatrace"), 4),
        (single("Kept off the wire by sampling", f'''fetch logs
| filter isNotNull(project) and {EXCL} and appname == "PAN-OS" and pan.action == "allow"
| lookup [
{ind(sampling_part(False, sampling))}
], sourceField: project, lookupField: project, prefix: "s_"
| filter isNotNull(s_first_ts) and timestamp >= s_first_ts
| summarize c = count()
| fields v = c * {keep_factor}''', "routine records dropped at the edge (est.)"), 4),
        (single("Credentials hashed", f'''fetch logs
| filter isNotNull(project) and {EXCL} and log.file.name == "audit.log" and contains(content, "BCH_ACCESS_KEY_ID=")
{PROJ_PREP}
| filter {state_hashed}
| summarize v = count()''', "secrets that never left in clear text"), 4),
    ], 4)

    PAY = PAY_LOGS + f"\n| filter {PAY_EXCL} and {PAY_DONE}"
    b.row([
        (single("🔎 Syslog lines parsed by OpenPipeline", f'''fetch logs
| filter isNotNull(project) and {EXCL} and log.file.name == "syslog" and isNotNull(syslog.severity)
| summarize v = count()''', "host logs given a real severity on ingest"), 8),
        (single("💳 Payments decoded", PAY + "\n| summarize v = count()", "transactions turned into business fields"), 8),
        (single("💰 Revenue made visible", PAY + '''
| summarize total = sum(toDouble(app.payment.amount)), by: { app.payment.currencyCode }
| sort total desc
| limit 1
| fields v = concat(app.payment.currencyCode, " ", toString(round(total, decimals: 0)))''',
                "from plain log lines (top currency)"), 8),
    ], 3)

    b.row([(data("💳 Payment challenge — first to turn payment logs into business data", payment_board() + '''
| fields status, participant, first_extracted, extracted, coverage_pct''', "table"), 24)], 6)

    b.md("## 🎖️ Special awards")
    first_to = lambda m: E + f'''
| filter milestone == "{label(m)}"
| sort first_ts asc
| limit 1
| fields v = project'''
    m_live = MILESTONES[0]
    m_mask = next((m for m in MILESTONES if m["name"] == "Masking"), MILESTONES[-1])
    b.row([
        (single("⚡ Speed demon", W + f'''
| filter score == {N}
| fieldsAdd t = (last - started) / 1m
| sort t asc
| limit 1
| fields v = concat(project, " · ", toString(round(t, decimals: 1)), " min")''', "fastest start-to-finish"), 5),
        (single("🏁 Off the line first", first_to(m_live), f"first to get {m_live['name'].lower()}"), 5),
        (single("🔐 Security first", first_to(m_mask), "first to hash the leaked credentials"), 5),
        (single("🧱 Toughest milestone", f'''data
  {", ".join(f'record(milestone = "{label(m)}")' for m in MILESTONES)}
| lookup [
{ind(E + chr(10) + "| summarize n = count(), by: { milestone }")}
], sourceField: milestone, lookupField: milestone, prefix: "x_"
| fieldsAdd n = coalesce(x_n, 0)
| sort n asc, milestone desc
| limit 1
| fields v = milestone''', "fewest people completed it"), 5),
        (single("🪶 Leanest collector", f'''timeseries v = avg(otelcol_process_memory_rss), by: {{ host.name }}
{LOOKUP_MAP}
| filter isNotNull(m_project) and not in(m_project, array($Exclude))
| fieldsAdd mb = arrayAvg(v) / 1048576
| sort mb asc
| limit 1
| fields v = concat(m_project, " · ", toString(round(mb, decimals: 0)), " MB")''', "lowest average memory"), 4),
    ], 4)

    steps = ",\n    ".join(
        f'record(step = "{label(cur)}", d = c{cur["id"]} - c{prev["id"]})'
        for prev, cur in zip(MILESTONES, MILESTONES[1:]))
    b.row([
        (data("⏱️ Where the time went — average minutes per step", W + f'''
| fieldsAdd steps = array(
    {steps})
| expand steps
| fieldsAdd step = steps[step], mins = steps[d] / 1m
| filter isNotNull(mins) and mins >= 0
| summarize avg_minutes = round(avg(mins), decimals: 1), by: {{ step }}
| sort step asc''', "categoricalBarChart"), 12),
        (data("🏎️ How the race unfolded", E + '''
| makeTimeseries m = count(), by: { project }, time: first_ts, interval: 5m
| fieldsAdd m = arrayCumulativeSum(m)''', "lineChart"), 12),
    ], 8)

    b.row([
        (data("🥇 First to each milestone", E + '''
| sort first_ts asc
| summarize { winner = takeFirst(project), achieved_at = takeFirst(first_ts), completed_by = count() }, by: { milestone }
| sort milestone asc''', "table"), 12),
        (data("🔥 What the class's firewalls saw — top apps in parsed traffic", f'''fetch logs
| filter isNotNull(project) and {EXCL} and appname == "PAN-OS" and isNotNull(pan.app)
| summarize sessions = count(), by: {{ app = pan.app }}
| sort sessions desc
| limit 8''', "categoricalBarChart"), 12),
    ], 8)
    return dashboard(b, [exclude_var(visible=True), exclude_cluster_var(visible=True)])


if __name__ == "__main__":
    for name, d in [("bindplane-race-trainer.json", trainer()),
                    ("bindplane-race-my-progress.json", participant()),
                    ("bindplane-race-results.json", awards())]:
        with open(name, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print(f"wrote {name}: {len(d['tiles'])} tiles")
