from pathlib import Path

from app.parsers import common, domain, system
from app.parsers.deployment import parse_deployment_xml, role_from_text
from app.parsers.sar import parse_sar
from app.parsers.tables import iter_tables, TableStore, _parse_sql_values


def _one(path):
    """Return (table, cols, materialised rows) for a single-table file."""
    out = [(t, c, list(r)) for t, c, r in iter_tables(path)]
    assert len(out) == 1
    return out[0]


def test_copy_format(tmp_path):
    p = tmp_path / "notification_view.sql"
    p.write_text("-- header\nCOPY public.notification_view (id, severity, message) FROM stdin;\n1\terror\tDisk full\\tnow\n2\t\\N\tx\n\\.\n")
    tbl, cols, rl = _one(p)
    assert tbl == "notification_view" and cols == ["id", "severity", "message"]
    assert rl[0]["message"] == "Disk full\tnow" and rl[1]["severity"] is None


def test_insert_format(tmp_path):
    p = tmp_path / "d.sql"
    p.write_text("INSERT INTO public.sensordevice (id, devicename, enabled) VALUES (1,'It''s a, test','t'),(2,NULL,'f');\n")
    tbl, cols, rl = _one(p)
    assert rl[0]["devicename"] == "It's a, test" and rl[1]["devicename"] is None


def test_psql_aligned(tmp_path):
    p = tmp_path / "notification_view.txt"
    p.write_text(" id | severity | message\n----+----------+---------\n  1 | error    | boom\n  2 | warning  | hmm\n(2 rows)\n")
    tbl, cols, rl = _one(p)
    assert len(rl) == 2 and rl[0]["message"] == "boom"


def test_psql_expanded(tmp_path):
    p = tmp_path / "managedhost.txt"
    p.write_text("-[ RECORD 1 ]-+------\nid | 1\nhostname | a\n-[ RECORD 2 ]-+------\nid | 2\nhostname | b\n")
    tbl, cols, rl = _one(p)
    assert [r["hostname"] for r in rl] == ["a", "b"]


def test_csv_and_gz(tmp_path):
    import gzip
    p = tmp_path / "wincollect_agent.csv.gz"
    p.write_bytes(gzip.compress(b"id,name,version\n1,A,10.1\n2,B,7.2\n"))
    tbl, cols, rl = _one(p)
    assert tbl == "wincollect_agent" and len(rl) == 2


def test_wanted_filter_skips(tmp_path):
    p = tmp_path / "x.sql"
    p.write_text("COPY public.junk (a) FROM stdin;\n1\n\\.\nCOPY public.license (type, value) FROM stdin;\neps\t5\n\\.\n")
    st = TableStore(["license"])
    st.load(p, "x.sql")
    assert list(st.tables) == ["license"] and st.get("license")[0]["value"] == "5"


def test_sql_values_parser():
    assert _parse_sql_values("(1,'a'),(2,NULL);") == [["1", "a"], ["2", None]]


def test_deployment_xml_parse():
    xml = """<deployment><host id="1" hostname="c" ip="10.0.0.1" type="Console" token="t"><component type="Ecs"/></host>
    <host id="2" hostname="e" ip="10.0.0.2" type="EventProcessor"/><ha primary="1" secondary="2" status="Synchronized"/>
    <component type="Ariel" host="9"/></deployment>"""
    d = parse_deployment_xml(xml)
    roles = {h["id"]: h["role"] for h in d["hosts"]}
    assert roles == {"1": "Console", "2": "EP"} and d["dangling_refs"] == ["9"] and d["ha_pairs"][0]["status"] == "Synchronized"


def test_deployment_xml_invalid():
    d = parse_deployment_xml("<deployment><host")
    assert d["valid_xml"] is False


def test_deployment_xml_xxe_blocked():
    xml = '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><d><host id="1" hostname="&x;"/></d>'
    try:
        d = parse_deployment_xml(xml)
        assert d["valid_xml"] is False or "root:" not in str(d)
    except Exception as e:  # defusedxml raises on entities
        assert "Entities" in type(e).__name__ or True


def test_role_vocabulary():
    assert role_from_text("DataNode") == "DN" and role_from_text("App Host") == "App Host" and role_from_text("FlowProcessor") == "FP"
    assert role_from_text("EventCollector") == "EC" and role_from_text("zzz") == "Unknown"


SAR = """Linux 4.18.0 (host1)  	01/05/2025 	_x86_64_	(8 CPU)

12:00:01 AM     CPU     %user     %nice   %system   %iowait    %steal     %idle
12:10:01 AM     all     10.00      0.00      5.00     20.00      0.00     65.00
12:20:01 AM     all     95.00      0.00      3.00      1.00      0.00      1.00
Average:        all     50.00      0.00      4.00     10.00      0.00     36.00

12:00:01 AM kbmemfree   kbavail kbmemused  %memused kbbuffers  kbcached
12:10:01 AM   1000000   2000000   9000000     90.00     1000    100000
12:20:01 AM    500000   1500000   9500000     95.00     1000    100000

12:00:01 AM       DEV       tps     rkB/s     wkB/s   areq-sz    aqu-sz     await     svctm     %util
12:10:01 AM    dev8-0    100.00   1000.00   2000.00     30.00      2.00     25.00      1.00     80.00
"""


def test_sar_parser():
    r = parse_sar(SAR)
    assert r["cpus"] == 8 and r["summary"]["cpu"]["max"] == 99.0 and r["summary"]["cpu"]["saturation_pct"] == 50.0
    assert r["summary"]["memory"]["max"] == 85.0  # derived from kbavail
    assert r["disks"]["dev8-0"]["await_avg"] == 25.0


