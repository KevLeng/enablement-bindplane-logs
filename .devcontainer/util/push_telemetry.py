#!/usr/bin/env python3
"""
push_telemetry.py — network telemetry generator for the Bindplane lab.

Companion to generate_logs.py. Where that script *writes files* for a Bindplane
File source to tail, this one *sends UDP datagrams* so you can practice with
Bindplane's network receivers:

  syslog     UDP/5140   Palo Alto traffic+threat, Azure NSG flow logs,
                        Citrix Broker/CDF, FSLogix, AVD (WVD) events, HAProxy
  netflow v5 UDP/2055   synthetic flow records

Everything is sent to 127.0.0.1 by default, i.e. to the Bindplane agent running
inside this very Dev Container. Nothing leaves the container.

Single file, stdlib only, Python 3.8+. Every endpoint gets the same stream.

  python3 .devcontainer/util/push_telemetry.py              # syslog + netflow to localhost
  python3 .devcontainer/util/push_telemetry.py --dry-run    # print samples, send nothing
  python3 .devcontainer/util/push_telemetry.py --syslog-only
  python3 .devcontainer/util/push_telemetry.py --eps 200 --fps 100   # crank the rates
  python3 .devcontainer/util/push_telemetry.py --duration 300        # stop after 5 min
  python3 .devcontainer/util/push_telemetry.py --to 10.1.0.4         # another host

Lab defaults are deliberately gentle (10 eps / 5 flows-per-sec, ~0.2 GiB/day)
so a training environment does not burn ingest quota. The upstream defaults of
1300 eps / 400 fps are load-test territory — only use them on purpose.

Ports below 1024 need root; 5140 is used so the generator runs as `vscode`.
"""

# ==========================================================================
#  Endpoints — one IP or hostname per line. Ports are set below, not here.
#  127.0.0.1 = the Bindplane agent inside this Dev Container.
# ==========================================================================

ENDPOINTS = [
    "127.0.0.1"
]

SYSLOG_PORT = 5140
NETFLOW_PORT = 2055

# Lab-friendly rates. Override with --eps / --fps / --rate.
DEFAULT_EPS = 10
DEFAULT_FPS = 5

# ==========================================================================

import argparse
import json
import random
import socket
import string
import struct
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

BOOT = time.time()

# ---------------------------------------------------------------- fixtures

DOMAIN = "contoso.local"
UPN = "contoso.com"
USERS = ["jsmith", "dnguyen", "rpatel", "mokafor", "lchen", "aivanov", "tmurphy",
         "skoval", "bwilliams", "hnakamura", "gsantos", "kobrien", "pdesai"]
VDA = [f"AU-VDA-{i:03d}" for i in range(1, 25)]
AVD = [f"avd-pool1-{i}" for i in range(16)]
FW = ["AU-SYD-EDGE-01", "AU-SYD-EDGE-02", "AU-MEL-DC-01", "AU-MEL-DC-02"]
APPS = [("ssl", 443), ("web-browsing", 80), ("ms-rdp", 3389), ("citrix", 1494),
        ("citrix-cgp", 2598), ("dns", 53), ("ldap", 389), ("kerberos", 88),
        ("ms-sql-db", 1433), ("smb", 445), ("ntp", 123), ("snmp", 161)]
RULES = ["Users-to-Internet", "DC-Replication", "Citrix-to-Backend", "Allow-O365",
         "Deny-Any-Any-Log", "Mgmt-Jumphost", "Branch-VPN"]
ZONES = ["trust", "untrust", "dmz", "vpn", "mgmt"]


def ip4(private=True):
    if private:
        return f"10.{random.randint(10,60)}.{random.randint(0,255)}.{random.randint(1,254)}"
    return (f"{random.choice([13,20,40,52,104,203])}.{random.randint(0,255)}"
            f".{random.randint(0,255)}.{random.randint(1,254)}")


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="milliseconds")[:-6] + "Z"


def bsd(ts):
    d = datetime.fromtimestamp(ts, timezone.utc)
    # space-padded day, as BSD syslog wants it ("Sep  3", "Sep 21")
    return f"{d.strftime('%b')} {d.day:2d} {d.strftime('%H:%M:%S')}"


# ------------------------------------------------------------ syslog events
# Each returns (facility, severity, tag, hostname, message).
# Records are kept under ~900 bytes so they fit a 1024-byte datagram.

