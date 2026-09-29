In this hands-on lab, you're going to build a Telemetry Pipeline end-to-end. Using **Bindplane** as your collection and processing layer and **Dynatrace** as your observability backend, you'll collect syslog data from a Linux host, shape it in-flight, and deliver it to Dynatrace, where **OpenPipeline** takes over to parse and further enrich it.

By the end of the lab, you'll know how to:

- Deploy and configure a Bindplane agent on a Linux host
- Define sources, processors, and destinations in a Bindplane configuration
- Cut log volume by up to 40 percent by sampling routine firewall traffic while keeping every denied session
- Parse raw CSV firewall records into named, queryable attributes before they are stored
- Set log severity from what the firewall actually did rather than trusting the syslog priority
- Enrich logs with custom metadata before they leave the host
- Parse structured fields out of raw syslog content using Dynatrace OpenPipeline
- Detect and mask sensitive credentials in-flight using regex-based redaction
- Route logs selectively so only the right data passes through each processor
- Convert log events into metrics and query them with DQL
- Monitor the health of your Bindplane pipeline itself using self-monitoring

## Prerequisites

| What you need | Detail |
|---|---|
| Bindplane account | With a project created |
| Dynatrace tenant | SaaS environment |
| Dynatrace token | Scopes in the table below |
| Lab environment | GitHub Codespaces, or a local Dev Container |

### Token scopes

| Scope | Used for |
|---|---|
| `storage:logs:write` | Writing log records to Grail |
| `openpipeline:logs:ingest` | Sending logs through OpenPipeline |
| `storage:metrics:write` | Writing extracted metrics |
| `openpipeline:metrics:ingest` | Sending metrics through OpenPipeline |

### If you use a platform token

Scopes on the token are not enough on their own. A platform token can only do what the **user or service user who owns it** is permitted to do, so that identity also needs an IAM policy granting the same permissions. A classic API token carries its scopes directly and needs no policy.

Grant the policy like this:

1. Open **Account Management**, then **Identity & access management**, then **Policies**.
2. Create a policy, choose your environment as the scope, and paste the statements below.
3. Go to **Groups**, pick the group your user or service user belongs to, and bind the policy to it.
4. Create the platform token under **Access tokens**, selecting the same scopes listed above.

```
ALLOW storage:logs:write;
ALLOW storage:metrics:write;
ALLOW openpipeline:logs:ingest;
ALLOW openpipeline:metrics:ingest;
```

!!! tip "Symptom of a missing policy"
    Ingest returns `403 Forbidden` even though the token shows the correct scopes. That is the IAM policy missing, not the token. See the Dynatrace documentation on [IAM policy statements](https://docs.dynatrace.com/docs/manage/identity-access-management/permission-management/manage-user-permissions-policies) and [platform tokens](https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/platform-tokens).

### Lab environment

Pick one. The next section walks through both.

| Option | You need |
|---|---|
| **GitHub Codespaces**, entirely in a browser | A GitHub account |
| **Local [Dev Container](https://code.visualstudio.com/docs/devcontainers/tutorial)** | VS Code, the Dev Containers extension, and Docker |

<div class="grid cards" markdown>
- [Yes! Let's begin :octicons-arrow-right-24:](2-getting-started.md)