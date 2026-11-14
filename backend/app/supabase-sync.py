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
import math
from datetime import datetime, timedelta
from app import db

def _haversine_transit_days(lat1, lon1, lat2, lon2):
    """Calculates realistic inter-hospital transit days from coordinates (minimum 1 day)."""
    if None in (lat1, lon1, lat2, lon2):
        return 1
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    km = 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    # Local NCR transfers (< 40 km) take 1 day; longer distances add 1 day per 150 km
    return max(1, math.ceil(km / 150.0))

def apply_sync_to_sqlite(sync_payload):
    """Writes synced Supabase facilities, stock, and 60-day usage into mediflow.db."""
    facilities = sync_payload.get("facilities", [])
    stock_rows = sync_payload.get("stock_register", [])
    usage_rows = sync_payload.get("daily_usage", [])

    if not facilities or not stock_rows:
        return {"updated": False, "reason": "No facility or stock rows returned from Supabase"}

    # Map Supabase text facility_id (e.g. 'HOSP_SUNRISE') -> facility metadata & lead_days
    fac_meta = {f["facility_id"]: f for f in facilities}
    lead_by_fac = {}
    for s in stock_rows:
        fid = s["facility_id"]
        if fid not in lead_by_fac and s.get("lead_days") is not None:
            lead_by_fac[fid] = int(s["lead_days"])

    # Determine the 60-day window (day 0..59, oldest first) ending at the latest usage_date
    parsed_dates = []
    for u in usage_rows:
        if u.get("usage_date"):
            parsed_dates.append(datetime.strptime(str(u["usage_date"])[:10], "%Y-%m-%d").date())
    max_date = max(parsed_dates) if parsed_dates else datetime.utcnow().date()
    start_date = max_date - timedelta(days=59)

    c = db.conn()
    try:
        db.clear(c)
        sqlite_fac_ids = {}

        # 1. Insert Facilities
        for fid, f in fac_meta.items():
            sql_id = db.get_id(
                c,
                "facilities",
                f["name"],
                lead_days=lead_by_fac.get(fid, 4),
                locality=f.get("locality"),
                latitude=f.get("latitude"),
                longitude=f.get("longitude"),
            )
            sqlite_fac_ids[fid] = sql_id

        # 2. Insert Medicines & Batches (from stock_register)
        for s in stock_rows:
            fid = s["facility_id"]
            if fid not in sqlite_fac_ids:
                continue
            med_id = db.get_id(c, "medicines", s["medicine"])
            c.execute(
                "INSERT INTO batches(facility_id, medicine_id, quantity, expiry_days, incoming_qty) VALUES(?,?,?,?,?)",
                (
                    sqlite_fac_ids[fid],
                    med_id,
                    s.get("stock"),
                    s.get("expiry_days"),
                    s.get("incoming", 0),
                ),
            )

        # 3. Insert 60-Day Usage History (day 0..59)
        for u in usage_rows:
            fid = u["facility_id"]
            if fid not in sqlite_fac_ids or not u.get("usage_date"):
                continue
            u_date = datetime.strptime(str(u["usage_date"])[:10], "%Y-%m-%d").date()
            day_idx = (u_date - start_date).days
            if 0 <= day_idx < 60:
                med_id = db.get_id(c, "medicines", u["medicine"])
                c.execute(
                    "INSERT OR REPLACE INTO usage(facility_id, medicine_id, day, used) VALUES(?,?,?,?)",
                    (sqlite_fac_ids[fid], med_id, day_idx, u.get("used")),
                )

        # 4. Populate Inter-Hospital Transit Matrix
        fac_keys = list(sqlite_fac_ids.keys())
        for fid_a in fac_keys:
            for fid_b in fac_keys:
                if fid_a == fid_b:
                    continue
                fa, fb = fac_meta[fid_a], fac_meta[fid_b]
                days = _haversine_transit_days(
                    fa.get("latitude"), fa.get("longitude"),
                    fb.get("latitude"), fb.get("longitude"),
                )
                c.execute(
                    "INSERT OR REPLACE INTO transit(from_id, to_id, days) VALUES(?,?,?)",
                    (sqlite_fac_ids[fid_a], sqlite_fac_ids[fid_b], days),
                )

        c.commit()
        return {"updated": True, "facilities_loaded": len(sqlite_fac_ids)}
    finally:
        c.close()
