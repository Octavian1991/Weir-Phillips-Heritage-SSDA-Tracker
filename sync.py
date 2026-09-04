import argparse
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.planningportal.nsw.gov.au"
LIST = BASE + "/major-projects/projects"
DB = "data/tracker.sqlite3"

STATUSES = [
    "Prepare EIS", "SEARs", "Exhibition", "Collate Submissions",
    "Response to Submissions", "Assessment", "Recommendation",
    "Determination", "Withdrawn", "Prepare Mod Report",
]

DEVELOPMENT_TYPES = [
    "State Significant Development",
    "SSD Modifications",
    "Part3A Modifications",
    "Part3A",
    "SSI Modifications",
    "State Significant Infrastructure",
    "Site Verification Certificate",
]


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "WPH-SSDA-Tracker/3.0 public-data research",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def fetch(s, url, params=None, attempts=4):
    last = None
    for attempt in range(attempts):
        try:
            r = s.get(url, params=params, timeout=60)
            r.raise_for_status()
            return r.text
        except Exception as exc:
            last = exc
            time.sleep(min(8, 1.5 * (attempt + 1)))
    raise last


def project_number_from(text):
    m = re.search(r"\b((?:SSD|SSI|MP|DA)[-_A-Za-z0-9]+)\b", text or "", re.I)
    return m.group(1) if m else ""


def nearest_card(a):
    """Find the smallest useful ancestor containing a project card."""
    cur = a
    for _ in range(10):
        cur = cur.parent if cur else None
        if not cur:
            break
        text = clean(cur.get_text(" ", strip=True))
        if not project_number_from(text):
            continue
        # Real cards have a heading for the project title. This avoids grabbing
        # the entire page-level container around multiple projects.
        if cur.find(["h2", "h3", "h4"]):
            return cur
    return None


