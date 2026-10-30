#!/usr/bin/env python3
"""Generate a realistic *synthetic* QRadar get_logs bundle for demos, QA and automated tests.

The content is fabricated (no customer data) but mirrors the layout the platform parses:
  * <console>/deployment.xml
  * per-host directories with df / free / top / ps / lscpu / sar outputs
  * PostgreSQL table exports (COPY format) – notification_view, managedhost, sensordevice, wincollect, applications, licences, usage history
  * auto_update logs and version files

Usage:  python tools/make_sample_getlogs.py out.tar.gz [--profile healthy|troubled] [--seed N]
"""
from __future__ import annotations

import argparse
import io
import random
import tarfile
from datetime import datetime, timedelta, timezone

HOSTS = [  # (id, hostname, ip, role/type, cpus, ram_gb, disk_gb)
    (53, "qr-console01", "10.10.1.10", "Console", 32, 128, 8000),
    (55, "qr-ep01", "10.10.1.21", "EventProcessor", 24, 64, 12000),
    (56, "qr-ec01", "10.10.1.22", "EventCollector", 16, 32, 2000),
    (57, "qr-fp01", "10.10.1.23", "FlowProcessor", 16, 64, 4000),
    (58, "qr-apphost01", "10.10.1.30", "AppHost", 16, 64, 2000),
    (59, "qr-dn01", "10.10.1.40", "DataNode", 24, 64, 20000),
]


