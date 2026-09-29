The **Bindplane Agent** is the component that runs on a host and collects telemetry. Its Bindplane's distribution of the OpenTelemetry Collector which is purpose-built for managed deployment. This means Bindplane can push configuration changes to it remotely via the OpAmp protocol, without you ever touching the host directly.

Once the agent is running and visible in the Bindplane UI, you're ready to tell it what to collect and where to send it.

### Watch: get the agent installation command

<video controls muted playsinline preload="metadata" style="width:100%; max-width:100%; height:auto;">
  <source src="../img/3-bindplane-agent/get_agent_installation_command.mp4" type="video/mp4">
  Your browser does not support embedded video.
  <a href="../img/3-bindplane-agent/get_agent_installation_command.mp4">Download the video</a> instead.
</video>

The written steps below follow the same flow.

### 1. Navigate to your Bindplane account
Click the button "Install Agent"
<!-- ![Install Agent](img/3-bindplane-agent/install_agent.png) -->

### 2. Specify your agent configuration
You can use the default, stable Agent Type.

You can leave "Fleet" blank.

Choose **Linux** for the platform and click "Next"

<!-- ![Agent Platform](img/3-bindplane-agent/agent_platform.png) -->

### Install the agent
You'll be shown a command that installs the agent.  Copy it and run it in your terminal.

<!-- ![Install Command](img/3-bindplane-agent/install_command.png) -->

You should see some text scroll by, and a message indicating that the Bindplane agent was installed.

<!-- ![Terminal](img/3-bindplane-agent/terminal.png) -->

You may see some messages instructing you to use `systemctl` to start the Bindplane service.  DON'T DO THAT!  In this environment, you have a command called `startBindplane` instead.  Go ahead and run that in your terminal.

```
> startBindplane
```

!!! warning "Bindplane Startup"
    Don't use the `systemctl` command to start Bindplane as the installation script mentions.  Instead, use the `startBindplane` command available in your terminal.

Once you've run that command, you should see your agent show up in the Bindplane UI.  It will be named after the host it is installed on.  If you are using a Codespace, it will be your Codespace name.  If you are using a local Dev Container, it will take the name of your Docker implementation.

<!-- ![Success](img/3-bindplane-agent/success.png) -->

Go ahead and click "Create a Configuration" and we'll start ingesting some logs!

<div class="grid cards" markdown>
- [Create Configuration :octicons-arrow-right-24:](4-bindplane-configuration.md)
</div>