def listing(html):
    """Parse NSW Planning Portal project cards.

    The public listing is deliberately treated as the authoritative source for
    the core fields. Each card is presented as:
        application number / status / development type / LGA / title / address
    followed by a Read more link. We parse that sequence directly rather than
    relying on heading tags, which have changed across Portal revisions.
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []

    for a in soup.find_all("a", href=True):
        if clean(a.get_text(" ", strip=True)).casefold() != "read more":
            continue

        # Find the smallest ancestor that represents one card. It should contain
        # exactly one Read more link and a recognisable application number.
        card = None
        cur = a
        for _ in range(10):
            cur = cur.parent if cur else None
            if not cur:
                break
            read_more = cur.find_all("a", href=True)
            if sum(clean(x.get_text(" ", strip=True)).casefold() == "read more" for x in read_more) != 1:
                continue
            txt = clean(cur.get_text(" ", strip=True))
            if project_number_from(txt):
                card = cur
                break
        if not card:
            continue

        lines = []
        for value in card.stripped_strings:
            value = clean(value)
            if value and value.casefold() != "read more" and value not in lines:
                lines.append(value)

        number = next(
            (x for x in lines if re.fullmatch(r"(?:SSD|SSI|MP|DA)[-_A-Za-z0-9]+", x, re.I)),
            "",
        )
        if not number:
            number = project_number_from(clean(card.get_text(" ", strip=True)))
        if not number:
            continue

        # Locate the known status and development type, then use the Portal's
        # stable positional sequence for LGA, title and address.
        status = next((x for x in lines if x in STATUSES), "")
        dtype = next((x for x in lines if x in DEVELOPMENT_TYPES), "")
        lga = title = address = ""

        if status and dtype:
            si = lines.index(status)
            di = next((i for i in range(si + 1, len(lines)) if lines[i] == dtype), -1)
            if di >= 0:
                if di + 1 < len(lines):
                    lga = lines[di + 1]
                if di + 2 < len(lines):
                    title = lines[di + 2]
                if di + 3 < len(lines):
                    address = lines[di + 3]

        # Defensive fallbacks for markup variations.
        if not title:
            heading = card.find(["h2", "h3", "h4"])
            if heading:
                heading_text = clean(heading.get_text(" ", strip=True))
                if heading_text and heading_text != number:
                    title = heading_text
        if not address and title and title in lines:
            ti = lines.index(title)
            if ti + 1 < len(lines):
                address = lines[ti + 1]

        href = urljoin(BASE, a["href"])
        out.append({
            "project_number": number,
            "title": title,
            "status": status,
            "assessment_type": dtype,
            "development_type": dtype,
            "lga": lga,
            "address": address,
            "url": href,
            "raw": clean(card.get_text(" ", strip=True)),
        })

    seen = set()
    result = []
    for row in out:
        key = row["url"] or row["project_number"]
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result



# NSW Spatial Services Address Location Service (GURAS-backed authoritative
# NSW property addressing). It returns an address point in EPSG:4326.
ADDRESS_SERVICE = "http://mapsq.six.nsw.gov.au/services/public/Address_Location"
ROAD_TYPES = {
    "access":"ACCS","alley":"ALLY","alleyway":"ALWY","amble":"AMBL","approach":"APP",
    "arcade":"ARC","arterial":"ARTL","artery":"ART","avenue":"AVE","bend":"BEND",
    "boardwalk":"BWLK","boulevard":"BVD","brace":"BRCE","brae":"BRAE","break":"BRK",
    "broadway":"BDWY","brow":"BROW","bypass":"BYPA","byway":"BYWY","causeway":"CAUS",
    "centre":"CTR","chase":"CH","circle":"CIR","circlet":"CLT","circuit":"CCT","circus":"CRCS",
    "close":"CL","common":"CMMN","concourse":"CON","copse":"CPS","corner":"CNR","court":"CT",
    "courtyard":"CTYD","cove":"COVE","crescent":"CR","crest":"CRST","cross":"CRSS","crossing":"CRSG",
    "cul-de-sac":"CSAC","dale":"DALE","deviation":"DEVN","dip":"DIP","distributor":"DSTR","drive":"DR",
    "driveway":"DRWY","edge":"EDGE","elbow":"ELB","end":"END","entrance":"ENT","esplanade":"ESP",
    "expressway":"EXP","extension":"EXTN","fairway":"FAWY","firetrack":"FTRK","firetrail":"FITR","follow":"FOLW",
    "footway":"FTWY","formation":"FORM","freeway":"FWY","frontage":"FRTG","gap":"GAP","garden":"GDN",
    "gardens":"GDNS","gate":"GATE","glade":"GLD","glen":"GLEN","grange":"GRA","green":"GRN","grove":"GR",
    "heights":"HTS","highroad":"HRD","highway":"HWY","hill":"HILL","interchange":"INTG","junction":"JNC",
    "key":"KEY","lane":"LANE","laneway":"LNWY","line":"LINE","link":"LINK","lookout":"LKT","loop":"LOOP",
    "mall":"MALL","meander":"MNDR","mews":"MEWS","motorway":"MWY","nook":"NOOK","outlook":"OTLK","parade":"PDE",
    "parkway":"PKWY","pass":"PASS","passage":"PSGE","path":"PATH","pathway":"PHWY","piazza":"PIAZ","place":"PL",
    "plaza":"PLZA","pocket":"PKT","point":"PNT","port":"PORT","promenade":"PROM","quadrant":"QDRT","quay":"QY",
    "quays":"QYS","ramble":"RMBL","ramp":"RAMP","rest":"REST","retreat":"RTT","ridge":"RDGE","ring":"RING",
    "rise":"RISE","road":"RD","roads":"RDS","rotary":"RTY","route":"RTE","row":"ROW","rue":"RUE","serviceway":"SVWY",
    "shunt":"SHUN","spur":"SPUR","square":"SQ","stairs":"STRS","steps":"STPS","street":"ST","strip":"STRP",
    "subway":"SBWY","tarn":"TARN","terrace":"TCE","thoroughfare":"THOR","tollway":"TLWY","top":"TOP","tor":"TOR",
    "track":"TRK","trail":"TRL","turn":"TURN","underpass":"UPAS","vale":"VALE","viaduct":"VIAD","view":"VIEW",
    "vista":"VSTA","walk":"WALK","walkway":"WKWY","way":"WAY","wharf":"WHRF","wynd":"WYND"
}

def parse_address_for_nsw_service(address):
    """Extract the best single street address from a Portal address string."""
    a = clean(address).replace("&amp;", "&")
    if not a:
        return None
    # Drop country/state suffixes while retaining the suburb.
    a = re.sub(r",?\s*(?:New South Wales|NSW|Australia)\s*$", "", a, flags=re.I)
    # If a site has multiple addresses, use the first address as the representative point.
    a = re.split(r"\s+&\s+|\s*;\s*", a, maxsplit=1)[0].strip()
    parts = [clean(x) for x in a.split(",") if clean(x)]
    if not parts:
        return None

    postcode_match = re.search(r"\b(2\d{3})\b", a)
    postcode = postcode_match.group(1) if postcode_match else ""
    if postcode:
        a_no_post = re.sub(r"\b2\d{3}\b", "", a).strip(" ,")
        parts = [clean(x) for x in a_no_post.split(",") if clean(x)]

    # Usually the final comma component is the suburb. If there is no comma,
    # find the road type and treat the text after it as the suburb.
    suburb = parts[-1] if len(parts) >= 2 else ""
    street = parts[0] if len(parts) >= 2 else parts[0]
    if len(parts) == 1:
        # e.g. "346 Panorama Avenue Bathurst"
        m = re.search(r"\b(" + "|".join(sorted(map(re.escape, ROAD_TYPES), key=len, reverse=True)) + r")\b", street, re.I)
        if m:
            suburb = clean(street[m.end():])
            street = clean(street[:m.end()])
    if not street:
        return None

    # Extract house number, preserving ranges/suffixes where present.
    hm = re.match(r"\s*([0-9]+[A-Za-z]?(?:\s*[-/]\s*[0-9]+[A-Za-z]?)?)\s+(.+)$", street)
    house = hm.group(1) if hm else ""
    road_part = hm.group(2) if hm else street

    # Find the road type at the end of the street component.
    type_match = None
    for rt in sorted(ROAD_TYPES, key=len, reverse=True):
        m = re.search(r"\b" + re.escape(rt) + r"\.?\s*$", road_part, re.I)
        if m:
            type_match = m
            break
    if not type_match:
        # No standard road type: the service cannot reliably geocode this string.
        return None
    road_name = clean(road_part[:type_match.start()])
    road_type = type_match.group(1) if type_match.groups() else type_match.group(0)
    if not road_name or not suburb:
        return None
    return {"houseNumber": house, "roadName": road_name, "roadType": road_type, "suburb": suburb, "postCode": postcode}


def geocode_address(address, http_session=None):
    parsed = parse_address_for_nsw_service(address)
    if not parsed:
        return None, "unparseable"
    s = http_session or session()
    try:
        params = dict(parsed)
        params["projection"] = "EPSG:4326"
        r = s.get(ADDRESS_SERVICE, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        addresses = (((data or {}).get("addressResult") or {}).get("addresses") or [])
        if not addresses:
            return None, "no_match"
        # Prefer an exact/official/assigned match where available.
        chosen = addresses[0]
        for candidate in addresses:
            methods = ((data.get("addressResult") or {}).get("searchMethod") or {}).get("methodDescriptions", [])
            if "Input parameters matched" in methods:
                chosen = candidate
                break
        pt = chosen.get("addressPoint") or {}
        lat = pt.get("centreY")
        lon = pt.get("centreX")
        if lat is None or lon is None:
            return None, "no_point"
        return (float(lat), float(lon)), "ok"
    except Exception as exc:
        return None, str(exc)

def detail(html, row):
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    number = row["project_number"]

    h = soup.find("h1")
    title = clean(h.get_text(" ", strip=True)) if h else row["title"]

    def after(label, stop_labels):
        stops = "|".join(map(re.escape, stop_labels))
        m = re.search(re.escape(label) + r"\s*(.*?)\s*(?=" + stops + r"|$)", text, re.I)
        return clean(m.group(1)) if m else ""

    status = ""
    m = re.search(
        r"Current Status:\s*(.+?)(?=\s+Interact with the stages|\s+Interact|\s+Want to stay|\s+1\.|\s+2\.|$)",
        text, re.I,
    )
    if m:
        status = clean(m.group(1))
        # Guard against a page heading leaking into the match.
        if len(status) > 80:
            status = ""

    assessment = after("Assessment Type", ["Development Type", "Local Government Areas", "Contact Planner", "View project on map"])
    dtype = after("Development Type", ["Local Government Areas", "Contact Planner", "View project on map", "Project Details"])
    lga = after("Local Government Areas", ["Contact Planner", "View project on map", "Project Details"])
    decision = after("Decision", ["Determination Date", "Decider", "Last Modified"])
    detdate = after("Determination Date", ["Decider", "Last Modified"])
    modified = after("Last Modified On", ["Contact Planner", "View project on map", "Project Details"])

    desc = ""
    m = re.search(r"\b(?:Submissions|Notify me.*?)\s+(.*?)\s+Attachments & Resources\b", text, re.I)
    if m and 50 < len(m.group(1)) < 8000:
        desc = clean(m.group(1))

    # Fall back to the listing card's reliable fields whenever the detail page
    # doesn't expose a particular value.
    status = status or row["status"]
    lga = lga or row["lga"]
    dtype = dtype or row["development_type"]
    assessment = assessment or row["assessment_type"]

    lat = lon = None
    for script in soup.find_all("script"):
        s = script.get_text(" ", strip=True)
        ml = re.search(r'(?:(?:"lat"|latitude)\s*[:=]\s*)(-?\d+\.\d+)', s, re.I)
        mn = re.search(r'(?:(?:"lng"|"lon"|longitude)\s*[:=]\s*)(-?\d+\.\d+)', s, re.I)
        if ml and mn:
            lat = float(ml.group(1))
            lon = float(mn.group(1))
            break

    dwell = height = cost = gfa = affordable = None
    m = re.search(r"\b(\d[\d,]*)\s+(?:residential\s+)?(?:units|dwellings)\b", desc, re.I)
    if m:
        dwell = float(m.group(1).replace(",", ""))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:storeys|stories)\b", desc, re.I)
    if m:
        height = float(m.group(1))
    m = re.search(r"(?:gross floor area|GFA)[^\d]{0,30}(\d[\d,]*(?:\.\d+)?)\s*(?:m2|m²|sqm|square metres|square meters)?", desc, re.I)
    if m:
        gfa = float(m.group(1).replace(",", ""))
    m = re.search(r"(?:affordable housing|affordable dwellings|affordable homes)[^\d]{0,40}(\d[\d,]*)", desc, re.I)
    if m:
        affordable = float(m.group(1).replace(",", ""))
    m = re.search(r"\$\s*([\d,.]+)\s*(million|billion)?", desc, re.I)
    if m:
        cost = float(m.group(1).replace(",", "")) * (
            1e6 if (m.group(2) or "").lower() == "million" else
            1e9 if (m.group(2) or "").lower() == "billion" else 1
        )

    assessment_type = assessment
    if re.search(r"(?:-mod|mod-)", number, re.I) and not assessment_type:
        assessment_type = row["development_type"] or "SSD Modifications"

    return {
        "project_number": number,
        "title": title or row["title"],
        "status": status,
        "assessment_type": assessment_type,
        "development_type": dtype,
        "lga": lga,
        "address": row["address"],
        "description": desc,
        "url": row["url"],
        "decision": decision,
        "determination_date": detdate,
        "last_modified": modified,
        "lat": lat,
        "lon": lon,
        "estimated_cost": cost,
        "dwellings": dwell,
        "height": height,
        "gfa": gfa,
        "affordable_housing": affordable,
        "applicant": "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def listing_detail(row):
    return {
        "project_number": row["project_number"],
        "title": row["title"],
        "status": row["status"],
        "assessment_type": row["assessment_type"],
        "development_type": row["development_type"],
        "lga": row["lga"],
        "address": row["address"],
        "description": "",
        "url": row["url"],
        "decision": "",
        "determination_date": "",
        "last_modified": "",
        "lat": None,
        "lon": None,
        "estimated_cost": None,
        "dwellings": None,
        "height": None,
        "gfa": None,
        "affordable_housing": None,
        "applicant": "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def init_db(c):
    c.execute("""CREATE TABLE IF NOT EXISTS projects(
        project_number TEXT PRIMARY KEY,title TEXT,status TEXT,assessment_type TEXT,
        development_type TEXT,lga TEXT,address TEXT,description TEXT,url TEXT,decision TEXT,
        determination_date TEXT,last_modified TEXT,lat REAL,lon REAL,estimated_cost REAL,
        dwellings REAL,height REAL,gfa REAL,affordable_housing REAL,applicant TEXT,updated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS status_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,project_number TEXT,status TEXT,observed_at TEXT)""")
    existing = {r[1] for r in c.execute("PRAGMA table_info(projects)").fetchall()}
    if "gfa" not in existing:
        c.execute("ALTER TABLE projects ADD COLUMN gfa REAL")


def save_project(c, d):
    now = d["updated_at"]
    old = c.execute("SELECT * FROM projects WHERE project_number=?", (d["project_number"],)).fetchone()

    columns = [
        "project_number", "title", "status", "assessment_type", "development_type",
        "lga", "address", "description", "url", "decision", "determination_date",
        "last_modified", "lat", "lon", "estimated_cost", "dwellings", "height",
        "gfa", "affordable_housing", "applicant", "updated_at",
    ]

    if old:
        # Never replace a good value with an empty value just because a detail
        # page failed or changed its markup.
        existing = dict(zip(columns, old))
        merged = dict(existing)
        for col in columns:
            if col == "project_number":
                continue
            value = d.get(col)
            if value not in (None, ""):
                merged[col] = value
        merged["updated_at"] = now
        d = merged

    c.execute("""INSERT INTO projects(
        project_number,title,status,assessment_type,development_type,lga,address,description,url,decision,
        determination_date,last_modified,lat,lon,estimated_cost,dwellings,height,gfa,affordable_housing,applicant,updated_at)
        VALUES(:project_number,:title,:status,:assessment_type,:development_type,:lga,:address,:description,:url,:decision,
        :determination_date,:last_modified,:lat,:lon,:estimated_cost,:dwellings,:height,:affordable_housing,:applicant,:updated_at)
        ON CONFLICT(project_number) DO UPDATE SET
        title=excluded.title,status=excluded.status,assessment_type=excluded.assessment_type,
        development_type=excluded.development_type,lga=excluded.lga,address=excluded.address,
        description=excluded.description,url=excluded.url,decision=excluded.decision,
        determination_date=excluded.determination_date,last_modified=excluded.last_modified,
        lat=excluded.lat,lon=excluded.lon,estimated_cost=excluded.estimated_cost,
        dwellings=excluded.dwellings,height=excluded.height,gfa=excluded.gfa,affordable_housing=excluded.affordable_housing,
        applicant=excluded.applicant,updated_at=excluded.updated_at""", d)

    old_status = old[2] if old else ""
    if d.get("status") and d["status"] != old_status:
        c.execute(
            "INSERT INTO status_history(project_number,status,observed_at) VALUES(?,?,?)",
            (d["project_number"], d["status"], now),
        )


def is_ssd_record(row, include_ssi=False):
    number = row["project_number"].upper()
    dtype = (row.get("development_type") or "").lower()
    if number.startswith("SSI-") and not include_ssi:
        return False
    if "state significant development" in dtype:
        return True
    if "ssd modification" in dtype or "part3a" in dtype:
        return True
    if number.startswith("SSD-") or number.startswith("MP"):
        return True
    # Some legacy modification numbers use DA prefixes but are explicitly
    # categorised as SSD modifications by the Portal.
    if number.startswith("DA") and "modification" in dtype:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=30, help="Number of listing pages; 0 means all pages")
    ap.add_argument("--details", action="store_true", help="Enrich records from individual project pages")
    ap.add_argument("--delay", type=float, default=0.08)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--include-ssi", action="store_true")
    ap.add_argument("--include-modifications", action="store_true", help="Retained for compatibility; SSD modifications are now included by default")
    ap.add_argument("--full", action="store_true", help="Crawl every listing page")
    ap.add_argument("--recent", action="store_true", help="Refresh the newest listing pages")
    args = ap.parse_args()

    if args.full:
        args.pages = 0
    elif args.recent:
        args.pages = max(args.pages, 30)

    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    init_db(c)
    c.commit()

    s = session()
    links = []
    seen = set()
    page = 0

    while True:
        if args.pages and page >= args.pages:
            break
        html = fetch(s, LIST, {
            "case_type": "All", "development_type": "All", "industry_type": "All",
            "lga": "All", "status": "All", "page": page,
        })
        batch = listing(html)
        if not batch:
            break
        added = 0
        for row in batch:
            k = row["url"] or row["project_number"]
            if k in seen:
                continue
            seen.add(k)
            links.append(row)
            added += 1
        print(f"Listing page {page}: {len(batch)} cards, {added} new")
        page += 1
        time.sleep(args.delay)

    filtered = [r for r in links if is_ssd_record(r, args.include_ssi)]
    print(f"Collected {len(links)} public records; retaining {len(filtered)} SSD/Part 3A records from {page} listing pages.")

    # Always save the structured listing data first. This guarantees that LGA,
    # status, development type, title and address survive even if detail pages fail.
    for row in filtered:
        save_project(c, listing_detail(row))
    c.commit()

    if args.details:
        def get_one(row):
            try:
                return detail(fetch(session(), row["url"]), row), None
            except Exception as exc:
                return None, f"{row['project_number']}: {exc}"

        failures = 0
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(get_one, row): row for row in filtered}
            for i, future in enumerate(as_completed(futures), 1):
                d, err = future.result()
                if d:
                    save_project(c, d)
                elif err:
                    failures += 1
                    print("Detail failed", err)
                if i % 50 == 0:
                    c.commit()
                    print(f"Enriched {i}/{len(filtered)} project details; failures={failures}")

    # Fill missing map coordinates from the authoritative NSW Address Location
    # Service. This is intentionally a separate pass so listing-only full imports
    # also get usable map coordinates without requiring detail-page enrichment.
    rows = c.execute("SELECT project_number,address FROM projects WHERE (lat IS NULL OR lon IS NULL) AND address IS NOT NULL AND address != ''").fetchall()
    geo_ok = 0
    geo_failed = 0
    if rows:
        print(f"Geocoding {len(rows)} projects with missing coordinates via NSW Address Location Service...")
        def geo_one(item):
            number, address = item
            pt, reason = geocode_address(address)
            return number, pt, reason
        with ThreadPoolExecutor(max_workers=min(4, max(1, args.workers))) as pool:
            futures = [pool.submit(geo_one, row) for row in rows]
            for i, future in enumerate(as_completed(futures), 1):
                number, pt, reason = future.result()
                if pt:
                    c.execute("UPDATE projects SET lat=?, lon=?, updated_at=? WHERE project_number=?", (pt[0], pt[1], datetime.now(timezone.utc).isoformat(), number))
                    geo_ok += 1
                else:
                    geo_failed += 1
                if i % 100 == 0:
                    c.commit()
                    print(f"Geocoded {i}/{len(rows)}; matched={geo_ok}, unresolved={geo_failed}")
    c.commit()
    c.close()
    print(f"Sync complete: {len(filtered)} SSD/Part 3A records processed; detail failures={failures if args.details else 0}; geocoded={geo_ok}; unresolved={geo_failed}.")


if __name__ == "__main__":
    main()
