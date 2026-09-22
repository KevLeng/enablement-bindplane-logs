# Volume Reduction

## The problem

Firewall traffic logs are the highest volume, lowest value-per-record source in most estates. A session-end record is written for every connection that completes, and the overwhelming majority of those connections were permitted, uneventful, and will never be looked at again. In the mock estate in this lab, 92 percent of PAN-OS TRAFFIC records carry `action=allow` with a normal session end reason such as `tcp-fin` or `aged-out`.

The records you actually investigate are the other 8 percent. A `deny`, `drop` or `reset-both` session is evidence that a policy fired. Those need to arrive complete and unsampled, because a security investigation that finds a gap in the data is worse than no data at all.

This gives a clean rule. Forward every denied session at full fidelity. Sample the permitted sessions at a ratio you choose. In Dynatrace, logs are billed on what you ingest and again on what you retain, so the reduction applies twice. It is usually the single largest cost lever in a log pipeline, and it costs you nothing analytically as long as sampling touches only the routine traffic.

## Configure it in Bindplane

This reads `pan.action`, so it goes **after** the Parse CSV processor from [Structured Field Extraction](pipeline-field-extraction.md).

Add a processor and search for **Sampling**. Two settings.

**Condition**

```
body["pan"]["action"] == "allow"
```

**Drop Ratio**: `0.9`

That is the whole configuration. The processor drops 90 percent of the records that match the condition and passes everything else through untouched. Because the condition names `allow` explicitly, a `deny`, `drop` or `reset-both` record can never be selected for dropping.

| Drop Ratio | Keeps of allow traffic |
|---|---|
| `0.9` | 10 percent |
| `0.8` | 20 percent |
| `0.5` | 50 percent |

### The generated config

```yaml
sampling/panos_allow:
  drop_ratio: 0.9
  condition: body["pan"]["action"] == "allow"
```

## Measured result

Tested against live generator output with the processor in place:

```
                 records      raw bytes
  before             561         171327
  after               94          27950
  reduction          84%            84%

  action        before   after    kept
  allow            517      50      9%
  deny              22      22    100%
  drop              11      11    100%
  reset-both        11      11    100%
```

Every denied session survived. Allow traffic came down to roughly a tenth. Total volume fell by 84 percent.

## Why firewall logs for this

It is fair to ask whether this dataset makes the exercise harder than it needs to be. For volume reduction it is the opposite: firewall traffic is the textbook case, and for three reasons.

The volume is genuinely there. Firewall session logs are usually the largest single log source in an enterprise, so the saving is material rather than academic.

The keep-or-drop signal is unambiguous and lives in one field. You are not writing heuristics about what looks interesting, you are reading the action the firewall already decided on. That makes the rule easy to explain and easy to defend.

The 92 to 8 split is realistic. Customers recognise their own environment in it, which is what makes the cost conversation land.

The awkward part of this dataset was never the reduction, it was the positional CSV. The Parse CSV processor handles that from the UI, so the difficulty disappears.

## Lab exercise

**Goal:** cut PAN-OS log volume by more than 80 percent without losing a single denied session.

1. Confirm the generator is running.

    ```bash
    ps -eo args | grep "[p]ush_telemetry"
    ```

2. Record your baseline. In the Bindplane configuration overview, note the throughput in MB per hour on the Syslog source. Screenshot it.

3. Count records by action so you know the starting mix.

    ```
    fetch logs
    | filter isNotNull(pan.action)
    | summarize count(), by: {pan.action}
    ```

4. Add a **Sampling** processor after Parse CSV. Set the condition and a drop ratio of `0.9`.

5. Roll out the configuration.

6. Wait five minutes and compare throughput against your screenshot. It should have fallen by roughly 80 percent.

7. Prove nothing was lost. Re-run the query from step 3. The `deny`, `drop` and `reset-both` counts should keep climbing at the same rate. Only `allow` should have slowed.

8. Change the drop ratio to `0.5`, roll out, and watch throughput settle at about half the original instead of a tenth.

**Checkpoint:** you can state the reduction percentage and show that denied sessions still arrive at full rate.

!!! warning "Sample the routine traffic only"
    It is tempting to sample everything, because the headline number gets bigger. Do not. The value of this pattern is that it is defensible to a security team: you can point at the condition and show that policy-relevant records bypass it entirely. A blanket sampler gives that up for a few more percent.

!!! tip "Talking about cost"
    Relate the reduction to both ingest and retention. A record that is never ingested is also never retained, so the saving compounds over the retention period. Use the customer's own retention setting when you size it, and use their own action mix rather than the 92 to 8 from this lab.