def copy_block(table: str, cols: list[str], rows: list[list]) -> str:
    out = [f"COPY public.{table} ({', '.join(cols)}) FROM stdin;"]
    for r in rows:
        out.append("\t".join("\\N" if v is None else str(v).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ") for v in r))
    out.append("\\.\n")
    return "\n".join(out)


def deployment_xml(profile: str) -> str:
    hosts = []
    for hid, name, ip, role, *_ in HOSTS:
        ha = ""
        if profile == "healthy" and name == "qr-console01":
            ha = ' ha_peer="qr-console02" ha_role="primary" ha_status="Synchronized"'
        hosts.append(f'  <host id="{hid}" hostname="{name}" ip="{ip}" type="{role}" status="{"error" if profile == "troubled" and name == "qr-ec01" else "active"}" version="7.5.0" token="tok-{hid}"{ha}>\n'
                     f'    <component type="{role}" name="{role.lower()}-{hid}"/>\n  </host>')
    if profile == "healthy":
        hosts.append('  <host id="54" hostname="qr-console02" ip="10.10.1.11" type="Console" status="active" version="7.5.0" token="tok-54" ha_peer="qr-console01" ha_role="secondary" ha_status="Synchronized"/>')
    comp = '  <component type="Ecs" host="999" name="orphan-ecs"/>\n' if profile == "troubled" else ""
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<deployment version="7.5.0">\n' + "\n".join(hosts) + f"\n{comp}</deployment>\n"


def sar_text(host_name: str, cpus: int, profile: str, rnd: random.Random, day: datetime) -> str:
    lines = [f"Linux 4.18.0-513.el8.x86_64 ({host_name})\t{day:%m/%d/%Y}\t_x86_64_\t({cpus} CPU)\n"]
    stress = profile == "troubled" and host_name in ("qr-ep01", "qr-console01")
    times = [day.replace(hour=0, minute=0, second=0) + timedelta(minutes=10 * i) for i in range(144)]

    def hdr(t, cols):
        return f"{t:%I:%M:%S %p}     {cols}"

    out = [lines[0]]
    out.append(hdr(times[0], "CPU     %user     %nice   %system   %iowait    %steal     %idle"))
    for t in times:
        busy = 55 + 30 * (0.5 + 0.5 * __import__("math").sin(t.hour / 24 * 6.28)) if stress else 22 + 12 * (0.5 + 0.5 * __import__("math").sin(t.hour / 24 * 6.28))
        iow = rnd.uniform(14, 28) if stress else rnd.uniform(0.2, 2.0)
        user = max(busy - 8, 3) + rnd.uniform(-3, 3)
        sysc = 6 + rnd.uniform(-1, 1)
        idle = max(0.0, 100 - user - sysc - iow - 0.2)
        out.append(f"{t:%I:%M:%S %p}     all     {user:6.2f}      0.00     {sysc:6.2f}     {iow:6.2f}      0.20     {idle:6.2f}")
    out.append("")
    out.append(hdr(times[0], "kbmemfree   kbavail kbmemused  %memused kbbuffers  kbcached  kbcommit   %commit  kbactive   kbinact   kbdirty"))
    total = 64 * 1024 * 1024
    for t in times:
        used_pct = rnd.uniform(90, 96) if stress else rnd.uniform(48, 62)
        used = int(total * used_pct / 100)
        out.append(f"{t:%I:%M:%S %p}   {total - used:9d} {int((total - used) * 1.2):9d} {used:9d}     {used_pct:5.2f}    120000   9000000  30000000     40.00  20000000   5000000       200")
    out.append("")
    out.append(hdr(times[0], "kbswpfree kbswpused  %swpused  kbswpcad   %swpcad"))
    for t in times:
        sw = rnd.uniform(18, 35) if stress else 0.0
        out.append(f"{t:%I:%M:%S %p}   {int(8e6 * (1 - sw / 100)):9d} {int(8e6 * sw / 100):9d}     {sw:5.2f}         0      0.00")
    out.append("")
    out.append(hdr(times[0], "runq-sz  plist-sz   ldavg-1   ldavg-5  ldavg-15   blocked"))
    for t in times:
        l1 = rnd.uniform(cpus * 1.1, cpus * 2.2) if stress else rnd.uniform(1, cpus * 0.3)
        out.append(f"{t:%I:%M:%S %p}       {int(l1)}       812     {l1:5.2f}     {l1 * 0.95:5.2f}     {l1 * 0.9:5.2f}         0")
    out.append("")
    out.append(hdr(times[0], "DEV       tps     rkB/s     wkB/s   areq-sz    aqu-sz     await     svctm     %util"))
    for t in times:
        aw = rnd.uniform(22, 70) if stress else rnd.uniform(1.0, 6.0)
        out.append(f"{t:%I:%M:%S %p}     dev8-0   {rnd.uniform(80, 400):7.2f}  {rnd.uniform(500, 6000):8.2f}  {rnd.uniform(1000, 25000):8.2f}     38.10     {aw / 8:5.2f}   {aw:7.2f}      1.10     {min(100, aw * 1.3):5.1f}")
    out.append("")
    out.append(hdr(times[0], "IFACE   rxpck/s   txpck/s    rxkB/s    txkB/s   rxcmp/s   txcmp/s  rxmcst/s   %ifutil"))
    for t in times:
        out.append(f"{t:%I:%M:%S %p}     eth0  {rnd.uniform(2000, 9000):8.2f}  {rnd.uniform(1500, 6000):8.2f}  {rnd.uniform(800, 4000):9.2f}  {rnd.uniform(600, 3000):9.2f}      0.00      0.00      0.10      3.20")
    out.append("")
    out.append(hdr(times[0], "IFACE   rxerr/s   txerr/s    coll/s  rxdrop/s  txdrop/s  txcarr/s  rxfram/s  rxfifo/s  txfifo/s"))
    for t in times:
        d = rnd.uniform(0, 12) if profile == "troubled" and host_name == "qr-ec01" else 0.0
        out.append(f"{t:%I:%M:%S %p}     eth0      0.00      0.00      0.00 {d:9.2f}      0.00      0.00      0.00      0.00      0.00")
    return "\n".join(out) + "\n"


def top_text(stress: bool, rnd: random.Random) -> str:
    procs = [("ecs-ep", 85 if stress else 24), ("postgres", 48 if stress else 11), ("java", 40 if stress else 14), ("ariel_proxy_server", 22 if stress else 6), ("httpd", 6), ("tomcat", 12), ("docker", 8)]
    out = ["top - 10:15:01 up 94 days,  3:21,  1 user,  load average: 21.30, 19.80, 18.11", "Tasks: 612 total,   4 running", "%Cpu(s): 62.0 us,  9.0 sy,  0.0 ni, 14.0 id, 14.5 wa,  0.0 hi,  0.5 si,  0.0 st" if stress else "%Cpu(s): 18.0 us,  5.0 sy,  0.0 ni, 76.0 id,  0.8 wa,  0.0 hi,  0.2 si,  0.0 st", "", "  PID USER      PR  NI    VIRT    RES    SHR S  %CPU  %MEM     TIME+ COMMAND"]
    for i, (n, c) in enumerate(procs):
        out.append(f"{1000 + i:5d} root      20   0 8123456 {rnd.randint(300, 9000)}m  12000 S {c:5.1f}  {rnd.uniform(1, 18):4.1f}  120:00.00 {n}")
    return "\n".join(out) + "\n"


def df_text(profile: str, name: str) -> str:
    full = profile == "troubled" and name in ("qr-ep01", "qr-dn01")
    rows = [("/dev/mapper/rhel-root", 100, 41), ("/dev/sda1", 1, 28), ("/dev/mapper/storerhel-store", 8000, 93 if full else 54), ("/dev/mapper/storerhel-transient", 400, 31),
            ("/dev/mapper/rhel-var_log", 50, 96 if full else 38), ("/dev/mapper/storerhel-storetmp", 30, 22)]
    mounts = ["/", "/boot", "/store", "/transient", "/var/log", "/storetmp"]
    out = ["Filesystem                          Size  Used Avail Use% Mounted on"]
    for (dev, gb, pct), m in zip(rows, mounts):
        used = gb * pct / 100
        out.append(f"{dev:35s} {gb:4d}G {used:4.0f}G {gb - used:4.0f}G  {pct}% {m}")
    return "\n".join(out) + "\n"


def tables(profile: str, rnd: random.Random) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    t: dict[str, str] = {}
    mh = [[h[0], h[1], h[2], h[3], "active" if not (profile == "troubled" and h[1] == "qr-ec01") else "error", "7.5.0", h[4], h[5] * 1024**3, h[6] * 1024**3] for h in HOSTS]
    t["managedhost"] = copy_block("managedhost", ["id", "hostname", "ip", "appliance_type", "status", "version", "cpu", "memory", "disk"], mh)
    notif = [
        [1, "error" if profile == "troubled" else "warning", "Disk usage on /store has exceeded 93% on qr-ep01", "qr-ep01", 0, (now - timedelta(hours=3)).isoformat()],
        [2, "critical", "License EPS threshold exceeded: current 28,400 EPS exceeds licensed 25,000 EPS", "qr-console01", 0, (now - timedelta(days=1)).isoformat()],
        [3, "warning", "Auto update failed: unable to connect to the update server public.dhe.ibm.com", "qr-console01", 0, (now - timedelta(days=2)).isoformat()],
        [4, "error", "Events were not parsed: Unknown log source type for 14 sources", "qr-ec01", 0, (now - timedelta(hours=9)).isoformat()],
        [5, "warning", "Backup failed: unable to write to /store/backup", "qr-console01", 0, (now - timedelta(days=3)).isoformat()],
        [6, "error", "WinCollect agents disconnected: 12 agents have not checked in", "qr-ec01", 0, (now - timedelta(hours=20)).isoformat()],
        [7, "warning", "Application ThreatIntel container restarted unexpectedly", "qr-apphost01", 0, (now - timedelta(hours=5)).isoformat()],
        [8, "warning", "HA cluster qr-console01 is not synchronized (DRBD Inconsistent)", "qr-console01", 0, (now - timedelta(hours=2)).isoformat()],
        [9, "info", "Scheduled report generation completed", "qr-console01", 1, (now - timedelta(days=4)).isoformat()],
        [10, "warning", "Ariel searches are slow: 17 searches queued", "qr-ep01", 0, (now - timedelta(hours=1)).isoformat()],
        [11, "error", "Managed host qr-ec01 is not responding (hostcontext down)", "qr-ec01", 0, (now - timedelta(hours=6)).isoformat()],
        [12, "warning", "Events dropped: event pipeline queue overflow on qr-ep01", "qr-ep01", 0, (now - timedelta(minutes=50)).isoformat()],
    ] if profile == "troubled" else [
        [1, "info", "Scheduled report generation completed", "qr-console01", 1, (now - timedelta(days=4)).isoformat()],
        [2, "warning", "Auto update failed: unable to connect to the update server", "qr-console01", 0, (now - timedelta(days=9)).isoformat()],
        [3, "warning", "Disk usage on /store reached 81%", "qr-ep01", 0, (now - timedelta(days=1)).isoformat()],
    ]
    t["notification_view"] = copy_block("notification_view", ["id", "severity", "message", "host", "closed", "create_time"], notif)
    types = {1: "Microsoft Windows Security Event Log", 2: "Linux OS", 3: "Palo Alto PA Series", 4: "Cisco ASA", 5: "Universal DSM", 6: "AWS CloudTrail", 7: "Office 365 Message Trace", 8: "Oracle Database Listener", 9: "Check Point", 10: "SIM Generic Log DSM"}
    protocols = {1: "WinCollect", 2: "Syslog", 3: "TLS Syslog", 4: "UDP Multiple", 5: "JDBC", 6: "Amazon AWS S3 REST API", 7: "Office 365 Message Trace REST API", 8: "Log File", 9: "OPSEC/LEA", 10: "SNMPv3", 11: "Microsoft Azure Event Hubs"}
    t["sensordevicetype"] = copy_block("sensordevicetype", ["id", "name"], [[k, v] for k, v in types.items()])
    t["sensorprotocol"] = copy_block("sensorprotocol", ["id", "name"], [[k, v] for k, v in protocols.items()])
    n_ls = 140 if profile == "troubled" else 60
    ls_rows = []
    for i in range(n_ls):
        tid = rnd.choice(list(types))
        pid = {1: 1, 2: 2, 3: 3, 4: 4, 5: 2, 6: 6, 7: 7, 8: 5, 9: 9, 10: 8}[tid]
        r = rnd.random()
        status = "error" if profile == "troubled" and r < 0.08 else "disabled" if r < 0.14 else "enabled"
        silent = profile == "troubled" and 0.08 <= r < 0.2
        last = now - (timedelta(days=rnd.randint(3, 40)) if silent else timedelta(minutes=rnd.randint(1, 50)))
        eps = round(rnd.expovariate(1 / 120) if status == "enabled" and not silent else 0, 2)
        ls_rows.append([i + 1, f"{types[tid].split()[0]}-{i + 1:03d}", f"10.20.{i // 250}.{i % 250 + 1}", tid, pid, "t" if status != "disabled" else "f", status if status == "error" else "", eps, last.isoformat(), "f"])
    t["sensordevice"] = copy_block("sensordevice", ["id", "devicename", "deviceid", "devicetypeid", "protocolid", "enabled", "status", "eps", "last_event", "deleted"], ls_rows)
    n_agents = 95
    wc = []
    for i in range(n_agents):
        ver = rnd.choices(["10.1.8", "10.1.5", "7.3.1", "7.2.9"], weights=[50, 25, 15, 10] if profile == "troubled" else [80, 15, 4, 1])[0]
        disc = profile == "troubled" and rnd.random() < 0.13
        managed = rnd.random() > (0.2 if profile == "troubled" else 0.04)
        wc.append([i + 1, f"WIN-SRV{i + 1:03d}", f"10.30.{i // 250}.{i % 250 + 1}", ver, "t" if managed else "f", "disconnected" if disc else "connected", "qr-ec01" if managed else None,
                   (now - (timedelta(days=5) if disc else timedelta(minutes=rnd.randint(1, 30)))).isoformat(), "Certificate verification failed" if disc and rnd.random() < 0.3 else None])
    t["wincollect_agent"] = copy_block("wincollect_agent", ["id", "name", "ip", "version", "managed", "status", "destination", "last_checkin", "config_error"], wc)
    apps = [[1, "Log Source Management", "7.0.3", "7.0.5"], [2, "Pulse", "2.2.1", None], [3, "ThreatIntel", "3.1.0", "3.2.0"], [4, "User Behavior Analytics", "4.1.2", None], [5, "QRadar Assistant", "3.0.4", None], [6, "Use Case Manager", "3.9.0", "3.10.0"]]
    t["installed_application"] = copy_block("installed_application", ["id", "name", "version", "latest_version"], apps)
    inst = []
    for a in apps:
        bad = profile == "troubled" and a[1] in ("ThreatIntel", "User Behavior Analytics", "Pulse")
        status = "running" if not bad else {"ThreatIntel": "degraded", "User Behavior Analytics": "error", "Pulse": "running"}[a[1]]
        inst.append([a[0], a[0], "qr-apphost01", status, round(rnd.uniform(1, 40), 1), 96.0 if a[1] == "Pulse" and profile == "troubled" else round(rnd.uniform(20, 70), 1),
                     14 if a[1] == "ThreatIntel" and profile == "troubled" else 0, "Container exited with code 137 (OOMKilled)" if a[1] == "User Behavior Analytics" and profile == "troubled" else None])
    t["installed_application_instance"] = copy_block("installed_application_instance", ["id", "installed_application_id", "managed_host", "status", "cpu_usage", "memory_percent", "restart_count", "error"], inst)
    t["license"] = copy_block("license", ["type", "value", "expiry"], [["eps", 25000, (now + timedelta(days=(45 if profile == "troubled" else 400))).isoformat()], ["fpm", 1200000, None], ["apps", 10, None]])
    eps_hist, fpm_hist = [], []
    for d in range(120, 0, -1):
        base = (17000 + (120 - d) * 85) if profile == "troubled" else (9000 + (120 - d) * 12)
        v = base + rnd.uniform(-1200, 1200)
        eps_hist.append([(now - timedelta(days=d)).date().isoformat(), round(v), round(v * 1.3)])
        fpm_hist.append([(now - timedelta(days=d)).date().isoformat(), round(v * 22), round(v * 28)])
    t["eps_history"] = copy_block("eps_history", ["day", "eps", "peak"], eps_hist)
    t["fpm_history"] = copy_block("fpm_history", ["day", "fpm", "peak"], fpm_hist)
    t["auto_update_history"] = copy_block("auto_update_history", ["time", "type", "status", "version", "message"],
                                          [[(now - timedelta(days=3)).isoformat(), "DSM", "failed" if profile == "troubled" else "success", "2024.10", "unable to connect to update server" if profile == "troubled" else None],
                                           [(now - timedelta(days=10)).isoformat(), "Protocol", "success", "2024.09", None]])
    return t


def build(path: str, profile: str, seed: int) -> None:
    rnd = random.Random(seed)
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    files: dict[str, bytes] = {}
    root = "get_logs_qr-console01"
    files[f"{root}/qr-console01/store/configservices/staging/globalconfig/deployment.xml"] = deployment_xml(profile).encode()
    files[f"{root}/qr-console01/VERSION"] = b"QRadar 7.5.0 UP8 Build 20240101123456\nIBM Security QRadar SIEM\n"
    files[f"{root}/qr-console01/system_info/dmidecode.txt"] = b"System Information\n\tManufacturer: VMware, Inc.\n\tProduct Name: VMware Virtual Platform\n"
    files[f"{root}/qr-console01/opt/qradar/conf/masterlist"] = ("\n".join(h[2] for h in HOSTS)).encode()
    for hid, name, ip, role, cpus, ram, disk in HOSTS:
        d = f"{root}/{name}_{ip}"
        files[f"{d}/hostname"] = f"{name}.corp.example\n".encode()
        files[f"{d}/df"] = df_text(profile, name).encode()
        files[f"{d}/free"] = (f"              total        used        free      shared  buff/cache   available\nMem:       {ram * 1024 * 1024}    {int(ram * 1024 * 1024 * 0.55)}      {int(ram * 1024 * 1024 * 0.1)}      1024      {int(ram * 1024 * 1024 * 0.3)}     {int(ram * 1024 * 1024 * 0.4)}\nSwap:      8388604           0     8388604\n").encode()
        files[f"{d}/lscpu"] = f"CPU(s):                {cpus}\nModel name:            Intel(R) Xeon(R) Gold 6248\nSocket(s): 2\n".encode()
        files[f"{d}/top"] = top_text(profile == "troubled" and name in ("qr-ep01", "qr-console01"), rnd).encode()
        files[f"{d}/ps"] = ("USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\n" + "\n".join(f"apache {2000 + i} 0.1 0.4 400000 90000 ? S 01:00 0:10 /usr/sbin/httpd -DFOREGROUND" for i in range(65 if profile == "troubled" and name == "qr-console01" else 12)) + "\n").encode()
        files[f"{d}/sar/sar_{day:%d}"] = sar_text(name, cpus, profile, rnd, day).encode()
        files[f"{d}/var/log/qradar.error"] = (f"Oct 12 03:11:22 {name} [hostcontext] autossh tunnel to 10.10.1.21 failed: connection refused\n" * (3 if profile == "troubled" and name == "qr-ec01" else 0)).encode()
    for tname, content in tables(profile, rnd).items():
        files[f"{root}/qr-console01/postgres/{tname}.sql"] = content.encode()
    files[f"{root}/qr-console01/var/log/autoupdate.log"] = (b"Could not resolve host: public.dhe.ibm.com\nFailed to download update package\n" if profile == "troubled" else b"Connection OK. Up to date.\n")
    with tarfile.open(path, "w:gz") as tf:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = int(datetime.now().timestamp())
            tf.addfile(ti, io.BytesIO(data))
    print(f"wrote {path}  ({len(files)} files, profile={profile})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--profile", choices=["healthy", "troubled"], default="troubled")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    build(a.out, a.profile, a.seed)
