import argparse, re, sqlite3, time, os
from datetime import datetime, timezone
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BASE="https://www.planningportal.nsw.gov.au"
LIST=BASE+"/major-projects/projects"
DB="data/tracker.sqlite3"

def clean(s): return re.sub(r"\s+"," ",s or "").strip()

def fetch(s,url,params=None):
    r=s.get(url,params=params,timeout=45)
    r.raise_for_status()
    return r.text

def listing(html):
    soup=BeautifulSoup(html,"html.parser")
    out=[]
    for a in soup.find_all("a",href=True):
        if clean(a.get_text(" ",strip=True)).lower()!="read more": continue
        card=a
        for _ in range(8):
            card=card.parent if card else None
            if not card: break
            txt=clean(card.get_text(" ",strip=True))
            if re.search(r"\b(SSD|SSI|MP)",txt,re.I) and len(txt)>60: break
        if not card: continue
        txt=clean(card.get_text(" ",strip=True))
        m=re.search(r"\b(SSD|SSI|MP)[-_][A-Za-z0-9_-]+",txt,re.I)
        if not m: continue
        href=urljoin(BASE,a["href"])
        # The listing consistently contains number, status, assessment type,
        # council, title and address. Keep raw text as a fallback.
        out.append((m.group(0),href,txt))
    seen=set(); result=[]
    for r in out:
        if r[1] not in seen: seen.add(r[1]); result.append(r)
    return result