FAC = {"local0": 16, "local1": 17, "local2": 18, "local3": 19, "local4": 20}
SEV = {"crit": 2, "err": 3, "warning": 4, "notice": 5, "info": 6, "debug": 7}


def ev_panos_traffic(ts):
    app, dport = random.choice(APPS)
    deny = random.random() < 0.08
    action = random.choice(["deny", "drop", "reset-both"]) if deny else "allow"
    sent = 0 if deny else random.randint(200, 900_000)
    recv = 0 if deny else random.randint(200, 4_000_000)
    # A denied session is torn down before data flows, so it carries no packets.
    pkts = 0 if deny else random.randint(4, 12_000)
    el = 0 if deny else random.randint(1, 3600)
    t = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y/%m/%d %H:%M:%S")
    host = random.choice(FW)
    msg = ",".join([
        "1", "", t, "013201009876", "TRAFFIC", "end", "", t, ip4(),
        ip4(random.random() < 0.4), "0.0.0.0", "0.0.0.0", random.choice(RULES),
        f"{DOMAIN}\\{random.choice(USERS)}", "", app, "vsys1",
        random.choice(ZONES), random.choice(ZONES), "ethernet1/1", "ethernet1/2",
        "log-forwarding-default", "", str(random.randint(100000, 999999)), "1",
        str(random.randint(1024, 65535)), str(dport), "0", "0", "0x400053",
        random.choice(["tcp", "tcp", "tcp", "udp"]), action,
        str(sent + recv), str(sent), str(recv), str(pkts), str(el),
        "policy-deny" if deny else random.choice(["aged-out", "tcp-fin", "tcp-rst-from-client"]),
    ])
    # PAN-OS forwards every TRAFFIC log at informational severity, whatever the
    # action was. Only THREAT logs carry a varying severity. That is why the
    # severity-enrichment lab has something to fix: the syslog priority on a
    # denied session says "info", and only the action field tells the truth.
    return "local0", "info", "PAN-OS", host, msg


def ev_panos_threat(ts):
    ttype, tname, sev = random.choice([
        ("spyware", "Generic.Trojan.Downloader(84013)", "crit"),
        ("vulnerability", "Apache Log4j RCE(91991)", "crit"),
        ("url", "command-and-control", "crit"),
        ("virus", "Win32/Emotet.AC(2478)", "err"),
        ("scan", "TCP Port Scan(8001)", "warning"),
    ])
    t = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y/%m/%d %H:%M:%S")
    msg = ",".join([
        "1", "", t, "013201009876", "THREAT", ttype, "", t, ip4(False), ip4(),
        random.choice(RULES), f"{DOMAIN}\\{random.choice(USERS)}",
        "ssl", "untrust", "trust", tname, sev,
        random.choice(["alert", "reset-both", "block-url"]),
    ])
    return "local0", sev, "PAN-OS", random.choice(FW), msg


def ev_nsg_flow(ts):
    allowed = random.random() > 0.06
    return "local1", "info", "nsgflow", "nsg-avd-pool1", json.dumps({
        "time": iso(ts),
        "rule": random.choice(["Allow-RDP-ShortPath", "Allow-AVD-Service",
                               "Allow-AD-Replication", "DenyAllInBound", "Allow-HTTPS-Out"]),
        "srcIp": ip4(), "destIp": ip4(random.random() < 0.5),
        "srcPort": random.randint(1024, 65535),
        "destPort": random.choice([443, 3389, 445, 88, 389, 53, 1433]),
        "protocol": random.choice(["T", "T", "T", "U"]),
        "direction": random.choice(["I", "O"]),
        "decision": "A" if allowed else "D",
        "packetsSrcToDst": random.randint(1, 5000),
        "bytesSrcToDst": random.randint(64, 2_000_000),
        "packetsDstToSrc": random.randint(1, 5000),
        "bytesDstToSrc": random.randint(64, 8_000_000),
    }, separators=(",", ":"))


