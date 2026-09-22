# Volume Reduction

## The problem

Firewall traffic logs are the highest volume, lowest value-per-record source in most estates. A session-end record is written for every connection that completes, and the overwhelming majority of those connections were permitted, uneventful, and will never be looked at again. In the mock estate in this lab, 92 percent of PAN-OS TRAFFIC records carry `action=allow` with a normal session end reason such as `tcp-fin` or `aged-out`.

The records you actually investigate are the other 8 percent. A `deny`, `drop` or `reset-both` session is evidence that a policy fired. Those need to arrive complete and unsampled, because a security investigation that finds a gap in the data is worse than no data at all.

This gives a clean rule. Forward every denied session at full fidelity. Sample the permitted sessions at a ratio you choose. You keep the whole security signal and discard most of the bulk. In Dynatrace, logs are billed on what you ingest and again on what you retain, so this reduction applies twice. It is usually the single largest cost lever available in a log pipeline, and it costs you nothing analytically as long as the sampling is applied only to the routine traffic.

## The pipeline config

This goes in a Bindplane **Custom** processor, which accepts raw OpenTelemetry Collector configuration. It depends on the parsing processor from [Structured Field Extraction](pipeline-field-extraction.md), so place it **after** that processor in the pipeline.

```yaml
filter/panos_volume:
  error_mode: ignore
  logs:
    log_record:
      - attributes["pan.action"] == "allow" and not IsMatch(attributes["pan.session_id"], "[0]$")
```

Two things are worth understanding here.

The `filter` processor drops a record when the condition is **true**. Read the condition as "discard this record if it was allowed, and its session ID does not end in 0". Anything that is not an `allow` never matches, so every `deny`, `drop` and `reset-both` passes through untouched.

The sampling ratio is the character class at the end. Matching on the last digit of the session ID gives deterministic sampling, so the same record is always kept or always dropped, and there is no random number generator to reason about.

| Pattern | Keeps | Reduction on allow traffic |
|---|---|---|
| `[0]$` | 10 percent | 90 percent |
| `[05]$` | 20 percent | 80 percent |
| `[0-4]$` | 50 percent | 50 percent |

### If you have not done the parsing exercise yet

You can filter on the raw message instead. This works standalone but is harder to read and harder to maintain.

```yaml
filter/panos_volume_raw:
  error_mode: ignore
  logs:
    log_record:
      - IsMatch(attributes["message"], ",(tcp|udp),allow,") and not IsMatch(attributes["message"], ",\\d*0,1,")
```

## Measured result

Run against 941 live PAN-OS TRAFFIC records from the lab generator, with the `[0]$` ratio:

```
                 records      raw bytes
  before             941         286909
  after              172          51051
  reduction          82%            83%

  action        before   after    kept
  allow            860      91     10%
  deny              24      24    100%
  drop              30      30    100%
  reset-both        27      27    100%
```

Every denied session survived. The allow traffic came down to a tenth. Total volume fell by 83 percent.

## Lab exercise

**Goal:** cut PAN-OS log volume by more than 80 percent without losing a single denied session.

1. Confirm the generator is running and sending to the Syslog source on UDP 5140.

    ```bash
    ps -eo args | grep "[p]ush_telemetry"
    ```

2. Record your baseline. In the Bindplane configuration overview, note the current throughput in MB per hour for the Syslog source. Take a screenshot, you will compare against it.

3. In Dynatrace, count the records by action so you know what you started with.

    ```
    fetch logs
    | filter matchesPhrase(content, "TRAFFIC,end")
    | summarize count(), by: {action = splitString(content, ",")[31]}
    ```

4. Add a **Custom** processor to your configuration, after the parsing processor. Paste the `filter/panos_volume` config above.

5. Roll out the configuration.

6. Wait five minutes, then compare. Throughput on the Syslog source should drop by roughly 80 percent.

7. Prove nothing was lost. Re-run the query from step 3. The `deny`, `drop` and `reset-both` counts should keep climbing at the same rate as before. Only `allow` should have slowed.

8. Change the ratio to `[0-4]$`, roll out again, and watch the throughput settle at roughly half the original instead of a tenth.

**Checkpoint:** you should be able to state the reduction percentage, and show that denied sessions are still arriving at full rate.

!!! warning "Sample the routine traffic only"
    It is tempting to sample everything, because the reduction number gets bigger. Do not. The value of this pattern is that it is defensible to a security team: you can point at the condition and show that policy-relevant records bypass it entirely. A blanket sampler gives up that argument for a few more percent.
