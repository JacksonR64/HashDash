#!/usr/bin/env python3
"""Read-only infrastructure checks. Reuses existing Proxmox monitor credentials."""
import argparse
import concurrent.futures
import json
import ssl
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from collect_host import write_module


def get_json(url, auth=None, ca=None):
    context = None
    if ca:
        context = ssl.create_default_context()
        context.load_verify_locations(cadata=ca)
    headers = {"Authorization": auth} if auth else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), context=context, timeout=4) as response:
        return json.load(response)


def resource_problems(resources, tasks, now):
    if not isinstance(resources, list) or not any(r.get("type") == "node" for r in resources):
        raise ValueError("missing node resources")
    if not isinstance(tasks, list):
        raise ValueError("missing backup tasks")
    problems = []
    for r in resources:
        kind, status = r.get("type"), r.get("status")
        name = str(r.get("name") or r.get("storage") or r.get("node") or "resource")
        if kind == "node":
            if status != "online":
                problems.append(name + " offline")
            elif r.get("maxmem") and r.get("mem", 0) / r["maxmem"] > .92:
                problems.append(name + " RAM >92%")
        elif kind in ("lxc", "qemu") and not r.get("template") and status != "running":
            if "optional" not in str(r.get("tags", "")).split(";"):
                problems.append(name + " " + str(status))
        elif kind == "storage":
            if status != "available":
                problems.append(name + " storage unavailable")
            elif r.get("maxdisk") and r.get("disk", 0) / r["maxdisk"] > .85:
                problems.append(name + " >85% full")
    for task in tasks:
        status = str(task.get("status", ""))
        if task.get("type") == "vzdump" and task.get("endtime", 0) > now - 93600:
            if status and status != "OK" and not status.startswith("WARNINGS"):
                problems.append("backup failed on " + str(task.get("node", "host")))
    return problems


def pve_check(site):
    resources = get_json(site["url"], site["auth"], site["ca"])["data"]
    tasks = get_json(site["url"].rsplit("/", 1)[0] + "/tasks", site["auth"], site["ca"])["data"]
    problems = resource_problems(resources, tasks, datetime.now(timezone.utc).timestamp())
    if any(r.get("type") == "node" and r.get("status") == "offline" for r in resources):
        return "fault", "; ".join(problems)
    return ("warning", "; ".join(problems)) if problems else ("ok", "Host, guests, storage and recent backup errors checked")


def ha_check(url):
    data = get_json(url)
    if not isinstance(data, dict) or not data.get("name"):
        raise ValueError("invalid Home Assistant manifest")
    return "ok", "Home Assistant HTTP endpoint responding"


def router_check(url):
    data = get_json(url)
    stamp = datetime.fromisoformat(data["ts"]).replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    if not -60 <= age <= 180:
        return "unknown", "OpenWrt port monitor stale"
    return "ok", "OpenWrt HTTP and port-monitor heartbeat responding"


def internet_check(url):
    data = get_json(url)
    stamp = datetime.fromisoformat(data["ts"]).replace(tzinfo=timezone.utc)
    if not -60 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 900:
        return "unknown", "Router WAN check stale"
    preferred = data.get("preferred")
    if preferred not in ("5G", "ADSL"):
        return "unknown", "Router active WAN unknown"
    suffix = "adsl" if preferred == "ADSL" else "5g"
    online = data.get("wan2_state" if suffix == "adsl" else "wan_state") == "online"
    loss = data.get("loss_" + suffix)
    if not online or loss is None:
        return "unknown", "No current positive WAN check"
    if not isinstance(loss, (int, float)) or not 0 <= loss <= 100:
        return "unknown", "Invalid router WAN result"
    if loss > 20:
        return "warning", str(preferred) + " loss " + str(loss) + "%"
    return "ok", "Router " + str(preferred) + " check / loss " + str(loss) + "%"


def tailnet_checks(m5_ip):
    result = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=4, check=True)
    data = json.loads(result.stdout)
    if data.get("BackendState") in ("Stopped", "NeedsLogin", "NeedsMachineAuth"):
        tailnet = ("fault", "Tailscale backend not running")
    elif data.get("BackendState") != "Running":
        tailnet = ("unknown", "Tailscale backend state unavailable or starting")
    elif data.get("Health"):
        detail = "; ".join(data["Health"])
        if detail == "Some peers are advertising routes but --accept-routes is false":
            detail = "Routes not accepted (existing setting)"
        tailnet = ("warning", detail)
    else:
        tailnet = ("ok", "Tailscale backend running without health warnings")
    peer = next((p for p in data.get("Peer", {}).values() if m5_ip in p.get("TailscaleIPs", [])), None)
    m5 = ("unknown", "M5 not found in peer map") if peer is None else (
        ("ok", "M5 online in Tailscale peer map") if peer.get("Online") else ("offline", "M5 offline/asleep in Tailscale peer map"))
    return tailnet, m5


def collect(config, directory):
    checks = [("i7", "i7/PVE", pve_check, config["i7"]), ("i5", "i5/PVE", pve_check, config["i5"]),
              ("ha_flat", "HAflat", ha_check, config["ha_flat"]), ("ha_house", "HAhouse", ha_check, config["ha_house"]),
              ("router", "OpenWrt", router_check, config["router"]), ("internet", "Net", internet_check, config["internet"])]
    items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        pending = [(key, label, pool.submit(function, arg)) for key, label, function, arg in checks]
        tailnet = pool.submit(tailnet_checks, config["m5_ip"])
        for key, label, future in pending:
            try:
                status, detail = future.result()
            except Exception as error:
                reason = getattr(error, "reason", error)
                if isinstance(reason, ssl.SSLCertVerificationError):
                    status, detail = "warning", ("TLS certificate expired" if "expired" in str(reason) else "TLS verification failed")
                else:
                    status, detail = "unknown", "Check unavailable (" + type(error).__name__ + ")"
            items.append({"key": key, "label": label, "status": status, "detail": detail})
        try:
            ts, m5 = tailnet.result()
        except Exception as error:
            ts = m5 = ("unknown", "Check unavailable (" + type(error).__name__ + ")")
        items += [{"key": key, "label": label, "status": value[0], "detail": value[1]}
                  for key, label, value in (("m5", "M5", m5), ("tailscale", "TS", ts))]
    write_module(directory, "health", [item["label"] + ": " + item["status"] + " / " + item["detail"] for item in items], items=items)
    print("health: refreshed (read-only)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/console-dashboard/health-sources.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("/var/lib/console-clock/dashboard"))
    args = parser.parse_args()
    collect(json.loads(args.config.read_text()), args.data_dir)
