<!-- markdownlint-disable-next-line -->
# <img src="https://cdn.bfldr.com/B686QPH3/at/w5hnjzb32k5wcrcxnwcx4ckg/Dynatrace_signet_RGB_HTML.svg?auto=webp&format=pngg" alt="DT logo" width="30"> Log Pipelines with Bindplane

[![Dynatrace](https://img.shields.io/badge/Dynatrace-Intelligence-purple?logo=dynatrace&logoColor=white)](https://dynatrace-wwse.github.io/codespaces-framework/dynatrace-integration/#mcp-server-integration)
[![Mastering](https://img.shields.io/badge/Mastering-Complexity-8A2BE2?logo=dynatrace)](https://dynatrace-wwse.github.io)
[![Downloads](https://img.shields.io/docker/pulls/shinojosa/dt-enablement?logo=docker)](https://hub.docker.com/r/shinojosa/dt-enablement)
[![Integration tests](https://github.com/dynatrace-wwse/enablement-bindplane-logs/actions/workflows/integration-tests.yaml/badge.svg)](https://github.com/dynatrace-wwse/enablement-bindplane-logs/actions)
[![Version](https://img.shields.io/github/v/release/dynatrace-wwse/enablement-bindplane-logs?color=blueviolet)](https://github.com/dynatrace-wwse/enablement-bindplane-logs/releases)
[![Commits](https://img.shields.io/github/commits-since/dynatrace-wwse/enablement-bindplane-logs/latest?color=ff69b4&include_prereleases)](https://github.com/dynatrace-wwse/enablement-bindplane-logs/graphs/commit-activity)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?color=green)](https://github.com/dynatrace-wwse/enablement-bindplane-logs/blob/main/LICENSE)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Live-green)](https://dynatrace-wwse.github.io/enablement-bindplane-logs/)

---

[![Log Pipeline Overview](docs/img/hero.png)](docs/img/hero.png)

## Lab Overview

During this hands-on training, you will install and configure Bindplane to collect logs from a Linux host, shape them in-flight using processors and routers, and deliver them to Dynatrace, where OpenPipeline takes over to parse and shape them.

**Lab tasks:**

1. **Getting Started**
   - Create a Bindplane account and project
   - Generate a Dynatrace platform token with `logs.ingest` and `metrics.ingest` permissions
   - Launch the lab environment using GitHub Codespaces or a local Dev Container

2. **Install the Bindplane Agent**
   - Run the Bindplane-generated installation command on the lab host
   - Confirm the agent appears in the Bindplane UI

3. **Create a Bindplane Configuration**
   - Define sources for the host log files and the PAN-OS syslog stream
   - Configure a Dynatrace destination using your environment ID and token
   - Assign the agent and verify data flowing in the pipeline overview

4. **Add Fields with a Processor**
   - Apply an *Add Fields* transform to tag every log with a `project` attribute

5. **Volume Reduction**
   - Sample routine allowed firewall sessions while forwarding every denied session in full
   - Measure the before and after byte counts and relate them to Grail ingest and retention cost

6. **Structured Field Extraction**
   - Parse the PAN-OS CSV into named attributes such as `pan.src_ip`, `pan.action` and `pan.bytes_sent`
   - Compare the DQL experience before and after

7. **Severity Enrichment**
   - Reclassify log severity from the firewall action rather than the syslog priority
   - Make the Dynatrace severity filter and alerting usable on this source

8. **Security Context Tagging**
   - Set `dt.security_context` from the firewall action so Grail ABAC policies can scope access
   - Relate the result to the APRA CPS 234 classification requirement

9. **Parse Logs with Dynatrace OpenPipeline**
   - Create an OpenPipeline logs pipeline using the Syslog technology bundle
   - Route logs to it using a dynamic route keyed on the `project` field

10. **Monitor Bindplane Health**
    - Observe the health of your Bindplane infrastructure using Self-Monitoring

11. **Mask Sensitive Data & Route Selectively**
    - Add a *Redact Sensitive Data* processor with custom regex rules and a hashing strategy
    - Insert a router so redaction applies only to credential-bearing logs

12. **Extract Metrics from Logs**
    - Generate counter metrics from the redacted credential data using OpenPipeline

Ready to build a log pipeline?

## 🚀 Open the lab

[https://dynatrace-wwse.github.io/enablement-bindplane-logs](https://dynatrace-wwse.github.io/enablement-bindplane-logs)