def detail(html,url,number,raw):
    soup=BeautifulSoup(html,"html.parser")
    text=clean(soup.get_text(" ",strip=True))
    h=soup.find("h1")
    title=clean(h.get_text(" ",strip=True)) if h else number

    def after(label, stop_labels):
        m=re.search(re.escape(label)+r"\s*(.*?)\s*(?="+ "|".join(map(re.escape,stop_labels))+r"|$)",text,re.I)
        return clean(m.group(1)) if m else ""

    status=""
    m=re.search(r"Current Status:\s*([A-Za-z ]+?)(?:\s+Interact|\s+Want to stay|\s+1\.)",text,re.I)
    if m: status=clean(m.group(1))

    assessment=after("Assessment Type",["Development Type","Local Government Areas","Contact Planner"])
    dtype=after("Development Type",["Local Government Areas","Contact Planner"])
    lga=after("Local Government Areas",["Contact Planner","View project on map","Project Details"])
    decision=after("Decision",["Determination Date","Decider","Last Modified"])
    detdate=after("Determination Date",["Decider","Last Modified"])
    modified=after("Last Modified On",["Contact Planner","View project on map","Project Details"])

    # Listing card is the most reliable source for address.
    address=""
    # Remove the project number and obvious workflow terms, then use a final
    # address-like segment when available.
    if raw:
        parts=re.split(r"\s+(?=Prepare EIS|SEARs|Exhibition|Assessment|Determination|Withdrawn|State Significant|SSD Modifications)",raw,1)
        if len(parts)>1:
            tail=parts[-1]
            # take the last sentence-like segment after title
            address=tail.split("Read more")[0].strip()

    desc=""
    # Public project pages put the proposal immediately before Attachments.
    m=re.search(r"\b(?:Submissions|Notify me.*?)\s+(.*?)\s+Attachments & Resources\b",text,re.I)
    if m and 50<len(m.group(1))<3000: desc=clean(m.group(1))

    lat=lon=None
    # Search embedded JSON/JS for coordinates.
    for script in soup.find_all("script"):
        s=script.get_text(" ",strip=True)
        ml=re.search(r'(?:"lat"|latitude)\s*[:=]\s*(-?\d+\.\d+)',s,re.I)
        mn=re.search(r'(?:"lng"|"lon"|longitude)\s*[:=]\s*(-?\d+\.\d+)',s,re.I)
        if ml and mn:
            lat=float(ml.group(1)); lon=float(mn.group(1)); break

    # Basic quantitative extraction from the proposal where clearly stated.
    dwell=None; height=None; cost=None
    m=re.search(r"\b(\d[\d,]*)\s+(?:residential\s+)?(?:units|dwellings)\b",desc,re.I)
    if m: dwell=float(m.group(1).replace(",",""))
    m=re.search(r"\b(\d+(?:\.\d+)?)\s*(?:storeys|stories)\b",desc,re.I)
    if m: height=float(m.group(1))
    m=re.search(r"\$\s*([\d,.]+)\s*(million|billion)?",desc,re.I)
    if m:
        cost=float(m.group(1).replace(",",""))*(1e6 if (m.group(2) or "").lower()=="million" else 1e9 if (m.group(2) or "").lower()=="billion" else 1)

    assessment_type="SSD Modifications" if "-Mod-" in number or "-MOD-" in number else assessment
    return dict(project_number=number,title=title,status=status,assessment_type=assessment_type,
        development_type=dtype,lga=lga,address=address,description=desc,url=url,decision=decision,
        determination_date=detdate,last_modified=modified,lat=lat,lon=lon,
        estimated_cost=cost,dwellings=dwell,height=height,affordable_housing=None,applicant="",
        updated_at=datetime.now(timezone.utc).isoformat())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pages",type=int,default=10)
    ap.add_argument("--details",action="store_true")
    ap.add_argument("--delay",type=float,default=.4)
    ap.add_argument("--include-ssi",action="store_true")
    ap.add_argument("--include-modifications",action="store_true")
    args=ap.parse_args()

    s=requests.Session()
    s.headers["User-Agent"]="NSW-SSD-Tracker/1.0 public-data research"
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c=sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS projects(
        project_number TEXT PRIMARY KEY,title TEXT,status TEXT,assessment_type TEXT,
        development_type TEXT,lga TEXT,address TEXT,description TEXT,url TEXT,decision TEXT,
        determination_date TEXT,last_modified TEXT,lat REAL,lon REAL,estimated_cost REAL,
        dwellings REAL,height REAL,affordable_housing REAL,applicant TEXT,updated_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS status_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,project_number TEXT,status TEXT,observed_at TEXT)""")
    links=[]
    for page in range(args.pages):
        html=fetch(s,LIST,{"case_type":"All","development_type":"All","industry_type":"All","lga":"All","status":"All","page":page})
        batch=listing(html)
        if not batch: break
        links += batch
        print(f"Page {page}: {len(batch)} records")
        time.sleep(args.delay)

    for number,url,raw in links:
        if not args.include_ssi and number.upper().startswith("SSI-"): continue
        ismod="-MOD-" in number.upper() or "-MOD" in number.upper()
        if ismod and not args.include_modifications: continue
        now=datetime.now(timezone.utc).isoformat()
        d=detail(fetch(s,url),url,number,raw) if args.details else {
          "project_number":number,"title":raw[:250],"status":"","assessment_type":"",
          "development_type":"","lga":"","address":"","description":"","url":url,
          "decision":"","determination_date":"","last_modified":"","lat":None,"lon":None,
          "estimated_cost":None,"dwellings":None,"height":None,"affordable_housing":None,
          "applicant":"","updated_at":now}
        old=c.execute("SELECT status FROM projects WHERE project_number=?",(number,)).fetchone()
        c.execute("""INSERT INTO projects(project_number,title,status,assessment_type,development_type,lga,address,description,url,decision,determination_date,last_modified,lat,lon,estimated_cost,dwellings,height,affordable_housing,applicant,updated_at)
        VALUES(:project_number,:title,:status,:assessment_type,:development_type,:lga,:address,:description,:url,:decision,:determination_date,:last_modified,:lat,:lon,:estimated_cost,:dwellings,:height,:affordable_housing,:applicant,:updated_at)
        ON CONFLICT(project_number) DO UPDATE SET
        title=excluded.title,status=excluded.status,assessment_type=excluded.assessment_type,
        development_type=excluded.development_type,lga=excluded.lga,address=excluded.address,
        description=excluded.description,url=excluded.url,decision=excluded.decision,
        determination_date=excluded.determination_date,last_modified=excluded.last_modified,
        lat=excluded.lat,lon=excluded.lon,estimated_cost=excluded.estimated_cost,
        dwellings=excluded.dwellings,height=excluded.height,updated_at=excluded.updated_at""",d)
        if (not old and d["status"]) or (old and old[0]!=d["status"]):
            c.execute("INSERT INTO status_history(project_number,status,observed_at) VALUES(?,?,?)",(number,d["status"],now))
        time.sleep(args.delay)
    c.commit(); c.close()
    print("Sync complete.")

if __name__=="__main__": main()
