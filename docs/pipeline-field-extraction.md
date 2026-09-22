# Structured Field Extraction

## The problem

A PAN-OS TRAFFIC record arrives as one long comma separated string. Dynatrace stores it in the `content` field and has no idea that position 31 is the firewall action or that position 33 is the byte count. Everything in that record is technically present and practically unreachable.

The cost shows up at query time. Every question you ask has to split the string first, index the right position, and cast the result. The analyst has to know the field offsets by heart, the queries are unreadable, and nothing can be used as a dimension in a dashboard or an alert without repeating the same parsing expression.

Bindplane has a **Parse CSV** processor that does this from the UI. You give it the delimiter and a list of column names, and it turns the CSV into named fields. Do this exercise first, because the three use cases that follow all read what it produces.

## Configure it in Bindplane

Add a processor to your Syslog source, search for **CSV**, and choose **Parse CSV**. Telemetry type is **LOGS**.

### Condition

Two conditions joined with **AND**. Both match on **Body**, because the Bindplane Syslog source moves the parsed syslog fields into the body.

| Match | Field | Operator | String |
|---|---|---|---|
| Body | `appname` | Equals | `PAN-OS` |
| Body | `message` | Contains | `,TRAFFIC,end,` |

### Fields

| Setting | Value |
|---|---|
| Source Field Type | **Body** |
| Source Field | `message` |
| Target Field Type | **Body** |
| Target Field | `pan` |
| Header Field Type | **Static String** |
| Headers | the 38 names below |
| Delimiter | `,` |
| Header Delimiter | leave empty |
| Mode | **Strict** |

### Headers

```
futureuse1,futureuse2,receive_time,serial_number,type,subtype,futureuse3,generate_time,src_ip,dst_ip,nat_src_ip,nat_dst_ip,rule_name,src_user,dst_user,app,vsys,src_zone,dst_zone,inbound_if,outbound_if,log_action,futureuse4,session_id,repeat_cnt,src_port,dst_port,nat_src_port,nat_dst_port,flags,protocol,action,bytes,bytes_sent,bytes_received,packets,elapsed,session_end_reason
```

!!! danger "Source Field is Body, not Attributes"
    The Bindplane Syslog source runs a `move` operator that relocates `appname`, `message`, `hostname`, `facility` and `priority` from attributes into the body. Point Parse CSV at attributes and it will find nothing, silently.

!!! danger "The Condition is not optional"
    Your Syslog source carries more than firewall logs. The Citrix, FSLogix and Azure NSG records on the same port are JSON, which contains quotes and commas. Feeding those to a CSV parser produces a stream of `bare " in non-quoted field` and `wrong number of fields` errors. Tested: with the condition in place, zero parse errors. Without it, hundreds.

!!! tip "Target Field gives you a namespace"
    Setting Target Field to `pan` nests the parsed columns under `pan`, so they read as `pan.action`, `pan.bytes_sent` and so on. Leaving it empty also works and merges the columns into the top level of the body, which is what Bindplane's Pipeline Intelligence suggests. The namespace is worth the extra word: `action` and `bytes` are generic enough to collide with something else later, and the prefix makes the fields easy to find in the Dynatrace log viewer.

## The fields you get

Verified against live records. The ones that matter for the later exercises:

| Field | Example |
|---|---|
| `pan.src_ip` / `pan.dst_ip` | `10.13.49.71` / `40.237.115.207` |
| `pan.src_port` / `pan.dst_port` | `32893` / `53` |
| `pan.rule_name` | `DC-Replication` |
| `pan.src_user` | `contoso.local\hnakamura` |
| `pan.app` | `dns` |
| `pan.src_zone` / `pan.dst_zone` | `trust` / `mgmt` |
| `pan.protocol` | `tcp` |
| `pan.action` | `allow` |
| `pan.bytes_sent` / `pan.bytes_received` | `484765` / `59289` |
| `pan.packets` | `1476` |
| `pan.elapsed` | session duration in seconds |
| `pan.session_end_reason` | `aged-out` |

The `futureuse` columns are real PAN-OS padding fields. They are named so the positions line up, and you can ignore them.

