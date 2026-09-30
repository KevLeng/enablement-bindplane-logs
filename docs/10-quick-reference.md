# Quick Reference

Every value you type, paste or search for in this lab, in the order you need it. Each step links to its full walkthrough. All videos and screenshots are collected under [Walkthroughs](#walkthroughs) at the bottom.

## Before you start

Your Dynatrace platform token needs these four scopes:

```
storage:logs:write
openpipeline:logs:ingest
storage:metrics:write
openpipeline:metrics:ingest
```

Both log generators start automatically in the container. You do **not** need to start them.

| Command | Purpose |
|---|---|
| `startBindplane` / `stopBindplane` | The collector process |
| `startLogGenerator` / `stopLogGenerator` | Linux host logs written to `/var/log` |
| `startNetworkTelemetry` / `stopNetworkTelemetry` | Syslog on udp/5140, NetFlow on udp/2055 |

---

## 1. Install the agent &mdash; [details](3-bindplane-agent.md)

Copy the install command from Bindplane, paste it into the container terminal, then start the collector:

```
startBindplane
```

Do **not** use `systemctl`, whatever the installer prints.

---

## 2. Create the configuration &mdash; [details](4-bindplane-configuration.md)

Platform **Linux**. Four sources, one destination. **Start Rollout** when done.

### File source

Short Description:

```
file
```

File Paths:

```
/var/log/syslog
/var/log/audit/audit.log
/var/log/fail2ban.log
```

Log Type `file` &middot; Multiline Parsing `none`

!!! danger "Only those three files"
    `auth.log`, `kern.log` and `cron.log` are duplicates of what is already in `syslog` &mdash; 41% of total volume, entirely redundant. `audit/audit.log` and `fail2ban.log` are not duplicates, and the audit log carries the leaked credentials.

### Syslog source

Short Description:

```
syslog
```

Listening IP Address:

```
0.0.0.0
```

Listening Port:

```
5140
```

Protocol `rfc3164` &middot; Transport `udp` &middot; Data Flow `high` &middot; Timezone `UTC` &middot; Parse To `body` &middot; Multiline Parsing `none`

!!! warning "Two picks that matter later"
    **Protocol** must be `rfc3164`, not 5424. **Parse To** must be `body`, or the Parse CSV processor in step 4 finds nothing.

### NetFlow source

Short Description:

```
Netflow
```

Hostname:

```
0.0.0.0
```

Port:

```
2055
```

Telemetry Type `LOGS` &middot; Scheme `netflow` &middot; Sockets `1` &middot; Workers `1` &middot; Send Raw unchecked

### Bindplane Collector source

Don't change any values. Just accept the defaults.

### Dynatrace destination

Your environment ID, plus the token from [Before you start](#before-you-start).

---

## 3. Add a field &mdash; [details](5-add-field.md)

**Add Fields** transform processor on the Syslog source.

Short Description:

```
Add Project Name
```

Field name:

```
project
```

Field value:

```
bindplane-logs-lab
```

This becomes the OpenPipeline routing key in step 6.

---

## 4. Parse the PAN-OS CSV &mdash; [details](pipeline-field-extraction.md)

**Parse CSV** processor on the Syslog source. Telemetry type **LOGS**.

Condition &mdash; two rows joined with **AND**, both matching on **Body**. Field `appname` **Equals**:

```
PAN-OS
```

Field `message` **Contains**:

```
,TRAFFIC,end,
```

Fields &mdash; Source Field Type **Body** &middot; Source Field `message` &middot; Target Field Type **Body** &middot; Target Field `pan` &middot; Header Field Type **Static String** &middot; Delimiter `,` &middot; Header Delimiter empty &middot; Mode **Strict**

Headers, all 38:

```
futureuse1,futureuse2,receive_time,serial_number,type,subtype,futureuse3,generate_time,src_ip,dst_ip,nat_src_ip,nat_dst_ip,rule_name,src_user,dst_user,app,vsys,src_zone,dst_zone,inbound_if,outbound_if,log_action,futureuse4,session_id,repeat_cnt,src_port,dst_port,nat_src_port,nat_dst_port,flags,protocol,action,bytes,bytes_sent,bytes_received,packets,elapsed,session_end_reason
```

!!! danger "Two settings that will bite you"
    Source Field Type is **Body**, not Attributes &mdash; the Syslog source moves `appname` and `message` into the body. And always set the Condition, or the JSON records on the same port flood the log with CSV parse errors.

---

## 5. Reduce volume &mdash; [details](pipeline-volume-reduction.md)

**Sample Logs** processor, placed **after** Parse CSV.

Condition &mdash; Match **Body**, Field `pan["action"]`, Operator **Equals**, String:

```
allow
```

Drop Ratio:

```
0.9
```

---

## 6. Parse with OpenPipeline &mdash; [details](6-parsing-with-openpipeline.md)

New logs pipeline, add the **Syslog** technology bundle.

Processor condition, replacing the bundle's default:

```
matchesValue(log.file.name, "syslog")
```

Dynamic route condition:

```
matchesValue(project, "bindplane-logs-lab")
```

---

## 7. Monitor collector health &mdash; [details](9-bindplane-health.md)

**Bindplane Agent** source with metrics **and** logs, linked to the Dynatrace destination. Add a **Custom** processor covering both signals:

```yaml
cumulativetodelta: {}
```

Then upload the dashboard from the repo's `Dashboards` folder.

---

## 8. Mask and route &mdash; [details](7-masking-routing.md)

**Routing** connector with two routes, evaluated top down, first match wins.

Route 1 name:

```
bch-credentials
```

Route 1 condition &mdash; Log &rarr; `body` &rarr; **Matches**:

```
BCH_ACCESS_KEY_ID=|BCH_SECRET_ACCESS_KEY=
```

The same condition written as OTTL:

```
IsMatch(body, "BCH_ACCESS_KEY_ID=|BCH_SECRET_ACCESS_KEY=")
```

Route 2 name, with no condition:

```
default
```

On the `bch-credentials` route add **Redact Sensitive Data**: strategy **Hashing**, uncheck Redaction Rule Presets, then two custom rules.

Access key:

```
BCHK[A-Z0-9]{16}
```

Secret access key:

```
[A-Za-z0-9/+]{40}
```

Then wire the `default` route around the redaction node, into the processor that feeds Dynatrace.

---

## 9. Extract a metric &mdash; [details](8-metric-extraction.md)

**Parse with Regex**, placed **after** the redaction processor so it parses the hashed value:

```
BCH_ACCESS_KEY_ID=(?<bch_access_key_id>\w+)
```

Target Field Type **Attribute**, target field blank.

Then a **Signal to Metric** connector. Metric name:

```
log.exposed_bch_credentials.count
```

Metric Type **Sum**, value `1`. Dimension:

```
bch_access_key_id
```

---

## Verify

Every config change needs a **Rollout** before it takes effect.

Is data reaching the collector? Per-source counts, so you can see which source is stuck:

```bash
curl -s localhost:8888/metrics | grep throughputmeasurement_log_count
```

Are the files being written?

```bash
tail -f /var/log/syslog
```

Are the logs in Dynatrace?

```
fetch logs | filter log.file.name == "syslog" | sort timestamp desc | limit 50
```

What is the PAN-OS action mix? Run it before and after step 5 to prove the denies survived:

```
fetch logs | filter isNotNull(pan.action) | summarize count(), by: {pan.action}
```

Is the metric being ingested?

```
metrics | filter matchesPhrase(metric.key, "bch")
```

How many sets of credentials were exposed?

```
timeseries total = sum(log.exposed_bch_credentials.count), by: {bch_access_key_id}
```

---

## Architecture

```text
  DEV CONTAINER
  =============

  generate_logs.py                        push_telemetry.py
  (Linux host logs)                       (network estate)
        |                                       |
        | writes files                          | sends UDP
        v                                       v
  /var/log/syslog           COLLECT       udp/5140   syslog    (RFC 3164)
  /var/log/audit/audit.log  COLLECT       udp/2055   netflow   (NetFlow v5)
  /var/log/fail2ban.log     COLLECT             |
  /var/log/auth.log         dup of syslog       |
  /var/log/kern.log         dup of syslog       |
  /var/log/cron.log         dup of syslog       |
        |                                       |
        +------------------+--------------------+
                           v
          +-------------------------------------+
          |        BINDPLANE COLLECTOR          |
          |  Sources  ->  Processors            |
          |    - Add Fields   project           |
          |    - Parse CSV    pan.*             |
          |    - Sample Logs  allow 0.9         |
          |    - Router       bch-credentials   |
          |    - Redact       hashing           |
          +------------------+------------------+
                             | OTLP/HTTP
                             v
  DYNATRACE
  =========

        OpenPipeline
          dynamic route   matchesValue(project, "bindplane-logs-lab")
            `- Syslog technology bundle pipeline
                 processor  matchesValue(log.file.name, "syslog")
                 metric     log.exposed_bch_credentials.count
                             |
                             v
        Logs app  .  Notebooks (DQL)  .  Bindplane health dashboard
```

## Security scenarios

`generate_logs.py` injects deliberate incidents alongside realistic background noise. The default set is `leak_bch_key,brute_force,recon,data_exfil`. To list all ten:

```bash
python3 .devcontainer/util/generate_logs.py --list-scenarios
```

| Scenario | Signature | Where |
|---|---|---|
| `brute_force` | Repeated `Failed password` from one bad IP, then a ban | `syslog` + `fail2ban.log` |
| `recon` | Targeted `[UFW BLOCK]` sweep across 22/80/443/3306 | `syslog` |
| `data_exfil` | `curl … -T /etc/passwd`, AppArmor `type=AVC` denial | `syslog` + `audit/audit.log` |
| `leak_bch_key` | `BCH_ACCESS_KEY_ID=` in an auditd EXECVE record | `audit/audit.log` only |

!!! tip "Signal versus noise"
    Failed logins and UFW blocks also occur as ordinary background noise, spread thinly across many `203.0.113.x` addresses. The scenarios differ by being *concentrated* on a single known-bad IP.

---

## Walkthroughs

Screen recordings for the steps above. Each step's own page carries the full set of screenshots.

### Getting the agent installation command

<video controls muted playsinline preload="metadata" style="width:100%; max-width:100%; height:auto;">
  <source src="../img/3-bindplane-agent/get_agent_installation_command.mp4" type="video/mp4">
  Your browser does not support embedded video.
  <a href="../img/3-bindplane-agent/get_agent_installation_command.mp4">Download the video</a> instead.
</video>

[hs-video](https://dt-arr.github.io/enablement-bindplane-logs/img/3-bindplane-agent/get_agent_installation_command.mp4|Get the agent installation command|Navigating Bindplane to generate the Linux agent install command.)

### Installing the agent in the terminal

<video controls muted playsinline preload="metadata" style="width:100%; max-width:100%; height:auto;">
  <source src="../img/3-bindplane-agent/terminal-installation.mp4" type="video/mp4">
  Your browser does not support embedded video.
  <a href="../img/3-bindplane-agent/terminal-installation.mp4">Download the video</a> instead.
</video>

[hs-video](https://dt-arr.github.io/enablement-bindplane-logs/img/3-bindplane-agent/terminal-installation.mp4|Install the Bindplane agent|Running the install command in the dev container terminal.)

The collector reporting in once it starts:

![Collector reported in](img/3-bindplane-agent/reported-collector.png)

### Adding all four sources

<video controls muted playsinline preload="metadata" style="width:100%; max-width:100%; height:auto;">
  <source src="../img/4-bindplane-configuration/add-sources-video.mp4" type="video/mp4">
  Your browser does not support embedded video.
  <a href="../img/4-bindplane-configuration/add-sources-video.mp4">Download the video</a> instead.
</video>

[hs-video](https://dt-arr.github.io/enablement-bindplane-logs/img/4-bindplane-configuration/add-sources-video.mp4|Add all four sources|Adding the File, Syslog, NetFlow and Bindplane Collector sources to the configuration.)

### Parsing the PAN-OS CSV

<video controls muted playsinline preload="metadata" style="width:100%; max-width:100%; height:auto;">
  <source src="../img/pipeline-field-extraction/pan-os-csv-parsing.mp4" type="video/mp4">
  Your browser does not support embedded video.
  <a href="../img/pipeline-field-extraction/pan-os-csv-parsing.mp4">Download the video</a> instead.
</video>

[hs-video](https://dt-arr.github.io/enablement-bindplane-logs/img/pipeline-field-extraction/pan-os-csv-parsing.mp4|Parse the PAN-OS CSV|Configuring the Parse CSV processor on the Syslog source.)