def ev_citrix_logon(ts):
    user = random.choice(USERS)
    host = random.choice(VDA)
    failed = random.random() < 0.02
    ph = {k: round(random.uniform(a, b), 2) for k, (a, b) in {
        "brokering": (0.2, 1.4), "hdxConnection": (0.4, 2.0),
        "authentication": (0.5, 3.0), "gpoProcessing": (1.5, 9.0),
        "profileLoad": (2.0, 14.0), "logonScripts": (0.8, 6.0),
    }.items()}
    total = round(sum(ph.values()), 2)
    return "local2", ("err" if failed else "info"), "CitrixBroker", host, json.dumps({
        "timestamp": iso(ts), "eventId": 1101 if failed else 1002,
        "message": (f"Session launch failed for {user} on {host}" if failed
                    else f"Session established for {user} on {host} in {total}s"),
        "sessionId": str(uuid.uuid4()), "state": "Failed" if failed else "Active",
        "deliveryGroup": random.choice(["DG-Finance", "DG-ContactCentre", "DG-Eng", "DG-Exec"]),
        "publishedName": random.choice(["Finance Desktop", "SAP GUI", "Excel 2021"]),
        "user": user, "upn": f"{user}@{UPN}", "domain": DOMAIN,
        "clientIp": ip4(random.random() < 0.6),
        "clientOs": random.choice(["Windows 11 23H2", "Windows 10 22H2", "macOS 14.5"]),
        "logonDurationSeconds": total, "phases": ph,
        "icaRttMs": round(random.uniform(8, 45), 1),
        "hostGroup": "citrix-vda",
    }, separators=(",", ":"))


def ev_citrix_cdf(ts):
    return "local2", "debug", "CdfSvc", random.choice(VDA), (
        f"[{random.choice(['PicaSvc2','WdIca','BrokerAgent','PortICA','IcaSrv'])}] "
        f"PID={random.randint(400,9000)} TID={random.randint(1000,60000)} "
        f"SESSION={random.randint(1,40)} "
        f"{random.choice(['CVirtualChannel::OnWrite','CIcaSession::PollForData','CVdaState::Refresh'])} "
        f"level=VERBOSE rc=0x{random.randint(0,0xFFFF):04X} "
        f"buffer={random.randint(64,65535)} queue={random.randint(0,32)}")


def ev_fslogix(ts):
    user = random.choice(USERS)
    ok = random.random() > 0.03
    op = random.choice(["Attach", "Detach", "Reattach"])
    return "local2", ("info" if ok else "err"), "frxsvc", random.choice(VDA), json.dumps({
        "timestamp": iso(ts), "operation": op, "status": "Success" if ok else "Failed",
        "statusCode": "0x00000000" if ok else random.choice(["0x00000079", "0x0000045B"]),
        "message": f"{op} of profile container {'succeeded' if ok else 'FAILED'} for {user}",
        "user": user, "upn": f"{user}@{UPN}",
        "container": f"\\\\auprodfs01\\profiles$\\{user}\\Profile_{user}.vhdx",
        "sizeGb": random.randint(2, 30), "durationMs": random.randint(180, 4000),
    }, separators=(",", ":"))


def ev_avd_checkpoint(ts):
    return "local3", "info", "WVDCheckpoints", random.choice(AVD), json.dumps({
        "TimeGenerated": iso(ts), "Type": "WVDCheckpoints",
        "CorrelationId": str(uuid.uuid4()),
        "Name": random.choice([
            "RdpStackAttached", "LoadBalancedNewConnection", "OrchestrationLBSelection",
            "SessionHostConnectionSetup", "TransportConnected", "GatewayConnectionSetup",
            "AuthenticationCompleted", "UserProfileLoaded", "ShellStarted",
            "ConnectionCompleted"]),
        "Source": random.choice(["RDStack", "ClientStack", "Gateway", "Broker"]),
        "step": random.randint(1, 14), "elapsedMs": random.randint(3, 900),
        "UserName": f"{random.choice(USERS)}@{UPN}",
    }, separators=(",", ":"))


def ev_avd_connection(ts):
    return "local3", "notice", "WVDConnections", random.choice(AVD), json.dumps({
        "TimeGenerated": iso(ts), "Type": "WVDConnections",
        "CorrelationId": str(uuid.uuid4()),
        "State": random.choice(["Started", "Connected", "Completed", "Completed"]),
        "ConnectionType": random.choice(["Desktop", "RemoteApp"]),
        "UserName": f"{random.choice(USERS)}@{UPN}",
        "ClientOS": random.choice(["Windows 11 23H2", "macOS 14.5", "iPadOS 17.4"]),
        "ClientType": random.choice(["Desktop", "Web", "iOS", "Android"]),
        "ClientIPAddress": ip4(False),
        "ResourceAlias": random.choice(["hp-pool-syd-prod", "hp-pool-mel-prod"]),
        "GatewayRegion": random.choice(["AU East", "AU Southeast"]),
        "UdpUse": random.choice(["UDP", "TCP", "None"]),
    }, separators=(",", ":"))