## Troubleshooting: nothing got parsed

The most common failure is a header whose column count does not match the record. It is nasty because it looks like nothing happened at all.

**Symptom.** Records arrive in Dynatrace as normal but carry no `pan.*` fields. Nothing errors in the Bindplane UI, the processor shows as healthy, and every downstream processor that reads `pan.action` silently stops doing anything.

**Cause.** The CSV parser in Strict mode requires the header to name exactly as many columns as the record contains. One name too many or too few and it rejects the whole record and passes it through unparsed.

**Confirm it** in the collector log on the lab host:

```bash
sudo grep "wrong number of fields" /opt/observiq-otel-collector/log/collector.log | tail -3
```

The numbers tell you both sides of the problem:

```
wrong number of fields: expected 37, found 38
```

**Count the real fields** rather than trusting any documentation, including this page:

```bash
python3 -c "import sys, time; sys.path.insert(0, '.devcontainer/util'); import push_telemetry as p; print(len(p.ev_panos_traffic(time.time())[4].split(',')))"
```

A TRAFFIC record from this lab's generator has **38** fields.

!!! warning "Restart the generator after you change it"
    The generator loads its code once at startup. If you edit `push_telemetry.py` the running process keeps emitting the old format, and the command above will disagree with what is actually on the wire. Run `stopNetworkTelemetry && startNetworkTelemetry` after any change. This has already caught people out: a generator started before the `packets` column was added kept sending 37 fields for hours while the file on disk said 38.

!!! warning "Do not fix a count mismatch by deleting a column name"
    It is tempting to drop a name to make the numbers line up. That shifts every column after the deletion by one position, so the parse then succeeds while quietly putting the wrong values in the wrong fields. Deleting `elapsed` makes `packets` pick up the session duration, and the record looks perfectly healthy while reporting 1,476 packets for a session that actually ran 1,476 seconds. Add or remove the column at the position where the record really differs.

!!! tip "Do not count fields with --dry-run"
    `push_telemetry.py --dry-run` truncates each sample line to 150 characters for readability, so piping it into a field counter reports about 12 fields instead of 38. It is useful for eyeballing the format, not for counting it.

## Before and after at query time

Finding large transfers on a denied session.

**Before:**

```
fetch logs
| filter matchesPhrase(content, "TRAFFIC,end")
| fieldsAdd action = splitString(content, ",")[31]
| fieldsAdd bytes_sent = toLong(splitString(content, ",")[33])
| filter action != "allow" and bytes_sent > 1000000
```

**After:**

```
fetch logs
| filter pan.action != "allow" and toLong(pan.bytes_sent) > 1000000
```

!!! tip "Numeric fields arrive as strings"
    Parse CSV produces string values for every column, including byte and packet counts. Wrap them in `toLong()` when you need a numeric comparison or a sum. Real numeric types would need a Custom processor with OTTL and `Int()` conversions, which is more powerful and considerably less convenient. For this lab the cast is the better trade.

## Lab exercise

**Goal:** turn the CSV blob into named fields using only the Bindplane UI.

1. In Dynatrace, open one PAN-OS record in the log viewer. `content` holds the whole CSV and there is nothing useful to filter on.

2. Run the "before" query above. Note how much of it is scaffolding rather than analysis.

3. In Bindplane, add a **Parse CSV** processor as the **first** processor on your Syslog source. Fill in the condition, fields and headers above.

4. Use the live preview before rolling out. The right hand pane shows the record after processing, so you can confirm the `pan.*` fields appear. Check one deliberately: find a record where `pan.action` is not `allow` and confirm `pan.session_end_reason` reads `policy-deny` and `pan.elapsed` is `0`.

5. Roll out the configuration.

6. In Dynatrace, open a new PAN-OS record. The `pan.*` fields should now be listed.

7. Run the "after" query and confirm it returns the same records.

8. Summarise by a parsed field, which was not possible before.

    ```
    fetch logs
    | filter isNotNull(pan.action)
    | summarize count(), by: {pan.action, pan.rule_name}
    ```

**Checkpoint:** you can group firewall records by action and rule without a single `splitString` in the query, and you configured it without writing any code.
