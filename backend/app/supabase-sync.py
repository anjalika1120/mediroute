import os
import httpx
from dotenv import load_dotenv

load_dotenv()

def normalize_base_url(raw_url: str) -> str:
    """Cleans trailing slashes or accidental '/rest/v1' suffixes from Supabase URLs."""
    url = raw_url.strip().rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[:-8]
    return url

def get_configured_hospitals():
    """Loads configured hospital Supabase nodes from environment variables (with active defaults)."""
    hospitals = []

    defaults = {
        1: (
            "Sunrise Hospital",
            "https://elgzqwrnjkuqexriqwtw.supabase.co",
            "sb_publishable_GM-sDmqneHqMvPnuyleXQg_nL5neOcO",
        ),
        2: (
            "Green Valley Clinic",
            "https://ghusmdzyhwqykpxzghhc.supabase.co",
            "sb_publishable_emOKrBxBkeESy7oKry4Gaw_j023rHL7",
        ),
    }

    for i in range(1, 11):
        default_name, default_url, default_key = defaults.get(i, (f"Hospital Node {i}", "", ""))
        url = os.getenv(f"HOSPITAL_{i}_URL", default_url).strip()
        key = os.getenv(f"HOSPITAL_{i}_KEY", default_key).strip()
        label = os.getenv(f"HOSPITAL_{i}_NAME", default_name).strip()

        if url and key:
            hospitals.append({
                "id": i,
                "name": label,
                "url": normalize_base_url(url),
                "key": key,
            })

    return hospitals

def fetch_node(node):
    """Fetches facility, stock_register, and daily_usage from one independent Supabase database."""
    headers = {"apikey": node["key"]}
    base = node["url"]

    with httpx.Client(timeout=10.0) as client:
        fac = client.get(f"{base}/rest/v1/facility?select=*", headers=headers).json()
        stk = client.get(f"{base}/rest/v1/stock_register?select=*", headers=headers).json()
        usg = client.get(f"{base}/rest/v1/daily_usage?select=*", headers=headers).json()

    if not isinstance(fac, list) or not isinstance(stk, list) or not isinstance(usg, list):
        raise ValueError(f"Unexpected response from {node['name']}: {fac}")

    return fac, stk, usg

def sync_all_hospitals(extra_nodes=None):
    """Syncs all configured hospitals + any runtime-registered 3rd+ hospitals."""
    nodes = get_configured_hospitals()
    if extra_nodes:
        for n in extra_nodes:
            nodes.append({
                "id": n.get("id", len(nodes) + 1),
                "name": n["name"],
                "url": normalize_base_url(n["url"]),
                "key": n["key"].strip(),
            })

    all_facilities, all_stock, all_usage, statuses = [], [], [], []

    for node in nodes:
        try:
            fac, stk, usg = fetch_node(node)
            all_facilities.extend(fac)
            all_stock.extend(stk)
            all_usage.extend(usg)
            statuses.append({
                "node": node["name"],
                "status": "synced",
                "facilities": len(fac),
                "stock_items": len(stk),
                "usage_rows": len(usg),
            })
        except Exception as e:
            statuses.append({"node": node["name"], "status": "failed", "error": str(e)})

    return {
        "sync_report": statuses,
        "facilities": all_facilities,
        "stock_register": all_stock,
        "daily_usage": all_usage,
    }