def ev_avd_error(ts):
    code, name, msg = random.choice([
        (3703, "ConnectionFailedNoHealthyRdshAvailable", "No session host available in pool"),
        (-2147467259, "ConnectionFailedAvNotAvailable", "Session host is not available"),
        (2, "SessionHostAgentUnhealthy", "Agent heartbeat not received for 15 minutes"),
        (5, "ConnectionFailedUserNotAuthorized", "User not authorised for this app group"),
        (-2146233087, "FSLogixProfileAttachFailure", "Profile container could not be attached"),
    ])
    return "local3", "err", "WVDErrors", random.choice(AVD), json.dumps({
        "TimeGenerated": iso(ts), "Type": "WVDErrors", "CodeSymbolic": name,
        "Code": code, "Message": msg, "CorrelationId": str(uuid.uuid4()),
        "Source": random.choice(["RDGateway", "RDBroker", "SessionHost"]),
        "UserName": f"{random.choice(USERS)}@{UPN}",
    }, separators=(",", ":"))


def ev_avd_health(ts):
    healthy = random.random() > 0.01
    return "local3", ("info" if healthy else "warning"), "WVDAgentHealth", random.choice(AVD), json.dumps({
        "TimeGenerated": iso(ts), "Type": "WVDAgentHealthStatus",
        "Status": "Available" if healthy else random.choice(["Unavailable", "UpgradeFailed"]),
        "AllowNewSession": healthy, "AgentVersion": "1.0.8912.1700",
        "ActiveSessions": random.randint(0, 12), "LastHeartBeat": iso(ts - random.randint(0, 60)),
    }, separators=(",", ":"))


def ev_healthcheck(ts):
    code = 200 if random.random() > 0.002 else 503
    t = datetime.fromtimestamp(ts, timezone.utc).strftime("%d/%b/%Y:%H:%M:%S +0000")
    return "local4", "info", "haproxy", "AU-SYD-LB-01", (
        f'{ip4()} - - [{t}] "GET /Citrix/StoreWeb/Home/Configuration HTTP/1.1" '
        f'{code} 1204 "-" "AzureLoadBalancer/1.0" rt=0.00{random.randint(1,9)} '
        f'upstream={random.choice(VDA)}')


# (weight, generator) — weight is relative share of the syslog stream
SOURCES = [
    (32, ev_panos_traffic),
    (14, ev_nsg_flow),
    (20, ev_citrix_cdf),
    (5, ev_citrix_logon),
    (3, ev_fslogix),
    (15, ev_avd_checkpoint),
    (2, ev_avd_health),
    (9, ev_healthcheck),
    (0.5, ev_avd_connection),
    (0.3, ev_avd_error),
    (0.2, ev_panos_threat),
]
_POP = [g for w, g in SOURCES]
_WEI = [w for w, g in SOURCES]


def syslog_datagram(ts, max_bytes):
    fac, sev, tag, host, msg = random.choices(_POP, weights=_WEI, k=1)[0](ts)
    pri = FAC[fac] * 8 + SEV[sev]
    dg = f"<{pri}>{bsd(ts)} {host} {tag}: {msg}".encode("utf-8", "replace")
    return dg[:max_bytes] if len(dg) > max_bytes else dg


# ----------------------------------------------------------- netflow v5

SUBNETS = [(10, 21), (10, 22), (10, 10), (10, 30), (10, 55)]
NF_PORTS = [443] * 40 + [1494] * 12 + [2598] * 10 + [3389] * 8 + [445] * 6 + \
           [88] * 5 + [389] * 4 + [53] * 6 + [1433] * 3 + [123, 161, 514, 22]
NF_PROTO = {53: 17, 123: 17, 161: 17, 514: 17}


def _nf_ip(ext=False):
    if ext:
        a, b = random.choice([(13, 107), (20, 190), (40, 126), (52, 251), (104, 45), (203, 31)])
        return (a << 24) | (b << 16) | (random.randint(0, 255) << 8) | random.randint(1, 254)
    a, b = random.choice(SUBNETS)
    return (a << 24) | (b << 16) | (random.randint(0, 20) << 8) | random.randint(2, 250)


