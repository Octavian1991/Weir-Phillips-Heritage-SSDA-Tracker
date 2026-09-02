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
    "Determination", "Withdrawn", "Prepare Mod Report", "Assessment",
]


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def session():
    s = requests.Session()
    s.headers["User-Agent"] = "WPH-SSDA-Tracker/2.0 public-data research"
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
            time.sleep(1.5 * (attempt + 1))
    raise last


def listing(html):
    """Return project links and card text from a Planning Portal listing page."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        if clean(a.get_text(" ", strip=True)).lower() != "read more":
            continue
        card = a
        for _ in range(10):
            card = card.parent if card else None
            if not card:
                break
            txt = clean(card.get_text(" ", strip=True))
            if re.search(r"\b(SSD|SSI|MP)[-_][A-Za-z0-9_-]+", txt, re.I) and len(txt) > 60:
                break
        if not card:
            continue
        txt = clean(card.get_text(" ", strip=True))
        m = re.search(r"\b(SSD|SSI|MP)[-_][A-Za-z0-9_-]+", txt, re.I)
        if not m:
            continue
        href = urljoin(BASE, a["href"])
        out.append((m.group(0), href, txt))

    seen = set()
    result = []
    for row in out:
        if row[1] not in seen:
            seen.add(row[1])
            result.append(row)
    return result


def detail(html, url, number, raw):
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))
    h = soup.find("h1")
    title = clean(h.get_text(" ", strip=True)) if h else number

    def after(label, stop_labels):
        stops = "|".join(map(re.escape, stop_labels))
        m = re.search(re.escape(label) + r"\s*(.*?)\s*(?=" + stops + r"|$)", text, re.I)
        return clean(m.group(1)) if m else ""

    status = ""
    m = re.search(r"Current Status:\s*([A-Za-z ]+?)(?:\s+Interact|\s+Want to stay|\s+1\.)", text, re.I)
    if m:
        status = clean(m.group(1))

    assessment = after("Assessment Type", ["Development Type", "Local Government Areas", "Contact Planner"])
    dtype = after("Development Type", ["Local Government Areas", "Contact Planner"])
    lga = after("Local Government Areas", ["Contact Planner", "View project on map", "Project Details"])
    decision = after("Decision", ["Determination Date", "Decider", "Last Modified"])
    detdate = after("Determination Date", ["Decider", "Last Modified"])
    modified = after("Last Modified On", ["Contact Planner", "View project on map", "Project Details"])

    address = ""
    if raw:
        parts = re.split(
            r"\s+(?=Prepare EIS|SEARs|Exhibition|Collate Submissions|Response to Submissions|Assessment|Recommendation|Determination|Withdrawn|Prepare Mod Report|State Significant)",
            raw,
            1,
        )
        if len(parts) > 1:
            address = parts[-1].split("Read more")[0].strip()

    desc = ""
    m = re.search(r"\b(?:Submissions|Notify me.*?)\s+(.*?)\s+Attachments & Resources\b", text, re.I)
    if m and 50 < len(m.group(1)) < 5000:
        desc = clean(m.group(1))

    lat = lon = None
    for script in soup.find_all("script"):
        s = script.get_text(" ", strip=True)
        ml = re.search(r'(?:(?:"lat"|latitude)\s*[:=]\s*)(-?\d+\.\d+)', s, re.I)
        mn = re.search(r'(?:(?:"lng"|"lon"|longitude)\s*[:=]\s*)(-?\d+\.\d+)', s, re.I)
        if ml and mn:
            lat = float(ml.group(1))
            lon = float(mn.group(1))
            break

    dwell = height = cost = None
    m = re.search(r"\b(\d[\d,]*)\s+(?:residential\s+)?(?:units|dwellings)\b", desc, re.I)
    if m:
        dwell = float(m.group(1).replace(",", ""))
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:storeys|stories)\b", desc, re.I)
    if m:
        height = float(m.group(1))
    m = re.search(r"\$\s*([\d,.]+)\s*(million|billion)?", desc, re.I)
    if m:
        cost = float(m.group(1).replace(",", "")) * (
            1e6 if (m.group(2) or "").lower() == "million" else
            1e9 if (m.group(2) or "").lower() == "billion" else 1
        )

    assessment_type = "SSD Modifications" if re.search(r"-mod", number, re.I) else assessment
    return dict(
        project_number=number,
        title=title,
        status=status,
        assessment_type=assessment_type,
        development_type=dtype,
        lga=lga,
        address=address,
        description=desc,
        url=url,
        decision=decision,
        determination_date=detdate,
        last_modified=modified,
        lat=lat,
        lon=lon,
        estimated_cost=cost,
        dwellings=dwell,
        height=height,
        affordable_housing=None,
        applicant="",
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def blank_detail(number, url, raw):
    return dict(
        project_number=number,
        title=raw[:250],
        status="",
        assessment_type="",
        development_type="",
        lga="",
        address="",
        description="",
        url=url,
        decision="",
        determination_date="",
        last_modified="",
        lat=None,
        lon=None,
        estimated_cost=None,
        dwellings=None,
        height=None,
        affordable_housing=None,
        applicant="",
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def init_db(c):
    c.execute("""CREATE TABLE IF NOT EXISTS projects(
        project_number TEXT PRIMARY KEY,title TEXT,status TEXT,assessment_type TEXT,
        development_type TEXT,lga TEXT,address TEXT,description TEXT,url TEXT,decision TEXT,
        determination_date TEXT,last_modified TEXT,lat REAL,lon REAL,estimated_cost REAL,
        dwellings REAL,height REAL,affordable_housing REAL,applicant TEXT,updated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS status_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,project_number TEXT,status TEXT,observed_at TEXT)""")


def save_project(c, d):
    now = d["updated_at"]
    old = c.execute("SELECT status FROM projects WHERE project_number=?", (d["project_number"],)).fetchone()
    c.execute("""INSERT INTO projects(project_number,title,status,assessment_type,development_type,lga,address,description,url,decision,determination_date,last_modified,lat,lon,estimated_cost,dwellings,height,affordable_housing,applicant,updated_at)
    VALUES(:project_number,:title,:status,:assessment_type,:development_type,:lga,:address,:description,:url,:decision,:determination_date,:last_modified,:lat,:lon,:estimated_cost,:dwellings,:height,:affordable_housing,:applicant,:updated_at)
    ON CONFLICT(project_number) DO UPDATE SET
      title=excluded.title,status=excluded.status,assessment_type=excluded.assessment_type,
      development_type=excluded.development_type,lga=excluded.lga,address=excluded.address,
      description=excluded.description,url=excluded.url,decision=excluded.decision,
      determination_date=excluded.determination_date,last_modified=excluded.last_modified,
      lat=excluded.lat,lon=excluded.lon,estimated_cost=excluded.estimated_cost,
      dwellings=excluded.dwellings,height=excluded.height,updated_at=excluded.updated_at""", d)
    if (not old and d["status"]) or (old and old[0] != d["status"] and d["status"]):
        c.execute("INSERT INTO status_history(project_number,status,observed_at) VALUES(?,?,?)", (d["project_number"], d["status"], now))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=20, help="Number of listing pages; 0 means all pages")
    ap.add_argument("--details", action="store_true")
    ap.add_argument("--delay", type=float, default=0.15)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--include-ssi", action="store_true")
    ap.add_argument("--include-modifications", action="store_true")
    ap.add_argument("--full", action="store_true", help="Crawl every listing page")
    args = ap.parse_args()

    if args.full:
        args.pages = 0

    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    init_db(c)
    c.commit()

    s = session()
    links = []
    seen_urls = set()
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
            number, url, raw = row
            if url not in seen_urls:
                seen_urls.add(url)
                links.append(row)
                added += 1
        print(f"Listing page {page}: {len(batch)} cards, {added} new")
        page += 1
        time.sleep(args.delay)

    print(f"Collected {len(links)} unique public project records from {page} listing pages.")

    # Filter to SSD/Part 3A/modifications by default. SSI can be enabled explicitly.
    filtered = []
    for row in links:
        number = row[0]
        if not args.include_ssi and number.upper().startswith("SSI-"):
            continue
        if not args.include_modifications and re.search(r"-mod", number, re.I):
            continue
        filtered.append(row)

    def get_one(row):
        number, url, raw = row
        try:
            if args.details:
                return detail(fetch(session(), url), url, number, raw)
            return blank_detail(number, url, raw)
        except Exception as exc:
            print(f"Detail failed for {number}: {exc}")
            return blank_detail(number, url, raw)

    if args.details:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(get_one, row): row for row in filtered}
            for i, future in enumerate(as_completed(futures), 1):
                save_project(c, future.result())
                if i % 50 == 0:
                    c.commit()
                    print(f"Saved {i}/{len(filtered)} project details")
    else:
        for row in filtered:
            save_project(c, blank_detail(*row))

    c.commit()
    c.close()
    print(f"Sync complete: {len(filtered)} SSD/Part 3A records processed.")


if __name__ == "__main__":
    main()
