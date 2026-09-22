#!/bin/bash
# ======================================================================
#          ------- Custom Functions -------                            #
#  Space for adding custom functions so each repo can customize as.    # 
#  needed.                                                             #
# ======================================================================


customFunction(){
  printInfoSection "This is a custom function that calculates 1 + 1"

  printInfo "1 + 1 = $(( 1 + 1 ))"

}

startLogGenerator(){
local logdir="${1:-/var/log}"

# Ensure the files the generator appends to exist and are writable. Only those
# files are claimed, never the whole directory: $logdir is /var/log by default,
# and chown -R on it would take ownership of dpkg.log, apt/, btmp and friends.
if [ ! -d "$logdir" ]; then
  sudo mkdir -p "$logdir"
fi
# id -un rather than $USER: $USER is unset in a non-login shell, which silently
# turns the chown into a no-op and leaves the files unwritable.
sudo mkdir -p "$logdir/audit"
sudo chown "$(id -un)":"$(id -gn)" "$logdir/audit"
for logfile in syslog auth.log kern.log cron.log fail2ban.log audit/audit.log; do
  if [ ! -w "$logdir/$logfile" ]; then
    sudo touch "$logdir/$logfile"
    sudo chown "$(id -un)":"$(id -gn)" "$logdir/$logfile"
  fi
done

nohup python3 .devcontainer/util/generate_logs.py \
  --logdir "$logdir" \
  --scenario leak_bch_key,brute_force,recon,data_exfil \
  --scenario-after 20 \
  --scenario-repeat 50 \
  --interval 0.5 \
  --quiet > /dev/null 2>&1 &
echo $! > ./generator.pid  # save the PID so you can kill it later
}

stopLogGenerator(){
if [ -f ./generator.pid ]; then
  local pid
  pid="$(cat ./generator.pid)"
  if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
    kill "$pid"
  fi
fi
}

startBindplane(){
  sudo env \
  PATH=/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin \
  BINDPLANE_COLLECTOR_HOME=/opt/observiq-otel-collector \
  BINDPLANE_COLLECTOR_STORAGE=/opt/observiq-otel-collector/storage \
  sh -c 'cd /opt/observiq-otel-collector && /opt/observiq-otel-collector/observiq-otel-collector --config config.yaml' &
}

stopBindplane(){
  sudo pkill -f observiq-otel-collector
}

# ----------------------------------------------------------------------
# Network telemetry (UDP) — syslog on 5140, NetFlow v5 on 2055.
# generate_logs.py writes files for a Bindplane *File* source; this one
# pushes datagrams for a Bindplane *Syslog* / *NetFlow* source. Both land
# on 127.0.0.1, i.e. the agent inside this container.
# ----------------------------------------------------------------------

startNetworkTelemetry(){
local target="${1:-127.0.0.1}"
local repo="${REPO_PATH:-.}"
local pidfile="$repo/telemetry.pid"
local logfile="${TELEMETRY_LOG:-/tmp/push_telemetry.log}"

# Ports the Bindplane Syslog / NetFlow sources listen on. These are already the
# default on both sides; they are set here so they sit next to the lab and can
# be overridden, e.g. NETFLOW_PORT=2056 startNetworkTelemetry
local syslog_port="${SYSLOG_PORT:-5140}"
local netflow_port="${NETFLOW_PORT:-2055}"

printInfoSection "Starting network telemetry generator"

# A second generator on the same ports would just double the rate, so refuse.
if [ -f "$pidfile" ] && ps -p "$(cat "$pidfile" 2>/dev/null)" > /dev/null 2>&1; then
  printWarn "Already running as PID $(cat "$pidfile") - run stopNetworkTelemetry first"
  return 0
fi

# --per-packet 5 puts NetFlow at roughly one datagram per second. At the default
# of 20 records per datagram it emits only one every four seconds, which looks
# like a stalled pipeline next to the syslog stream.
nohup python3 "$repo/.devcontainer/util/push_telemetry.py" \
  --to "$target" \
  --syslog-port "$syslog_port" \
  --netflow-port "$netflow_port" \
  --per-packet 5 \
  > "$logfile" 2>&1 &
local pid=$!
echo "$pid" > "$pidfile"  # save the PID so you can kill it later

# Confirm it survived startup rather than reporting success blindly: a bad port
# or a missing python would otherwise fail silently into the background.
sleep 1
if ! ps -p "$pid" > /dev/null 2>&1; then
  printError "Generator exited immediately. Its output was:"
  cat "$logfile"
  rm -f "$pidfile"
  return 1
fi

printInfo "syslog  -> udp://$target:$syslog_port  (RFC 3164)"
printInfo "netflow -> udp://$target:$netflow_port  (NetFlow v5)"
printInfo "Running as PID $pid, logging to $logfile"
printInfo "Stop it with stopNetworkTelemetry"
}

stopNetworkTelemetry(){
local repo="${REPO_PATH:-.}"
local pidfile="$repo/telemetry.pid"
local stopped=0

printInfoSection "Stopping network telemetry generator"

if [ -f "$pidfile" ]; then
  local pid
  pid="$(cat "$pidfile" 2>/dev/null)"
  if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
    kill "$pid" 2>/dev/null && stopped=1
    # Give it a moment to go down cleanly, then insist.
    local waited=0
    while ps -p "$pid" > /dev/null 2>&1 && [ "$waited" -lt 10 ]; do
      sleep 0.2
      waited=$((waited + 1))
    done
    ps -p "$pid" > /dev/null 2>&1 && kill -9 "$pid" 2>/dev/null
  fi
  rm -f "$pidfile"
fi

# Catch strays left by a shell that died before writing the PID file. The
# bracket stops pkill from matching this function's own command line.
if pkill -f "[p]ush_telemetry.py" > /dev/null 2>&1; then
  stopped=1
fi

if [ "$stopped" -eq 1 ]; then
  printInfo "Generator stopped"
else
  printInfo "No generator was running"
fi
}
