# Quick Reference

The whole lab on one page: what the environment looks like, and every setting you need in order. Use this to build the pipeline quickly, or to check your work. Each step links back to the full explanation.

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

## What the container already does for you

Both generators start automatically. You do **not** need to start them.

| Command | Purpose |
|---|---|
| `startLogGenerator` / `stopLogGenerator` | Linux host logs written to `/var/log` |
| `startNetworkTelemetry` / `stopNetworkTelemetry` | Syslog on udp/5140, NetFlow on udp/2055 |
| `startBindplane` / `stopBindplane` | The collector process |

## Sources to create

Collect these three files, and **only** these three:

| Source type | Setting | Contains |
|---|---|---|
| **File** | `/var/log/syslog` | Everything rsyslog receives, RFC 5424 |
| **File** | `/var/log/audit/audit.log` | auditd &mdash; **including the leaked credentials**. Not syslog format |
| **File** | `/var/log/fail2ban.log` | Bans. Not syslog format |
| **Syslog** | UDP port `5140`, **RFC 3164** | PAN-OS, Azure NSG, Citrix, AVD, HAProxy |
| **NetFlow** | UDP port `2055` | NetFlow v5 flow records |
| **Bindplane Agent** | metrics **and** logs | Collector self-monitoring |

!!! danger "Do not collect auth.log, kern.log or cron.log"
    rsyslog writes every `auth`, `kern` and `cron` record to **two** places: the facility file *and* `/var/log/syslog`. Collecting both ingests the same event twice, in two formats. On a measured run those three files were 589,497 of 1,420,526 bytes &mdash; **41% of total volume, entirely duplicate**. Dropping them costs you nothing.

    `audit/audit.log` and `fail2ban.log` are *not* duplicates. auditd and fail2ban write their own files and never pass through rsyslog, so their content appears nowhere else. Collect all three, and you still get the full 41% saving.

!!! warning "Ports and format"
    `5140` and `2055` are the Bindplane defaults and the generator's defaults, so leave them alone. Choose **RFC 3164**, not 5424 -- the UDP generator emits BSD-format records.

## Steps

### 1. Install the agent &mdash; [details](3-bindplane-agent.md)

Copy the install command from Bindplane, run it in the container terminal, confirm the agent appears.

### 2. Create the configuration &mdash; [details](4-bindplane-configuration.md)

Platform **Linux**. Add the three File sources from the table above, then the **Dynatrace** destination (environment ID + the token with `logs.ingest` and `metrics.ingest`). Assign the agent, then **Rollout**.

### 3. Add a field &mdash; [details](5-add-field.md)

**Add Fields** transform processor: field `project`, value `bindplane-logs-lab`. This becomes the OpenPipeline routing key. Preview, then **Rollout**.

### 4. Parse with OpenPipeline &mdash; [details](6-parsing-with-openpipeline.md)

1. New logs pipeline, add the **Syslog** technology bundle.
2. The bundle's default condition will not match. Replace it with:
   ```
   matchesValue(log.file.name, "syslog")
   ```
   `log.source` is a Dynatrace syslog-extension field; these logs arrive via Bindplane's filelog receiver instead.
3. Dynamic route to that pipeline:
   ```
   matchesValue(project, "bindplane-logs-lab")
   ```

### 5. Mask and route &mdash; [details](7-masking-routing.md)

Router with two routes:

| Route | Condition |
|---|---|
| `bch-credentials` | Log &rarr; `body` &rarr; Matches &rarr; `BCH_ACCESS_KEY_ID=\|BCH_SECRET_ACCESS_KEY=` |
| `default` | no condition |

On the `bch-credentials` route add **Redact Sensitive Data**: strategy **Hashing**, uncheck Redaction Rule Presets, two custom rules:

```
BCHK[A-Z0-9]{16}
[A-Za-z0-9/+]{40}
```

### 6. Extract a metric &mdash; [details](8-metric-extraction.md)

**Parse with Regex**, placed *after* the redaction processor so it parses the hashed value:

```
BCH_ACCESS_KEY_ID=(?<bch_access_key_id>\w+)
```

Target Field Type **Attribute**, target field blank. Then create metric `log.exposed_bch_credentials.count`, type **Sum**, value `1`, dimension `bch_access_key_id`.

### 7. Pipeline use cases on the PAN-OS stream

These four run on the Syslog source and are covered in full on their own pages. All are **Custom** processors taking raw collector YAML. Order matters: parsing must come first, the other three read the attributes it sets.

| Order | Processor | Purpose | Page |
|---|---|---|---|
| 1 | `transform/panos_parse` | CSV to named `pan.*` attributes | [details](pipeline-field-extraction.md) |
| 2 | `filter/panos_volume` | Sample allows, keep all denies. 83% byte reduction measured | [details](pipeline-volume-reduction.md) |
| 3 | `transform/panos_severity` | allow INFO, deny/drop WARN, reset-both ERROR | [details](pipeline-severity-enrichment.md) |
| 4 | `transform/panos_security_context` | `network-operational` vs `security-events` | [details](pipeline-security-context.md) |

!!! danger "Parse attributes\["message"\], not body"
    The Syslog source puts the raw line including the `<134>...` prefix in `body`, and the CSV alone in `attributes["message"]`. Splitting `body` shifts every field by one and fails silently.

### 8. Monitor collector health &mdash; [details](9-bindplane-health.md)

Add the **Bindplane Agent** source (metrics + logs), link it to the Dynatrace destination, and add a **Custom** processor covering both signals:

```yaml
cumulativetodelta: {}
```

Upload the dashboard from the repo's `Dashboards` folder.

## Verify

Every config change needs a **Rollout** before it takes effect.

**Is data reaching the collector?** Per-source counts, so you can see exactly which source is stuck:

```bash
curl -s localhost:8888/metrics | grep throughputmeasurement_log_count
```

**Are the files being written?**

```bash
tail -f /var/log/syslog
```

**Is it in Dynatrace?**

```
fetch logs | filter log.file.name == "syslog" | sort timestamp desc | limit 50
```

## Security scenarios

`generate_logs.py` injects deliberate incidents alongside realistic background noise. The default set is `leak_bch_key,brute_force,recon,data_exfil`; run `python3 .devcontainer/util/generate_logs.py --list-scenarios` for all ten.

| Scenario | Signature | Where |
|---|---|---|
| `brute_force` | Repeated `Failed password` from one bad IP, then a ban | `syslog` + `fail2ban.log` |
| `recon` | Targeted `[UFW BLOCK]` sweep across 22/80/443/3306 | `syslog` |
| `data_exfil` | `curl … -T /etc/passwd`, AppArmor `type=AVC` denial | `syslog` + `audit/audit.log` |
| `leak_bch_key` | `BCH_ACCESS_KEY_ID=` in an auditd EXECVE record | `audit/audit.log` only |

!!! tip "Signal versus noise"
    Failed logins and UFW blocks also occur as ordinary background noise, spread thinly across many `203.0.113.x` addresses. The scenarios differ by being *concentrated* on a single known-bad IP. A detection that counts `Failed password` drowns in the noise; one that groups by source IP finds the incident.
