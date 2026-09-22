# Security Context Tagging

## The problem

Records arriving in Grail without an explicit security context land as `dt.security_context: default-unclassified`. Everything sits in one undifferentiated pool, which means access to it is all or nothing. Anyone permitted to read logs can read all of them.

Firewall data makes that awkward quickly. Allowed session records are operational telemetry: the network team uses them for capacity questions, application dependency mapping and troubleshooting. Denied session records are security evidence: they show policy enforcement, they feed investigations, and access to them is usually meant to be narrower.

`dt.security_context` is the field Grail ABAC policies evaluate. Setting it in the pipeline, based on what the firewall actually did, lets you write one policy that grants the network team the operational records and another that restricts the security records to the security function. The classification is applied once, at ingest, by a rule you can show an auditor, rather than being reconstructed later by whoever writes the query.

## The mapping

| PAN-OS action | `dt.security_context` | Who needs it |
|---|---|---|
| `allow` | `network-operational` | Network and platform teams |
| `deny` | `security-events` | Security operations |
| `drop` | `security-events` | Security operations |
| `reset-both` | `security-events` | Security operations |

## Configure it in Bindplane

Reads `pan.action`, so place it **after** Parse CSV. This needs two **Add Fields** processors, one per classification.

**Processor 1, operational traffic**

| Setting | Value |
|---|---|
| Field name | `dt.security_context` |
| Field value | `network-operational` |
| Condition | `body["pan"]["action"] == "allow"` |

**Processor 2, security events**

| Setting | Value |
|---|---|
| Field name | `dt.security_context` |
| Field value | `security-events` |
| Condition | `body["pan"]["action"] != "allow" and body["pan"]["action"] != nil` |

The second condition tests for "not allow" rather than listing the three denied actions. That way a PAN-OS action this lab does not generate still gets classified as a security event rather than silently falling through. The `!= nil` guard stops non-PAN-OS records on the same source from being tagged.

Records that are not PAN-OS TRAFFIC match neither condition and keep `default-unclassified`. That is deliberate. Silently reclassifying data you have not reasoned about is how access control mistakes happen.

## Measured result

```
  action=allow        network-operational    n=91
  action=deny         security-events        n=24
  action=drop         security-events        n=30
  action=reset-both   security-events        n=27
```

Every record was classified, and the split follows the action field exactly.

## Why this matters for APRA CPS 234

CPS 234 requires an APRA regulated entity to classify its information assets by criticality and sensitivity, and to size its information security controls to that classification. Two obligations are relevant here.

The first is classification itself. An auditor asking how firewall telemetry is classified needs a better answer than "it is all in the log store". A pipeline rule that assigns security context from the firewall action is a documented, testable control. You can show the config, show the mapping table, and show sample records carrying the resulting tag.

The second is controlling access in proportion to sensitivity. Once denied traffic carries `security-events`, a Grail ABAC policy can scope who reads it, and that scoping is enforced by the platform rather than by convention. The evidence trail is straightforward: the pipeline sets the tag, the policy references the tag, and the record shows the tag.

This is a control contribution, not compliance on its own. CPS 234 covers a great deal more, including incident response and testing obligations. Present it as one concrete piece of the classification requirement and do not oversell it.

## Lab exercise

**Goal:** classify firewall records at ingest so ABAC can scope access to them.

1. In Dynatrace, check the current state.

    ```
    fetch logs
    | filter isNotNull(pan.action)
    | summarize count(), by: {dt.security_context}
    ```

    Everything should be `default-unclassified`.

2. In Bindplane, add the two **Add Fields** processors described above, after Parse CSV. Use the live preview to confirm a denied record picks up `security-events` before you roll out.

3. Roll out the configuration.

4. Re-run the query from step 1. You should now see two values, with the counts matching the allow and deny proportions.

5. Confirm the mapping holds record by record.

    ```
    fetch logs
    | filter isNotNull(pan.action)
    | summarize count(), by: {pan.action, dt.security_context}
    ```

    Every `allow` should be `network-operational`. Nothing else should be.

6. Discuss, or build if your tenant permits it, an ABAC policy scoped to `dt.security_context = "security-events"`. Talk through who would hold it and what they would and would not see.

**Checkpoint:** you can show a query proving that denied traffic carries a different security context from allowed traffic, and explain which policy would read each.

!!! warning "Agree the taxonomy before you roll this out"
    The tag values here are examples. Real environments usually have an existing classification scheme, and inventing a parallel one in the pipeline creates work later. Ask what the customer already uses before adopting `security-events` and `network-operational` as-is.
