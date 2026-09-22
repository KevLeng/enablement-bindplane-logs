# Structured Field Extraction

## The problem

A PAN-OS TRAFFIC record arrives as one long comma separated string. Dynatrace stores it in the `content` field and has no idea that position 31 is the firewall action or that position 33 is the byte count. Everything in that record is technically present and practically unreachable.

The cost of that shows up at query time. Every question you ask has to split the string first, index the right position, and cast the result. The analyst has to know the field offsets by heart, the queries are unreadable, and nothing can be used as a dimension in a dashboard or an alert without repeating the same parsing expression.

Parsing once at the pipeline puts named attributes on the record before it is ever stored. The query becomes a normal filter on a normal field. The same attributes then drive severity, security context, and metric dimensions, so this one processor is what the other three use cases are built on. Do this exercise first if you are running the whole set.

## The field map

Verified against 1,780 live records from the lab generator. A TRAFFIC record has **38 comma separated fields**.

| Index | Field | Example |
|---|---|---|
| 4 | record type | `TRAFFIC` |
| 8 | source IP | `10.23.38.26` |
| 9 | destination IP | `104.80.13.177` |
| 12 | rule name | `Allow-O365` |
| 13 | user | `contoso.local\hnakamura` |
| 15 | application | `ldap` |
| 17 | source zone | `trust` |
| 18 | destination zone | `dmz` |
| 23 | session ID | `351213` |
| 25 | source port | `26054` |
| 26 | destination port | `389` |
| 30 | protocol | `tcp` |
| 31 | action | `allow` |
| 33 | bytes sent | `277998` |
| 34 | bytes received | `1334817` |
| 35 | packets | `9361` |
| 37 | session end reason | `aged-out` |

!!! danger "Parse the message attribute, not the body"
    The Bindplane Syslog source puts the **full raw line** in `body`, including the `<134>Sep 22 ... PAN-OS:` prefix. It puts the **CSV alone** in `attributes["message"]`. A config that splits `body` will produce fields that are all shifted by one and will not error, it will just be quietly wrong. Always split `attributes["message"]`.

## The pipeline config

Bindplane **Custom** processor. This is the first processor in the chain.

```yaml
transform/panos_parse:
  error_mode: ignore
  log_statements:
    - context: log
      statements:
        - set(cache["f"], Split(attributes["message"], ",")) where attributes["appname"] == "PAN-OS"
        - set(cache["ok"], true) where Len(cache["f"]) == 38 and cache["f"][4] == "TRAFFIC"
        - set(attributes["pan.src_ip"], cache["f"][8]) where cache["ok"] == true
        - set(attributes["pan.dst_ip"], cache["f"][9]) where cache["ok"] == true
        - set(attributes["pan.rule_name"], cache["f"][12]) where cache["ok"] == true
        - set(attributes["pan.user"], cache["f"][13]) where cache["ok"] == true
        - set(attributes["pan.app"], cache["f"][15]) where cache["ok"] == true
        - set(attributes["pan.src_zone"], cache["f"][17]) where cache["ok"] == true
        - set(attributes["pan.dst_zone"], cache["f"][18]) where cache["ok"] == true
        - set(attributes["pan.session_id"], cache["f"][23]) where cache["ok"] == true
        - set(attributes["pan.src_port"], Int(cache["f"][25])) where cache["ok"] == true
        - set(attributes["pan.dst_port"], Int(cache["f"][26])) where cache["ok"] == true
        - set(attributes["pan.protocol"], cache["f"][30]) where cache["ok"] == true
        - set(attributes["pan.action"], cache["f"][31]) where cache["ok"] == true
        - set(attributes["pan.bytes_sent"], Int(cache["f"][33])) where cache["ok"] == true
        - set(attributes["pan.bytes_received"], Int(cache["f"][34])) where cache["ok"] == true
        - set(attributes["pan.packets"], Int(cache["f"][35])) where cache["ok"] == true
        - set(attributes["pan.session_end_reason"], cache["f"][37]) where cache["ok"] == true
```

How it works. The first statement splits the CSV once and parks the resulting list in `cache`, which is scratch space that exists for the lifetime of this record and is never exported. The second statement sets a guard flag, so a short or malformed record is skipped instead of producing garbage attributes. Every remaining statement reads one position out of the cached list.

`Int()` matters on the numeric fields. Without it you get the string `"277998"`, which cannot be summed or compared in a DQL numeric filter. Ports, byte counts and packet counts all go through `Int()`. Session ID stays a string because the volume reduction exercise pattern matches on its last character.

`error_mode: ignore` means a record that does not look like PAN-OS passes through untouched rather than failing the batch.

## Before and after at query time

Finding large outbound transfers on a denied session.

**Before**, with string parsing at query time:

```
fetch logs
| filter matchesPhrase(content, "TRAFFIC,end")
| fieldsAdd action = splitString(content, ",")[31]
| fieldsAdd bytes_sent = toLong(splitString(content, ",")[33])
| filter action != "allow" and bytes_sent > 1000000
```

**After**, with parsed attributes:

```
fetch logs
| filter pan.action != "allow" and pan.bytes_sent > 1000000
```

The second one is readable, uses an index, and the fields are available in the log viewer sidebar, in dashboard dimensions, and in alert conditions without restating the parse.

## Lab exercise

**Goal:** turn the CSV blob into queryable attributes.

1. In Dynatrace, find one PAN-OS record and look at it in the log viewer. Note that `content` holds the whole CSV and there are no useful fields to filter on.

2. Run the "before" query above. Note how much of it is scaffolding rather than analysis.

3. In Bindplane, add a **Custom** processor as the **first** processor on your Syslog source. Paste the `transform/panos_parse` config.

4. Use the live preview in Bindplane to inspect a record before rolling out. You should see the `pan.*` attributes appear alongside the original body.

5. Roll out the configuration.

6. Back in Dynatrace, open a new PAN-OS record. The `pan.*` attributes should now be listed as fields.

7. Run the "after" query. Confirm it returns the same records as the "before" query.

8. Prove the types are right. This only works if `pan.bytes_sent` is a number, not a string.

    ```
    fetch logs
    | filter isNotNull(pan.action)
    | summarize total = sum(pan.bytes_sent), by: {pan.action}
    ```

**Checkpoint:** you can summarise bytes by action without any `splitString` in the query.

!!! tip "Why the pan. prefix"
    Namespacing the attributes keeps them clearly separate from fields Dynatrace sets itself, and from any other source you add to the same configuration later. It also makes them easy to find in the log viewer sidebar, which sorts fields alphabetically.
