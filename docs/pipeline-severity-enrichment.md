# Severity Enrichment

## The problem

PAN-OS forwards every TRAFFIC log at informational severity, whatever the firewall actually did. A session that was denied by policy and a session that completed normally both arrive with syslog priority 134, which is `local0.info`. You can verify this on the lab data: every TRAFFIC record carries the same priority regardless of its action field.

This is not a bug in PAN-OS. Traffic logs are informational by definition in the PAN-OS severity model, and only THREAT logs carry a varying severity. But the effect downstream is that Dynatrace shows a wall of INFO records, the log viewer severity filter is useless on this source, and you cannot write an alert on "firewall denials" without falling back to string matching on the content field.

The action field already holds the truth. Severity enrichment simply promotes that truth into the severity of the record, so that the standard Dynatrace tooling starts working. Filtering by severity in the log viewer, colouring in the log timeline, and alerting on error-level events all become available without any source specific knowledge.

## The mapping

| PAN-OS action | Severity | Reasoning |
|---|---|---|
| `allow` | INFO | Session was permitted, nothing happened |
| `deny` | WARN | Policy blocked the session before it started |
| `drop` | WARN | Packets silently discarded |
| `reset-both` | ERROR | Firewall actively tore down both ends, the most aggressive response it has |

Splitting `reset-both` out as ERROR gives you three usable levels instead of two. It is also the action most likely to indicate something actively hostile rather than a routine policy match, so it is the one worth paging on.

## The pipeline config

Bindplane **Custom** processor. Place it **after** the parsing processor, since it reads `pan.action`.

```yaml
transform/panos_severity:
  error_mode: ignore
  log_statements:
    - context: log
      statements:
        - set(severity_text, "INFO") where attributes["pan.action"] == "allow"
        - set(severity_number, SEVERITY_NUMBER_INFO) where attributes["pan.action"] == "allow"
        - set(severity_text, "WARN") where attributes["pan.action"] == "deny" or attributes["pan.action"] == "drop"
        - set(severity_number, SEVERITY_NUMBER_WARN) where attributes["pan.action"] == "deny" or attributes["pan.action"] == "drop"
        - set(severity_text, "ERROR") where attributes["pan.action"] == "reset-both"
        - set(severity_number, SEVERITY_NUMBER_ERROR) where attributes["pan.action"] == "reset-both"
```

Set both `severity_text` and `severity_number`. The text is what a human sees in the log viewer, the number is what Dynatrace sorts and filters on. Setting only one of them produces a record that looks right but does not filter correctly.

The statements run in order and the later ones overwrite the earlier ones, so a record can only end on one severity. Records that are not PAN-OS never match any condition and keep whatever severity they arrived with.

## Measured result

Run against the lab generator output after the processor was applied:

```
  action=allow        severityText=INFO    n=91
  action=deny         severityText=WARN    n=24
  action=drop         severityText=WARN    n=30
  action=reset-both   severityText=ERROR   n=27
```

Every record was reclassified, and no record was left at the original misleading INFO.

## Lab exercise

**Goal:** make the Dynatrace severity filter work on firewall logs.

1. In Dynatrace, open the Logs app and filter to your PAN-OS records. Open the severity facet. Everything is INFO, including the denials. This is the problem.

2. Confirm it at the source. In the container, look at the syslog priority on a denied session.

    ```bash
    python3 .devcontainer/util/push_telemetry.py --dry-run 2>&1 | grep PAN-OS
    ```

    Every TRAFFIC line starts with `<134>`, which is `local0.info`.

3. In Bindplane, add a **Custom** processor after the parsing processor. Paste the `transform/panos_severity` config.

4. Roll out the configuration.

5. Back in the Logs app, open the severity facet again. You should now see INFO, WARN and ERROR, with the counts roughly matching the action mix: about 92 percent INFO, 5 percent WARN, 2 percent ERROR.

6. Filter to `severity == "ERROR"`. Every record returned should have `pan.action = reset-both`.

7. Build an alert. Create a metric or an alert condition on ERROR level logs from this source. Note that you did this without mentioning PAN-OS field positions anywhere, because the severity is now standard.

**Checkpoint:** the severity facet in the log viewer shows three levels, and an ERROR filter returns only `reset-both` sessions.

!!! tip "This interacts with volume reduction"
    If you have already applied the volume reduction filter, your INFO proportion will be much lower, because most of the allow traffic was sampled away. That is expected. The denied sessions were all retained, so WARN and ERROR counts are unaffected. It is worth pointing this out in a bootcamp, because the severity mix visibly changes between the two exercises and students will ask.