def netflow_packet(seq, count):
    now = time.time()
    up = int((now - BOOT) * 1000) + 86_400_000
    out = [struct.pack("!HHIIIIBBH", 5, count, up, int(now), int((now % 1) * 1e9), seq, 0, 0, 0)]
    for _ in range(count):
        ext = random.random() < 0.35
        src, dst = (_nf_ip(True), _nf_ip()) if ext else (_nf_ip(), _nf_ip())
        if random.random() < 0.5:
            src, dst = dst, src
        dport = random.choice(NF_PORTS)
        pkts = random.randint(1, 4000)
        last = up - random.randint(0, 5000)
        first = max(last - random.randint(10, 900_000), 0)
        out.append(struct.pack(
            "!IIIHHIIIIHHBBBBHHBBH",
            src, dst, _nf_ip(), random.randint(1, 8), random.randint(1, 8),
            pkts, pkts * random.randint(64, 1400), first, last,
            random.randint(1024, 65535), dport, 0,
            random.choice([0x02, 0x10, 0x18, 0x19, 0x1B]),
            NF_PROTO.get(dport, 6), 0,
            random.choice([0, 8075, 15169, 13335]), random.choice([0, 4764, 1221, 7545]),
            24, 24, 0))
    return b"".join(out)


# ---------------------------------------------------------------- senders

class Target:
    __slots__ = ("spec", "addr", "sent", "bytes", "errors", "last_error")

    def __init__(self, host, port):
        try:
            self.addr = (socket.gethostbyname(host), int(port))
        except socket.gaierror as e:
            raise SystemExit(f"cannot resolve endpoint '{host}': {e}")
        self.spec = f"{host}:{port}"
        self.sent = self.bytes = self.errors = 0
        self.last_error = None


def make_socket(sndbuf):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, sndbuf)
    return s


def pump(kind, targets, rate, build, args, stop):
    """Generic send loop. build(seq) -> datagram, called once per batch."""
    sock = make_socket(args.sndbuf)
    tick = 0.1
    per_tick = rate * tick
    accum = 0.0
    seq = 0
    start = time.time()
    while not stop.is_set():
        loop = time.time()
        if args.duration and loop - start >= args.duration:
            break
        accum += per_tick
        n = int(accum)
        accum -= n
        for _ in range(n):
            dg, units = build(seq)
            seq += units
            if args.dry_run:
                continue
            for t in targets:
                try:
                    sock.sendto(dg, t.addr)
                    t.sent += units
                    t.bytes += len(dg)
                except OSError as e:
                    t.errors += 1
                    t.last_error = str(e)
        sleep = tick - (time.time() - loop)
        if sleep > 0:
            time.sleep(sleep)
    sock.close()


