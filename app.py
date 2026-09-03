import base64
import re
import sqlite3
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

BASE = Path(__file__).parent
DB = BASE / "data" / "tracker.sqlite3"
LOGO = BASE / "WPHeritage_Logo_Horiz_RGB.jpg"

st.set_page_config(
    page_title="Weir Phillips Heritage SSDA Tracker",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
html, body, [class*="css"] { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
h1,h2,h3,h4 { font-family:Georgia,"Times New Roman",serif !important; font-weight:400 !important; }
[data-testid="stAppViewContainer"], [data-testid="stHeader"] { background:#fbfaf8; }
.main .block-container { max-width:1500px; padding-top:.7rem; padding-bottom:2rem; }
.wph-header { background:#fff; border-bottom:1px solid #dedbd6; padding:22px 28px 18px; margin:-.7rem -3rem 1.1rem; }
.wph-header-inner { display:flex; align-items:center; gap:24px; }
.wph-logo { width:355px; max-width:38%; object-fit:contain; }
.wph-divider { height:54px; width:1px; background:#c9c5bf; }
.wph-title { font-family:Georgia,serif; font-size:28px; color:#171513; line-height:1.15; }
.wph-subtitle { margin-top:5px; color:#65615c; font-size:14px; }
.wph-orange { color:#c95b22; }
.section-label { color:#c95b22; font-size:13px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; }
.metric-card { background:#fff; border-top:1px solid #dedbd6; border-bottom:1px solid #dedbd6; padding:15px 10px 14px; text-align:center; min-height:96px; }
.metric-number { font-family:Georgia,serif; color:#c95b22; font-size:32px; line-height:1; }
.metric-label { margin-top:7px; font-family:Georgia,serif; font-size:16px; font-weight:600; }
.metric-sub { color:#77716b; font-size:11px; margin-top:3px; }
.result-card,.detail-card { background:#fff; border:1px solid #dedbd6; border-radius:7px; padding:20px 22px; }
.small-muted { color:#77716b; font-size:12px; }
.stButton > button { border-radius:5px; }
div[data-testid="stSidebar"] { background:#fbfaf8; border-right:1px solid #dedbd6; }
div[data-testid="stSidebar"] .block-container { padding-top:1.5rem; padding-bottom:2rem; max-height:calc(100vh - 1rem); overflow-y:auto; overflow-x:hidden; }
div[data-baseweb="popover"] { max-height:70vh !important; }
div[data-baseweb="popover"] [role="listbox"],div[data-baseweb="popover"] [data-baseweb="menu"] { max-height:55vh !important; overflow-y:auto !important; }
div[data-testid="stSidebar"] label { font-weight:600; }
div[data-testid="stSidebar"] [data-baseweb="select"] { background:#fff; }
a { color:#c95b22 !important; }
</style>
""", unsafe_allow_html=True)


def clean(v):
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip()


def norm(v):
    return clean(v).casefold()


def split_lgas(value):
    text = clean(value)
    if not text:
        return []
    # Portal uses comma-separated LGAs for multi-council projects.
    return [clean(x) for x in re.split(r"\s*,\s*", text) if clean(x)]


@st.cache_data(ttl=600, show_spinner=False)
def load_db(path_str, mtime):
    c = sqlite3.connect(path_str)
    try:
        df = pd.read_sql_query("SELECT * FROM projects", c)
    except Exception:
        df = pd.DataFrame()
    c.close()
    return df.fillna("")


def get_db():
    try:
        mtime = DB.stat().st_mtime
    except FileNotFoundError:
        mtime = 0
    return load_db(str(DB), mtime)


def reload_database():
    load_db.clear()
    st.rerun()


df = get_db()

logo_b64 = ""
if LOGO.exists():
    logo_b64 = base64.b64encode(LOGO.read_bytes()).decode()

st.markdown(f"""
<div class="wph-header"><div class="wph-header-inner">
<img class="wph-logo" src="data:image/jpeg;base64,{logo_b64}">
<div class="wph-divider"></div><div>
<div class="wph-title">Weir Phillips Heritage <span class="wph-orange">SSDA Tracker</span></div>
<div class="wph-subtitle">State Significant Development Applications in NSW</div>
</div></div></div>
""", unsafe_allow_html=True)

if df.empty:
    st.warning("The project database has not been populated yet.")
    st.info("Run the “Refresh NSW SSDA data” workflow in GitHub once, then reload this page.")
    st.stop()

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown('<div class="section-label">Filters</div>', unsafe_allow_html=True)
    st.divider()

    if st.button("Clear all filters", use_container_width=True):
        for k in ("search", "lga_filter", "status_filter", "type_filter"):
            st.session_state.pop(k, None)
        st.rerun()

    st.markdown("**Search projects**")
    q = st.text_input("Search", placeholder="Project number, title, address or keywords…", label_visibility="collapsed")

    # Build unique LGA choices by splitting multi-LGA records. This prevents
    # 'North Sydney' appearing both as a standalone value and embedded in a
    # comma-separated value.
    lga_values = set()
    for value in df.get("lga", pd.Series(dtype=str)):
        lga_values.update(split_lgas(value))
    lga_options = sorted(lga_values, key=norm)

    def unique_options(col):
        vals = {clean(v) for v in df.get(col, pd.Series(dtype=str)) if clean(v)}
        return sorted(vals, key=norm)

    status_options = unique_options("status")
    type_options = unique_options("development_type")

    st.markdown("**LGA**")
    lga = st.multiselect("LGA", lga_options, key="lga_filter", placeholder="All LGAs", label_visibility="collapsed")
    st.markdown("**Project Status**")
    status = st.multiselect("Status", status_options, key="status_filter", placeholder="All Statuses", label_visibility="collapsed")
    st.markdown("**Development Type**")
    dtype = st.multiselect("Development type", type_options, key="type_filter", placeholder="All Development Types", label_visibility="collapsed")

    st.divider()
    st.markdown('<div class="small-muted">Click a row in the project table to open that project. The map uses project coordinates where available and LGA locations as a fallback.</div>', unsafe_allow_html=True)

# ---------- Filtering ----------
f = df.copy()
if q:
    qk = norm(q)
    searchable = ["project_number", "title", "lga", "address", "description", "development_type", "status", "assessment_type", "applicant"]
    mask = pd.Series(False, index=f.index)
    for col in searchable:
        if col in f.columns:
            mask |= f[col].map(norm).str.contains(qk, regex=False, na=False)
    f = f[mask]

if lga:
    wanted = {norm(x) for x in lga}
    f = f[f["lga"].map(lambda x: bool(wanted.intersection(norm(y) for y in split_lgas(x))))]
if status:
    wanted = {norm(x) for x in status}
    f = f[f["status"].map(norm).isin(wanted)]
if dtype:
    wanted = {norm(x) for x in dtype}
    f = f[f["development_type"].map(norm).isin(wanted)]

# ---------- Metrics ----------
total = len(f)
exhibition = int(f["status"].map(norm).str.contains("exhibition", regex=False).sum()) if total else 0
determined = int(f["status"].map(norm).str.contains("determination", regex=False).sum()) if total else 0
assessment = int(f["status"].map(norm).str.contains("assessment", regex=False).sum()) if total else 0
other = max(total - exhibition - determined - assessment, 0)

for c, (num, label, sub) in zip(st.columns(5), [
    (f"{total:,}", "Total Projects", "Matching your filters"),
    (f"{exhibition:,}", "Exhibition", "Current exhibition stage"),
    (f"{determined:,}", "Determined", "Determination stage"),
    (f"{assessment:,}", "Under Assessment", "Assessment stage"),
    (f"{other:,}", "Other / Earlier", "Other statuses"),
]):
    with c:
        st.markdown(f'<div class="metric-card"><div class="metric-number">{num}</div><div class="metric-label">{label}</div><div class="metric-sub">{sub}</div></div>', unsafe_allow_html=True)

st.write("")

# ---------- Map ----------
LGA_CENTROIDS = {
    "North Sydney": (-33.838, 151.207), "City of Sydney": (-33.874, 151.206), "Bayside": (-33.94, 151.14),
    "Waverley": (-33.90, 151.26), "City of Canada Bay": (-33.86, 151.13), "Inner West": (-33.88, 151.17),
    "City of Parramatta": (-33.815, 151.00), "The Hills Shire": (-33.73, 150.96), "Ku-ring-gai": (-33.72, 151.13),
    "Willoughby": (-33.80, 151.20), "Ryde": (-33.81, 151.10), "Blacktown": (-33.77, 150.91),
    "Cumberland": (-33.84, 151.01), "Canterbury-Bankstown": (-33.91, 150.99), "Liverpool": (-33.92, 150.92),
    "Penrith": (-33.75, 150.70), "Sutherland Shire": (-34.03, 151.06), "Georges River": (-33.97, 151.10),
    "Wollongong City": (-34.43, 150.89), "Newcastle City": (-32.93, 151.78), "Newcastle": (-32.93, 151.78),
}


def project_point(p):
    try:
        lat, lon = float(p.get("lat")), float(p.get("lon"))
        if -37 < lat < -28 and 140 < lon < 154:
            return lat, lon, True
    except Exception:
        pass
    for lga_name in split_lgas(p.get("lga", "")):
        for name, xy in LGA_CENTROIDS.items():
            if norm(name) == norm(lga_name):
                return xy[0], xy[1], False
    return None

map_col, side_col = st.columns([2.25, 1])
with map_col:
    st.markdown("### Project map")
    # Rendering 10,000 interactive Folium markers is slow. For broad searches,
    # use an LGA summary map; once filters narrow the result, show individual projects.
    individual = total <= 2000
    m = folium.Map(location=[-33.2, 151.1], zoom_start=7, tiles=None, prefer_canvas=True)
    folium.TileLayer(tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attr="© OpenStreetMap contributors", name="OpenStreetMap", overlay=False, control=True).add_to(m)

    if individual:
        cluster = MarkerCluster(name="Projects", options={"maxClusterRadius": 45, "disableClusteringAtZoom": 11}).add_to(m)
        plotted = 0
        for _, p in f.iterrows():
            point = project_point(p)
            if not point:
                continue
            lat, lon, precise = point
            sk = norm(p.get("status", ""))
            fill = "#c95b22" if "exhibition" in sk else "#e7a06d" if "assessment" in sk else "#9d9d9d" if "determination" in sk or "approved" in sk else "#55514d"
            popup = f"<b>{clean(p.get('project_number'))}</b><br>{clean(p.get('title'))}<br>{clean(p.get('lga'))}<br>Status: {clean(p.get('status'))}"
            folium.CircleMarker([lat, lon], radius=5 if precise else 4, weight=1, fill=True, fill_color=fill, color=fill, fill_opacity=.8, popup=popup, tooltip=clean(p.get("project_number")), opacity=.9).add_to(cluster)
            plotted += 1
        st_folium(m, height=500, width=None, key="wph-map")
        st.caption(f"{plotted:,} project locations shown. Precise coordinates are used where published; otherwise LGA locations are used. OpenStreetMap base map.")
    else:
        counts = {}
        for _, p in f.iterrows():
            for name in split_lgas(p.get("lga", "")):
                counts[name] = counts.get(name, 0) + 1
        plotted = 0
        for name, count in counts.items():
            point = LGA_CENTROIDS.get(name)
            if not point:
                continue
            folium.CircleMarker(point, radius=max(7, min(24, 6 + count ** 0.35)), weight=1, fill=True, fill_color="#c95b22", color="#c95b22", fill_opacity=.55, popup=f"<b>{name}</b><br>{count:,} projects").add_to(m)
            plotted += 1
        st_folium(m, height=500, width=None, key="wph-map-summary")
        st.info(f"{total:,} projects match your filters. To keep the map responsive, the map is showing {plotted} LGA summaries. Narrow the filters to 2,000 projects or fewer to show individual project markers.")

with side_col:
    st.markdown('<div class="result-card">', unsafe_allow_html=True)
    st.markdown(f'<div class="metric-number">{total:,}</div><div style="font-family:Georgia,serif;font-size:17px;margin-top:5px;">projects match your filters</div>', unsafe_allow_html=True)
    st.divider()
    st.download_button("⇩  Export results (CSV)", f.to_csv(index=False).encode("utf-8"), "weir_phillips_heritage_ssda_projects.csv", "text/csv", use_container_width=True)
    st.divider()
    st.markdown(f'<div class="small-muted">Database: {len(df):,} projects loaded</div>', unsafe_allow_html=True)
    if st.button("↻ Reload database", use_container_width=True):
        reload_database()
    st.caption("Data is refreshed automatically by GitHub Actions.")
    st.markdown('</div>', unsafe_allow_html=True)

# ---------- Project table / selected project ----------
st.write("")
st.markdown("### Projects")

if len(f):
    display = f.copy()
    display["Project"] = display["title"]
    display["Application"] = display["project_number"]
    display["Address"] = display["address"]
    display["LGA"] = display["lga"]
    display["Status"] = display["status"]
    display["Type"] = display["development_type"]
    display["Dwellings"] = display.get("dwellings", "")
    display["Height"] = display.get("height", "")
    display["GFA"] = display.get("gfa", "")
    display["Cost"] = display.get("estimated_cost", "")
    display["Affordable Housing"] = display.get("affordable_housing", "")
    table_cols = ["Application", "Project", "Address", "LGA", "Status", "Type", "Dwellings", "Height", "GFA", "Cost"]
    table_df = display[table_cols].sort_values(["Project", "Application"], na_position="last").reset_index(drop=True)

    event = st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        height=480,
        on_select="rerun",
        selection_mode="single-row",
        key="project_table",
        column_config={
            "Application": st.column_config.TextColumn("Application", width="small"),
            "Project": st.column_config.TextColumn("Project", width="large"),
            "Address": st.column_config.TextColumn("Address", width="large"),
            "LGA": st.column_config.TextColumn("LGA", width="medium"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
            "Type": st.column_config.TextColumn("Type", width="medium"),
            "Dwellings": st.column_config.NumberColumn("Dwellings", format="%.0f"),
            "Height": st.column_config.NumberColumn("Height / storeys", format="%.1f"),
            "GFA": st.column_config.NumberColumn("GFA / m²", format="%,.0f"),
            "Cost": st.column_config.NumberColumn("Estimated cost", format="$%,.0f"),
        },
    )

    selected_rows = list(getattr(event.selection, "rows", [])) if hasattr(event, "selection") else []
    if selected_rows:
        selected_application = table_df.iloc[selected_rows[0]]["Application"]
        p = f[f.project_number.eq(selected_application)].iloc[0]
    else:
        # No automatic selection means the table is immediately usable without a second scrollbar.
        p = None
        st.caption("Select a project row above to view its details.")

    if p is not None:
        st.markdown("---")
        st.markdown(f"## {clean(p.title)}")
        st.caption(clean(p.project_number))
        a,b,c,d = st.columns(4)
        a.metric("Status", clean(p.status) or "—")
        b.metric("LGA", clean(p.lga) or "—")
        c.metric("Assessment", clean(p.assessment_type) or "—")
        d.metric("Development type", clean(p.development_type) or "—")

        st.markdown('<div class="detail-card">', unsafe_allow_html=True)
        left, right = st.columns(2)
        with left:
            st.markdown(f"**Address**\n\n{clean(p.address) or '—'}")
            st.markdown(f"**Applicant**\n\n{clean(getattr(p, 'applicant', '')) or '—'}")
            st.markdown(f"**Decision**\n\n{clean(p.decision) or '—'}")
            st.markdown(f"**Determination date**\n\n{clean(p.determination_date) or '—'}")
        with right:
            def fmt_num(v, suffix=""):
                try:
                    if v == "" or pd.isna(v): return "—"
                    return f"{float(v):,.0f}{suffix}"
                except Exception:
                    return clean(v) or "—"
            st.markdown(f"**Dwellings**\n\n{fmt_num(getattr(p, 'dwellings', ''))}")
            st.markdown(f"**Height / storeys**\n\n{fmt_num(getattr(p, 'height', ''))}")
            st.markdown(f"**GFA**\n\n{fmt_num(getattr(p, 'gfa', ''), ' m²')}")
            st.markdown(f"**Estimated cost**\n\n{fmt_num(getattr(p, 'estimated_cost', ''))}")
            st.markdown(f"**Affordable housing**\n\n{fmt_num(getattr(p, 'affordable_housing', ''))}")

        st.markdown("### Proposal")
        st.write(clean(p.description) or "Additional project details are not available in the structured record. See the official NSW Planning Portal record for the complete project documentation.")
        if clean(p.url):
            st.link_button("Open official NSW Planning Portal record ↗", clean(p.url))
        st.markdown('</div>', unsafe_allow_html=True)
else:
    st.info("No projects match the current filters.")

st.write("")
st.caption("Weir Phillips Heritage · SSDA Tracker · Source: NSW Planning Portal public State Significant Applications records.")
