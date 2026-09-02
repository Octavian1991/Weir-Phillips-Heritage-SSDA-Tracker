import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

BASE=Path(__file__).parent
DB=BASE/"data"/"tracker.sqlite3"
LOGO=BASE/"WPHeritage_Logo_Horiz_RGB.jpg"

st.set_page_config(
    page_title="Weir Phillips Heritage SSDA Tracker",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Styling ----------
st.markdown("""
<style>
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
h1, h2, h3, h4 {
    font-family: Georgia, "Times New Roman", serif !important;
    font-weight: 400 !important;
}
[data-testid="stAppViewContainer"] {
    background: #fbfaf8;
}
[data-testid="stHeader"] {
    background: #fbfaf8;
}
.main .block-container {
    max-width: 1500px;
    padding-top: 0.7rem;
    padding-bottom: 2rem;
}
.wph-header {
    background: #fff;
    border-bottom: 1px solid #dedbd6;
    padding: 22px 28px 18px 28px;
    margin: -0.7rem -3rem 1.1rem -3rem;
}
.wph-header-inner {
    display:flex;
    align-items:center;
    gap:24px;
}
.wph-logo {
    width: 355px;
    max-width: 38%;
    object-fit: contain;
}
.wph-divider {
    height:54px;
    width:1px;
    background:#c9c5bf;
}
.wph-title {
    font-family: Georgia, serif;
    font-size: 28px;
    color:#171513;
    line-height:1.15;
}
.wph-subtitle {
    margin-top:5px;
    color:#65615c;
    font-size:14px;
}
.wph-orange { color:#c95b22; }

.section-label {
    color:#c95b22;
    font-size:13px;
    font-weight:600;
    letter-spacing:.06em;
    text-transform:uppercase;
}
.metric-card {
    background:#fff;
    border-top:1px solid #dedbd6;
    border-bottom:1px solid #dedbd6;
    padding:15px 10px 14px;
    text-align:center;
    min-height:96px;
}
.metric-number {
    font-family: Georgia, serif;
    color:#c95b22;
    font-size:32px;
    line-height:1;
}
.metric-label {
    margin-top:7px;
    font-family: Georgia, serif;
    font-size:16px;
    font-weight:600;
}
.metric-sub {
    color:#77716b;
    font-size:11px;
    margin-top:3px;
}
.result-card {
    background:#fff;
    border:1px solid #dedbd6;
    border-radius:7px;
    padding:24px 25px;
    min-height:292px;
}
.project-table {
    background:#fff;
    border:1px solid #dedbd6;
    border-radius:7px;
    padding:0;
}
.small-muted { color:#77716b; font-size:12px; }
.stButton > button {
    border-radius:5px;
}
div[data-testid="stSidebar"] {
    background:#fbfaf8;
    border-right:1px solid #dedbd6;
}
div[data-testid="stSidebar"] .block-container {
    padding-top:1.5rem;
    padding-bottom:2rem;
    max-height:calc(100vh - 1rem);
    overflow-y:auto;
    overflow-x:hidden;
}
/* Keep long filter lists usable on smaller screens. */
div[data-testid="stSidebar"] [data-baseweb="popover"] {
    max-height:70vh !important;
}
div[data-testid="stSidebar"] [role="listbox"] {
    max-height:55vh !important;
}
div[data-testid="stSidebar"] label {
    font-weight:600;
}
div[data-testid="stSidebar"] [data-baseweb="select"] {
    background:#fff;
}
a { color:#c95b22 !important; }
</style>
""", unsafe_allow_html=True)

# ---------- Data ----------
def clean(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\xa0"," ")).strip()

def key(v):
    return clean(v).casefold()

def reload_database():
    """Reload the committed SQLite database after a GitHub refresh."""
    load.clear()
    st.rerun()

@st.cache_data(ttl=300)
def load():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DB)
    try:
        df=pd.read_sql_query("SELECT * FROM projects",c)
    except Exception:
        df=pd.DataFrame()
    c.close()
    return df.fillna("")

df=load()
db_updated_text = ""
if len(df) and "updated_at" in df.columns:
    vals = pd.to_datetime(df["updated_at"], errors="coerce", utc=True).dropna()
    if len(vals):
        latest = vals.max()
        db_updated_text = latest.strftime("%-d %b %Y %H:%M UTC")

# ---------- Header ----------
st.markdown("""
<div class="wph-header">
  <div class="wph-header-inner">
    <img class="wph-logo" src="data:image/jpeg;base64,LOGO_PLACEHOLDER">
    <div class="wph-divider"></div>
    <div>
      <div class="wph-title">Weir Phillips Heritage <span class="wph-orange">SSDA Tracker</span></div>
      <div class="wph-subtitle">State Significant Development Applications in NSW</div>
    </div>
  </div>
</div>
""".replace("LOGO_PLACEHOLDER", __import__("base64").b64encode(LOGO.read_bytes()).decode()), unsafe_allow_html=True)
if db_updated_text:
    st.caption(f"Data last refreshed: **{db_updated_text}**")


# The hosted app reads the database produced by the scheduled GitHub Action.
if df.empty:
    st.warning("The project database has not been populated yet.")
    st.info("Run the “Refresh NSW SSDA data” workflow in GitHub once, then reload this page.")
    st.stop()

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown('<div class="section-label">Filters</div>', unsafe_allow_html=True)
    st.divider()

    if st.button("Clear all filters", use_container_width=True):
        for k,v in {"search":"","lga_filter":[],"status_filter":[],"type_filter":[]}.items():
            st.session_state[k]=v
        st.rerun()

    st.markdown("**Search projects**")
    q=st.text_input("", placeholder="Search by title, address or keywords…",
                    key="search", label_visibility="collapsed")

    def opts(col):
        vals={}
        if col in df.columns:
            for x in df[col]:
                v=clean(x)
                if v and key(v) not in ("nan","none"):
                    vals[key(v)]=v
        return sorted(vals.values(), key=lambda x:key(x))

    lga_options=opts("lga")
    status_options=opts("status")
    type_options=opts("development_type")

    st.markdown("**LGA**")
    lga=st.multiselect("", lga_options, key="lga_filter",
                       placeholder="All LGAs", label_visibility="collapsed")

    st.markdown("**Project Status**")
    status=st.multiselect("", status_options, key="status_filter",
                          placeholder="All Statuses", label_visibility="collapsed")

    st.markdown("**Development Type**")
    dtype=st.multiselect("", type_options, key="type_filter",
                         placeholder="All Development Types", label_visibility="collapsed")

    st.divider()
    st.markdown(
        '<div class="small-muted">Use the filters above to refine the project list. '
        'Click a project to view its full details.</div>',
        unsafe_allow_html=True
    )

# ---------- Filtering ----------
f=df.copy()

if q:
    qk=key(q)
    searchable=["project_number","title","lga","address","description",
                "development_type","status","assessment_type"]
    mask=pd.Series(False,index=f.index)
    for col in searchable:
        if col in f.columns:
            mask |= f[col].map(key).str.contains(qk, regex=False, na=False)
    f=f[mask]

if lga:
    wanted={key(x) for x in lga}
    f=f[f["lga"].map(key).isin(wanted)]
if status:
    wanted={key(x) for x in status}
    f=f[f["status"].map(key).isin(wanted)]
if dtype:
    wanted={key(x) for x in dtype}
    f=f[f["development_type"].map(key).isin(wanted)]

# ---------- Metrics ----------
total=len(f)
exhibition=int(f["status"].map(key).str.contains("exhibition",regex=False).sum()) if len(f) else 0
determined=int(f["status"].map(key).str.contains("determination",regex=False).sum()) if len(f) else 0
assessment=int(f["status"].map(key).str.contains("assessment",regex=False).sum()) if len(f) else 0
other=max(total-exhibition-determined-assessment,0)

cols=st.columns(5)
metrics=[
    (f"{total:,}","Total Projects","Matching your filters"),
    (f"{exhibition:,}","Exhibition","Currently on exhibition"),
    (f"{determined:,}","Determined","Determination stage"),
    (f"{assessment:,}","Under Assessment","Assessment stage"),
    (f"{other:,}","Other / Earlier","Other current statuses"),
]
for c,(num,label,sub) in zip(cols,metrics):
    with c:
        st.markdown(f'<div class="metric-card"><div class="metric-number">{num}</div>'
                    f'<div class="metric-label">{label}</div><div class="metric-sub">{sub}</div></div>',
                    unsafe_allow_html=True)

st.write("")

# ---------- Main content ----------
map_col, result_col=st.columns([2.25,1])

LGA_CENTROIDS={
    "North Sydney":(-33.838,151.207),"City of Sydney":(-33.874,151.206),
    "Bayside":(-33.94,151.14),"Waverley":(-33.90,151.26),
    "City of Canada Bay":(-33.86,151.13),"Inner West":(-33.88,151.17),
    "City of Parramatta":(-33.815,151.00),"The Hills Shire":(-33.73,150.96),
    "Ku-ring-gai":(-33.72,151.13),"Willoughby":(-33.80,151.20),
    "Ryde":(-33.81,151.10),"Blacktown":(-33.77,150.91),
    "Cumberland":(-33.84,151.01),"Canterbury-Bankstown":(-33.91,150.99),
    "Liverpool":(-33.92,150.92),"Penrith":(-33.75,150.70),
    "Sutherland Shire":(-34.03,151.06),"Georges River":(-33.97,151.10),
    "Wollongong City":(-34.43,150.89),"Newcastle":(-32.93,151.78),
}

with map_col:
    st.markdown("### Project map")
    m=folium.Map(location=[-33.2,151.1],zoom_start=7,tiles=None)
    folium.TileLayer(
        tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        attr="© OpenStreetMap contributors",
        name="OpenStreetMap",
        overlay=False,
        control=True,
    ).add_to(m)
    plotted=0
    for _,p in f.iterrows():
        try:
            lat=float(p.lat); lon=float(p.lon)
            if not (-37<lat<-28 and 140<lon<154): raise ValueError
        except:
            centroid=None
            for name,xy in LGA_CENTROIDS.items():
                if key(name)==key(p.lga):
                    centroid=xy; break
            if not centroid: continue
            lat,lon=centroid
        status_key=key(p.status)
        if "exhibition" in status_key:
            fill="#c95b22"
        elif "assessment" in status_key:
            fill="#e7a06d"
        elif "determination" in status_key or "approved" in status_key:
            fill="#9d9d9d"
        else:
            fill="#55514d"
        popup=(f"<b>{clean(p.project_number)}</b><br>{clean(p.title)}"
               f"<br>{clean(p.lga)}<br>Status: {clean(p.status)}")
        folium.CircleMarker([lat,lon],radius=5,weight=1,fill=True,
                            fill_color=fill,color=fill,fill_opacity=.8,
                            popup=popup,tooltip=clean(p.project_number)).add_to(m)
        plotted+=1
    st_folium(m,height=500,width=None,key="wph-map")
    st.caption(f"{plotted:,} projects shown. Projects without published coordinates are shown at their LGA centroid. Base map: OpenStreetMap. This tracker does not use a map API or API key.")

with result_col:
    st.markdown('<div class="result-card">',unsafe_allow_html=True)
    st.markdown(f'<div class="metric-number">{total:,}</div><div style="font-family:Georgia,serif;font-size:17px;margin-top:5px;">projects match your filters</div>',unsafe_allow_html=True)
    st.divider()
    st.download_button(
        "⇩  Export results (CSV)",
        f.to_csv(index=False).encode("utf-8"),
        "weir_phillips_heritage_ssda_projects.csv",
        "text/csv",
        use_container_width=True
    )
    st.divider()
    st.markdown(f'<div class="small-muted">Database: {len(df):,} projects loaded</div>',unsafe_allow_html=True)
    if st.button("↻ Reload database",use_container_width=True):
        reload_database()
    st.caption("Data is refreshed automatically by GitHub Actions. Use Reload database after a completed refresh.")
    st.markdown('</div>',unsafe_allow_html=True)

st.write("")
st.markdown("### Projects")

if len(f):
    display=f.copy()
    display["Project Name"]=display["title"]
    display["Address"]=display["address"]
    display["LGA"]=display["lga"]
    display["Status"]=display["status"]
    display["Development Type"]=display["development_type"]
    display["Date Updated"]=display["last_modified"]
    table_cols=["Project Name","Address","LGA","Status","Development Type","Date Updated"]
    st.dataframe(display[table_cols].sort_values("Project Name"),
                 use_container_width=True,hide_index=True,height=430)

    project_numbers=f.project_number.tolist()
    choice=st.selectbox(
        "Open project",
        project_numbers,
        format_func=lambda x:f"{x} — {f.loc[f.project_number.eq(x),'title'].iloc[0]}",
    )
    p=f[f.project_number.eq(choice)].iloc[0]
    st.markdown("---")
    st.markdown(f"## {clean(p.title)}")
    st.caption(clean(p.project_number))
    a,b,c=st.columns(3)
    a.metric("Status",clean(p.status) or "—")
    b.metric("LGA",clean(p.lga) or "—")
    c.metric("Assessment",clean(p.assessment_type) or "—")
    st.markdown(f"**Address:** {clean(p.address) or '—'}")
    if clean(p.description):
        st.markdown(f"**Proposal:** {clean(p.description)}")
    a,b,c=st.columns(3)
    a.metric("Dwellings",p.dwellings if p.dwellings else "—")
    b.metric("Height",p.height if p.height else "—")
    c.metric("Estimated cost",p.estimated_cost if p.estimated_cost else "—")
    if clean(p.url):
        st.link_button("Open official NSW project",p.url)

    c=sqlite3.connect(DB)
    hist=pd.read_sql_query(
        "SELECT status,observed_at FROM status_history WHERE project_number=? ORDER BY observed_at",
        c,params=(choice,)
    )
    c.close()
    if len(hist):
        st.markdown("### Status history")
        st.dataframe(hist,use_container_width=True,hide_index=True)
else:
    st.info("No projects match the current filters. Try clearing one or more filters.")

st.divider()
st.markdown(
    '<div style="display:flex;justify-content:space-between;color:#77716b;font-size:12px;">'
    '<span>Weir Phillips Heritage · Heritage · Planning · Advisory</span>'
    '<span>NSW SSDA project information · Verify critical information against the official record.</span>'
    '</div>',
    unsafe_allow_html=True
)
