# Severity Enrichment

## The problem

PAN-OS forwards every TRAFFIC log at informational severity, whatever the firewall actually did. A session denied by policy and a session that completed normally both arrive with syslog priority 134, which is `local0.info`. You can verify this on the lab data: every TRAFFIC record carries the same priority regardless of its action.

This is not a bug in PAN-OS. Traffic logs are informational by definition in the PAN-OS severity model, and only THREAT logs carry a varying severity. The effect downstream is that Dynatrace shows a wall of INFO records, the severity filter in the log viewer is useless on this source, and you cannot alert on firewall denials without falling back to string matching.

The action field already holds the truth. Severity enrichment promotes it into the severity of the record, so standard Dynatrace tooling starts working. Filtering by severity, colouring in the log timeline, and alerting on error-level events all become available without any source specific knowledge.

## The mapping

| PAN-OS action | Severity | Reasoning |
|---|---|---|
| `allow` | INFO | Session permitted, nothing happened |
| `deny` | WARN | Policy blocked the session before it started |
| `drop` | WARN | Packets silently discarded |
| `reset-both` | ERROR | Firewall actively tore down both ends, its most aggressive response |

Splitting `reset-both` out as ERROR gives three usable levels instead of two. It is also the action most likely to indicate something actively hostile rather than a routine policy match, so it is the one worth paging on.

## Configure it in Bindplane

Reads `pan.action`, so place it **after** Parse CSV.

Add a processor and search for **Severity**. Then set:

**Parse From**

```
body.pan.action
```

**Overwrite Text**: on.

**Mapping**: map each severity level to the action values that should produce it.

| Level | Values |
|---|---|
| `info` | `allow` |
| `warn` | `deny`, `drop` |
| `error` | `reset-both` |

**Condition**: two rows joined with AND, both matching on **Body**.

| Match | Field | Operator | String |
|---|---|---|---|
| Body | `appname` | Equals | `PAN-OS` |
| Body | `message` | Contains | `,TRAFFIC,end,` |

!!! tip "Turn Overwrite Text on"
    Without it the processor sets the severity *number* correctly but leaves the severity *text* as the raw action value, so the log viewer shows `reset-both` where you expect `ERROR`. Tested both ways: with Overwrite Text off you get `severityText=deny, severityNumber=13`. With it on you get `severityText=WARN, severityNumber=13`. Dynatrace derives its log level from the number either way, but the text is what a human reads.

### The generated config

```yaml
logstransform/panos_severity:
  operators:
    - type: severity_parser
      if: 'body.appname == "PAN-OS" and body.message contains ",TRAFFIC,end,"'
      parse_from: body.pan.action
      overwrite_text: true
      mapping:
        info: allow
        warn:
          - deny
          - drop
        error: reset-both
```

## Measured result

Tested against live generator output.

| Action | severityText | severityNumber | Records |
|---|---|---|---|
| `allow` | INFO | 9 | 414 |
| `deny` | WARN | 13 | 15 |
| `drop` | WARN | 13 | 10 |
| `reset-both` | ERROR | 17 | 10 |

Severity numbers 9, 13 and 17 are the OpenTelemetry values for INFO, WARN and ERROR. Every record was reclassified, and none was left at the original misleading INFO.

## Lab exercise

**Goal:** make the Dynatrace severity filter work on firewall logs.

1. In the Logs app, filter to your PAN-OS records and open the severity facet. Everything is INFO, including the denials. That is the problem.

2. Confirm it at the source.

    ```bash
    python3 .devcontainer/util/push_telemetry.py --dry-run 2>&1 | grep PAN-OS
    ```

    Every TRAFFIC line starts with `<134>`, which is `local0.info`.

3. In Bindplane, add a **Severity** processor after Parse CSV. Configure the mapping above and turn on Overwrite Text.

4. Use the live preview. Find a `reset-both` record and confirm its severity reads ERROR before you roll out.

5. Roll out the configuration.

6. Open the severity facet again. You should now see three levels, roughly 92 percent INFO, 5 percent WARN and 2 percent ERROR.

7. Filter to ERROR. Every record returned should have `pan.action = reset-both`.

8. Build an alert on ERROR level logs from this source. Note that you did it without referencing a single PAN-OS field position, because the severity is now standard.

**Checkpoint:** the severity facet shows three levels, and an ERROR filter returns only `reset-both` sessions.

!!! tip "This interacts with volume reduction"
    If you already applied the Sampling processor, your INFO proportion will be far lower, because most allow traffic was sampled away. That is expected and worth pointing out in a bootcamp, because the mix visibly changes between the two exercises and students will ask. The WARN and ERROR counts are unaffected, which is the whole point.