def report(label, targets, dur, unit):
    total_u = sum(t.sent for t in targets)
    total_b = sum(t.bytes for t in targets)
    errs = sum(t.errors for t in targets)
    print(f"\n  {label}: {total_u:,} {unit} to {len(targets)} endpoints, "
          f"{total_b / dur * 86400 / 1024 ** 3:.1f} GiB/day total egress"
          f"{f', {errs:,} send errors' if errs else ''}", file=sys.stderr)
    if targets:
        t = targets[0]
        print(f"    per endpoint: {t.sent:,} {unit}  "
              f"{t.bytes / dur * 86400 / 1024 ** 3:.2f} GiB/day", file=sys.stderr)
    for t in targets:
        if t.errors:
            print(f"    {t.spec}: {t.errors:,} errors — {t.last_error}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description="Push syslog + NetFlow v5 over UDP to one or more endpoints.")
    p.add_argument("--to", action="append", default=[], metavar="HOST",
                   help="endpoint IP or hostname; repeatable or comma separated. "
                        "Overrides ENDPOINTS. No port here — use --syslog-port / --netflow-port.")
    p.add_argument("--rate", type=float, default=1.0, help="multiplier on both rates")
    p.add_argument("--eps", type=float, default=DEFAULT_EPS, help="syslog events/sec")
    p.add_argument("--fps", type=float, default=DEFAULT_FPS, help="netflow flows/sec")
    p.add_argument("--per-packet", type=int, default=20, help="flows per netflow datagram (max 30)")
    p.add_argument("--max-datagram", type=int, default=1024, help="syslog datagram cap, bytes")
    p.add_argument("--duration", type=float, default=0, help="seconds, 0 = forever")
    p.add_argument("--syslog-only", action="store_true")
    p.add_argument("--netflow-only", action="store_true")
    p.add_argument("--syslog-port", type=int, default=SYSLOG_PORT)
    p.add_argument("--netflow-port", type=int, default=NETFLOW_PORT)
    p.add_argument("--sndbuf", type=int, default=4 * 1024 * 1024)
    p.add_argument("--report-every", type=float, default=30)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="print samples, send nothing")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    specs = [x.strip() for s in (args.to or ENDPOINTS) for x in s.split(",") if x.strip()]
    if not specs:
        sys.exit("no endpoints — edit ENDPOINTS at the top of this file, or pass --to")

    if args.dry_run:
        print("  syslog samples:", file=sys.stderr)
        seen = set()
        while len(seen) < 8:
            dg = syslog_datagram(time.time(), args.max_datagram)
            parts = dg.split()
            tag = parts[4] if len(parts) > 4 else b"?"
            if tag in seen:
                continue
            seen.add(tag)
            print(f"    {dg.decode('utf-8','replace')[:150]}", file=sys.stderr)
        nf = netflow_packet(0, args.per_packet)
        print(f"\n  netflow: v5, {args.per_packet} flows/datagram, {len(nf)} bytes", file=sys.stderr)
        print(f"\n  would send to {len(specs)} endpoints: {', '.join(specs[:4])}"
              f"{' ...' if len(specs) > 4 else ''}\n", file=sys.stderr)
        return

    do_syslog = not args.netflow_only
    do_netflow = not args.syslog_only
    for spec in specs:
        if ":" in spec:
            sys.exit(f"endpoint '{spec}' has a port. Endpoints are addresses only — "
                     f"set ports with --syslog-port / --netflow-port.")
    syslog_t = [Target(s, args.syslog_port) for s in specs] if do_syslog else []
    netflow_t = [Target(s, args.netflow_port) for s in specs] if do_netflow else []

    eps = args.eps * args.rate
    fps = args.fps * args.rate
    per = max(1, min(args.per_packet, 30))

    print(f"push_telemetry → {len(specs)} endpoints", file=sys.stderr)
    if do_syslog:
        print(f"  syslog  udp/{args.syslog_port}  {eps:,.0f} eps  "
              f"(x{len(specs)} = {eps * len(specs):,.0f} datagrams/s)", file=sys.stderr)
    if do_netflow:
        print(f"  netflow udp/{args.netflow_port}  {fps:,.0f} flows/s  "
              f"({per}/datagram)", file=sys.stderr)
    print("  ctrl-c to stop", file=sys.stderr)

    stop = threading.Event()
    start = time.time()
    threads = []
    if do_syslog:
        threads.append(threading.Thread(target=pump, args=(
            "syslog", syslog_t, eps,
            lambda seq: (syslog_datagram(time.time(), args.max_datagram), 1),
            args, stop), daemon=True))
    if do_netflow:
        threads.append(threading.Thread(target=pump, args=(
            "netflow", netflow_t, fps / per,
            lambda seq: (netflow_packet(seq, per), per),
            args, stop), daemon=True))
    for t in threads:
        t.start()

    try:
        last = start
        while any(t.is_alive() for t in threads):
            time.sleep(0.2)
            now = time.time()
            if now - last >= args.report_every:
                dur = now - start
                ev = syslog_t[0].sent if syslog_t else 0
                fl = netflow_t[0].sent if netflow_t else 0
                by = (sum(t.bytes for t in syslog_t) + sum(t.bytes for t in netflow_t))
                errs = sum(t.errors for t in syslog_t + netflow_t)
                print(f"  [{dur:6.0f}s] {ev:>10,} ev  {fl:>9,} flows  "
                      f"{by / dur * 86400 / 1024 ** 3:>7.1f} GiB/day egress"
                      + (f"  ERRORS={errs:,}" if errs else ""), file=sys.stderr)
                last = now
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=2)
        dur = max(time.time() - start, 1e-9)
        if syslog_t:
            report("syslog", syslog_t, dur, "events")
        if netflow_t:
            report("netflow", netflow_t, dur, "flows")
        print(file=sys.stderr)


if __name__ == "__main__":
    main()