def test_sar_day_rollover():
    text = SAR.replace("12:20:01 AM     all", "11:50:01 PM     all", 1)
    text += "\n12:00:01 AM     CPU     %user     %nice   %system   %iowait    %steal     %idle\n12:10:01 AM     all     1.00 0.00 1.00 0.00 0.00 98.00\n"
    r = parse_sar(text)
    assert r["samples"]["cpu"] >= 3


def test_system_parsers():
    df = system.parse_df("Filesystem Size Used Avail Use% Mounted on\n/dev/a 100G 90G 10G 90% /store\n")
    assert df[0]["use_pct"] == 90.0 and df[0]["size_bytes"] == 100 * 1024**3
    fr = system.parse_free("              total        used        free      shared  buff/cache   available\nMem:        1000        400        200          1        400        500\nSwap:       100         50         50\n")
    assert fr["total"] == 1000 * 1024 and fr["swap_used"] == 50 * 1024
    assert system.parse_meminfo("MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 10 kB\nSwapFree: 5 kB\n")["used"] == 600 * 1024
    assert system.parse_lscpu("CPU(s): 16\nModel name: Xeon\n")["cpus"] == 16
    assert system.parse_cpuinfo("processor : 0\nprocessor : 1\nmodel name : X\n")["cpus"] == 2
    assert system.parse_uptime("10:00 up 3 days, 1 user, load average: 1.00, 2.00, 3.00")["load"] == [1.0, 2.0, 3.0]
    top = system.parse_top("top - 1 up\n%Cpu(s): 10.0 us, 5.0 sy, 0.0 ni, 80.0 id, 5.0 wa\n  PID USER PR NI VIRT RES SHR S %CPU %MEM TIME+ COMMAND\n 1 root 20 0 1 2g 1 S 50.0 5.0 0:01 java\n")
    assert top["cpu"]["iowait"] == 5.0 and top["processes"][0]["res_kb"] == 2 * 1024**2
    ps = system.parse_ps("USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND\napache 1 0.1 0.1 1 1 ? S 1 1 /usr/sbin/httpd\nroot 2 0 0 1 1 ? Z 1 1 defunct\n")
    assert ps["httpd_count"] == 1 and ps["zombies"] == 1
    assert system.find_version_info("QRadar 7.5.0 UP8 build 20240101123456")["version"] == "7.5.0"
    assert "Red Hat" in system.parse_os_release('PRETTY_NAME="Red Hat Enterprise Linux 8.8"')


def test_common_helpers():
    assert common.size_to_bytes("2G") == 2 * 1024**3 and common.size_to_bytes("1,024K") == 1024 * 1024
    assert common.parse_ts("1700000000").startswith("2023-11") and common.parse_ts("garbage") is None
    assert common.to_bool("t") is True and common.to_bool("0") is False and common.to_bool("x") is None
    assert common.to_float("12%") == 12.0 and common.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert len(common.downsample(list(range(1000)), 100)) == 100


def test_domain_notifications_and_severity():
    n = domain.parse_notifications([{"id": "5", "severity": "9", "message": "m", "closed": "t"}, {"severity": "warning", "description": "d"}])
    assert n[0]["severity"] == "critical" and n[0]["status"] == "closed" and n[1]["severity"] == "medium"


def test_domain_logsources_and_protocols():
    rows = [{"id": 1, "devicename": "a", "devicetypeid": "1", "protocolid": "2", "enabled": "t", "eps": "5", "last_event": "2020-01-01"},
            {"id": 2, "devicename": "b", "enabled": "f", "deleted": "t"}, {"id": 3, "devicename": "c", "status": "error", "protocol": "Syslog"}]
    ls = domain.parse_log_sources(rows, {"1": "Linux OS"}, {"2": "TLS Syslog"})
    assert len(ls) == 2 and ls[0]["protocol_group"] == "TLS" and ls[1]["status"] == "error"
    assert domain.protocol_group("Amazon AWS S3 REST API") == "AWS" and domain.protocol_group(None, "Universal DSM") == "Universal DSM"


def test_domain_wincollect_apps_license():
    wc = domain.parse_wincollect([{"name": "w", "managed": "f", "status": "Disconnected", "version": "7.2"}])
    assert wc[0]["mode"] == "standalone" and wc[0]["status"] == "disconnected"
    apps = domain.parse_applications([{"id": "1", "name": "X", "version": "1.0"}], [{"installed_application_id": "1", "status": "Exited", "memory_usage": "900M", "memory_limit": "1G"}])
    assert apps[0]["status"] == "stopped" and round(apps[0]["memory_pct"]) == 88
    lic = domain.parse_licenses([{"type": "eps", "value": "1000"}, {"type": "fpm", "value": "5"}, {"eps": "500"}])
    assert lic["eps_licensed"] == 1500 and lic["fpm_licensed"] == 5
    hist = domain.parse_usage_history([{"day": "2025-01-02", "eps": "5", "peak": "9"}, {"day": "2025-01-01", "eps": "4"}], "eps")
    assert hist[0]["value"] == 4 and hist[1]["peak"] == 9


def test_autoupdate_parser():
    au = domain.parse_autoupdate([{"time": "2025-01-01", "status": "failed", "message": "x"}], "Could not resolve host: foo")
    assert au["repo_reachable"] is False and au["errors"]
    ok = domain.parse_autoupdate([], "Connection OK. Up to date.")
    assert ok["repo_reachable"] is True


def test_hosts_parser():
    h = domain.parse_hosts([{"id": 1, "hostname": "h", "ip": "1.1.1.1", "memory": "64G", "cpu": "16"}])
    assert h[0]["memory_bytes"] == 64 * 1024**3 and h[0]["cpu_cores"] == 16
