# Structured Field Extraction

## The problem

A PAN-OS TRAFFIC record arrives as one long comma separated string. Dynatrace stores it in the `content` field and has no idea that position 31 is the firewall action or that position 33 is the byte count. Everything in that record is technically present and practically unreachable.

The cost shows up at query time. Every question you ask has to split the string first, index the right position, and cast the result. The analyst has to know the field offsets by heart, the queries are unreadable, and nothing can be used as a dimension in a dashboard or an alert without repeating the same parsing expression.

Bindplane has a **Parse CSV** processor that does this from the UI. You give it the delimiter and a list of column names, and it turns the CSV into named attributes. Do this exercise first, because the three use cases that follow all read the attributes it produces.

## Configure it in Bindplane

Add a processor to your Syslog source and search for **CSV**. Choose **Parse CSV**, then fill in four things.

**Parse From**

```
attributes.message
```

**Parse To**

```
attributes.pan
```

**Delimiter**: a single comma.

**Header**: paste this. It names all 38 positions in a TRAFFIC record.

```
future_use1,future_use2,receive_time,serial,type,subtype,future_use3,generated_time,src_ip,dst_ip,nat_src_ip,nat_dst_ip,rule_name,user,dst_user,app,vsys,src_zone,dst_zone,inbound_if,outbound_if,log_action,future_use4,session_id,repeat_count,src_port,dst_port,nat_src_port,nat_dst_port,flags,protocol,action,bytes,bytes_sent,bytes_received,packets,elapsed,session_end_reason
```

**Condition**: this one is not optional.

```
attributes.appname == "PAN-OS" and attributes.message contains ",TRAFFIC,end,"
```

!!! danger "Without the condition, this processor will fail"
    Your Syslog source carries more than firewall logs. The Citrix, FSLogix and Azure NSG records on the same port are JSON, which contains quotes and commas. Feeding those to a CSV parser produces a stream of `bare " in non-quoted field` and `wrong number of fields` errors. Tested: with the condition in place, zero parse errors. Without it, hundreds.

!!! danger "Parse the message attribute, not the body"
    The Syslog source puts the **full raw line** in `body`, including the `<134>Sep 22 ... PAN-OS:` prefix. It puts the **CSV alone** in `attributes.message`. Parsing `body` shifts every field by one and does not raise an error, it is just quietly wrong.

## The generated config

For reference, this is what Bindplane builds from those settings. You do not need to paste it anywhere.

```yaml
logstransform/panos_csv:
  operators:
    - type: csv_parser
      if: 'attributes.appname == "PAN-OS" and attributes.message contains ",TRAFFIC,end,"'
      parse_from: attributes.message
      parse_to: attributes.pan
      delimiter: ","
      header: "future_use1,future_use2,receive_time,serial,type,subtype,future_use3,generated_time,src_ip,dst_ip,nat_src_ip,nat_dst_ip,rule_name,user,dst_user,app,vsys,src_zone,dst_zone,inbound_if,outbound_if,log_action,future_use4,session_id,repeat_count,src_port,dst_port,nat_src_port,nat_dst_port,flags,protocol,action,bytes,bytes_sent,bytes_received,packets,elapsed,session_end_reason"
```

## The fields you get

Verified against live records from the lab generator. The ones that matter for the later exercises:

| Attribute | Example |
|---|---|
| `pan.src_ip` | `10.56.108.190` |
| `pan.dst_ip` | `13.138.205.95` |
| `pan.rule_name` | `Citrix-to-Backend` |
| `pan.user` | `contoso.local\gsantos` |
| `pan.app` | `citrix-cgp` |
| `pan.src_zone` / `pan.dst_zone` | `trust` / `dmz` |
| `pan.src_port` / `pan.dst_port` | `26054` / `389` |
| `pan.protocol` | `tcp` |
| `pan.action` | `allow` |
| `pan.bytes_sent` / `pan.bytes_received` | `648334` / `1334817` |
| `pan.packets` | `8895` |
| `pan.session_end_reason` | `tcp-rst-from-client` |

The `future_use` columns are real PAN-OS padding fields. They are named so the positions line up, and you can ignore them.

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
    Parse CSV produces string values for every column, including byte and packet counts. Wrap them in `toLong()` when you need a numeric comparison or a sum. If you would rather have real numeric types on the record, that needs a Custom processor with OTTL and `Int()` conversions, which is more powerful and considerably less convenient. For this lab the `toLong()` cast is the better trade.

## Lab exercise

**Goal:** turn the CSV blob into named attributes using only the Bindplane UI.

1. In Dynatrace, open one PAN-OS record in the log viewer. `content` holds the whole CSV and there is nothing useful to filter on.

2. Run the "before" query above. Note how much of it is scaffolding rather than analysis.

3. In Bindplane, add a **Parse CSV** processor as the **first** processor on your Syslog source. Fill in the five settings above.

4. Use the live preview before rolling out. You should see the `pan.*` attributes appear. Check one deliberately: find a record where `pan.action` is not `allow` and confirm `pan.session_end_reason` reads `policy-deny`.

5. Roll out the configuration.

6. In Dynatrace, open a new PAN-OS record. The `pan.*` attributes should now be listed as fields.

7. Run the "after" query and confirm it returns the same records.

8. Summarise by a parsed field, which was not possible before.

    ```
    fetch logs
    | filter isNotNull(pan.action)
    | summarize count(), by: {pan.action, pan.rule_name}
    ```

**Checkpoint:** you can group firewall records by action and rule without a single `splitString` in the query, and you configured it without writing any code.
