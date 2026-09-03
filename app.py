import base64
import hashlib
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
.main .block-container { max-width:1550px; padding-top:.7rem; padding-bottom:2rem; }
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
.result-card,.detail-card { background:#fff; border:1px solid #dedbd6; border-radius:7px; padding:18px 20px; }
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
    return [clean(x) for x in re.split(r"\s*,\s*", text) if clean(x)]


@st.cache_data(ttl=900, show_spinner=False)
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
        st.session_state.pop("project_table", None)
        st.rerun()

    st.markdown("**Search projects**")
    q = st.text_input("Search", placeholder="Project number, title, address or keywords…", label_visibility="collapsed", key="search")

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
    st.markdown('<div class="small-muted">The map and project table use the same filtered dataset. Click a table row to open its details. Exact project coordinates are preferred; LGA locations are used as an approximate fallback.</div>', unsafe_allow_html=True)

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
# Common NSW LGA centres. These are deliberately labelled approximate locations.
LGA_CENTROIDS = {
    "Albury City": (-36.080, 146.916), "Armidale Regional": (-30.515, 151.665), "Ballina": (-28.865, 153.565),
    "Bathurst Regional": (-33.419, 149.577), "Bayside": (-33.940, 151.140), "Blacktown": (-33.770, 150.910),
    "Blue Mountains": (-33.700, 150.310), "Broken Hill": (-31.954, 141.453), "Byron": (-28.647, 153.612),
    "Byron Shire": (-28.647, 153.612), "Camden": (-34.055, 150.695), "Campbelltown": (-34.068, 150.814),
    "Canada Bay": (-33.862, 151.127), "City of Canada Bay": (-33.862, 151.127),
    "Canterbury-Bankstown": (-33.912, 150.994), "Central Coast": (-33.430, 151.340),
    "Cessnock": (-32.833, 151.356), "Clarence Valley": (-29.694, 152.934), "Coffs Harbour": (-30.296, 153.114),
    "Cumberland": (-33.840, 151.010), "Dubbo Regional": (-32.256, 148.601), "Dungog": (-32.405, 151.759),
    "Eurobodalla": (-35.706, 150.176), "Fairfield City": (-33.870, 150.957), "Forbes": (-33.384, 148.008),
    "Georges River": (-33.970, 151.100), "Goulburn Mulwaree": (-34.754, 149.720), "Griffith": (-34.289, 146.041),
    "Hawkesbury": (-33.600, 150.750), "Hornsby": (-33.703, 151.099), "Hunters Hill": (-33.835, 151.146),
    "Inner West": (-33.875, 151.170), "Kiama": (-34.671, 150.855), "Ku-ring-gai": (-33.720, 151.130),
    "Lake Macquarie City": (-33.000, 151.600), "Lane Cove": (-33.816, 151.166), "Lithgow": (-33.482, 150.158),
    "Liverpool": (-33.920, 150.920), "Liverpool Plains": (-31.514, 150.676), "Mid-Western Regional": (-32.594, 149.588),
    "Mid-Coast": (-31.896, 152.460), "Maitland": (-32.734, 151.557), "Mosman": (-33.830, 151.245),
    "Muswellbrook": (-32.266, 150.891), "Nambucca Valley": (-30.641, 152.990), "Newcastle City": (-32.928, 151.781),
    "Northern Beaches": (-33.750, 151.280), "North Sydney": (-33.838, 151.207), "Orange City": (-33.283, 149.100),
    "Parkes": (-33.138, 148.176), "Parramatta": (-33.815, 151.000), "City of Parramatta": (-33.815, 151.000),
    "Penrith": (-33.750, 150.700), "Port Macquarie-Hastings": (-31.433, 152.908), "Port Stephens": (-32.720, 152.100),
    "Queanbeyan-Palerang Regional": (-35.354, 149.233), "Randwick": (-33.914, 151.241), "Richmond Valley": (-28.864, 153.200),
    "Ryde": (-33.810, 151.100), "Shoalhaven": (-34.870, 150.600), "Singleton": (-32.568, 151.166),
    "Snowy Monaro Regional": (-36.220, 148.920), "Snowy Valleys": (-35.550, 148.150), "Strathfield": (-33.880, 151.090),
    "Sutherland Shire": (-34.030, 151.060), "Tamworth Regional": (-31.092, 150.930), "Temora": (-34.448, 147.535),
    "Tenterfield": (-29.050, 152.020), "The Hills Shire": (-33.730, 150.960), "Tweed Shire": (-28.330, 153.440),
    "Upper Hunter Shire": (-32.050, 150.580), "Wagga Wagga City": (-35.108, 147.370), "Walgett": (-30.024, 148.119),
    "Warrumbungle Shire": (-31.300, 149.850), "Waverley": (-33.900, 151.260), "Willoughby City": (-33.800, 151.200),
    "Wollondilly": (-34.020, 150.610), "Wollongong City": (-34.430, 150.890), "Woollahra Municipality": (-33.887, 151.250),
    "Yass Valley": (-34.820, 148.910), "Central Darling": (-31.970, 143.550), "Cootamundra-Gundagai Regional": (-34.640, 148.030),
    "Cowra": (-33.835, 148.690), "Dareton": (-34.090, 142.040), "Deniliquin": (-35.530, 144.960),
    "Edward River": (-35.530, 144.960), "Federation": (-35.990, 146.005), "Gwydir": (-29.850, 150.530),
    "Inverell": (-29.775, 151.112), "Junee": (-34.870, 147.580), "Leeton": (-34.550, 146.400),
    "Lockhart": (-35.220, 146.720), "Moree Plains": (-29.465, 149.841), "Narrabri": (-30.326, 149.783),
    "Narrandera": (-34.745, 146.550), "New England Tablelands": (-30.510, 151.670), "Temora Shire": (-34.450, 147.530),
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


def jitter(point, project_number):
    """Give projects sharing an approximate LGA point a deterministic small offset."""
    lat, lon = point
    digest = hashlib.md5(clean(project_number).encode("utf-8")).hexdigest()
    a = int(digest[:8], 16) / 0xFFFFFFFF
    b = int(digest[8:16], 16) / 0xFFFFFFFF
    radius = 0.004 + 0.012 * a
    angle = 6.28318530718 * b
    return lat + radius * __import__("math").cos(angle), lon + radius * __import__("math").sin(angle)


map_col, side_col = st.columns([2.25, 1])
with map_col:
    st.markdown("### Project map")
    map_key = "wph-map-" + hashlib.md5("|".join(sorted(f["project_number"].astype(str))).encode()).hexdigest()[:12]
    m = folium.Map(location=[-33.2, 151.1], zoom_start=7, tiles=None, prefer_canvas=True)
    folium.TileLayer(tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attr="© OpenStreetMap contributors", name="OpenStreetMap", overlay=False, control=True).add_to(m)

    # Individual projects are shown for a narrowed result set. For broad results,
    # use LGA summaries so the map stays responsive.
    individual = total <= 1500
    plotted = 0
    exact = 0
    approximate = 0

    if individual:
        cluster = MarkerCluster(name="Projects", options={"maxClusterRadius": 42, "disableClusteringAtZoom": 12}).add_to(m)
        bounds = []
        for _, p in f.iterrows():
            point = project_point(p)
            if not point:
                continue
            lat, lon, precise = point
            if not precise:
                lat, lon = jitter((lat, lon), p.get("project_number", ""))
                approximate += 1
            else:
                exact += 1
            bounds.append([lat, lon])
            sk = norm(p.get("status", ""))
            fill = "#c95b22" if "exhibition" in sk else "#e7a06d" if "assessment" in sk else "#9d9d9d" if "determination" in sk or "approved" in sk else "#55514d"
            popup = f"<b>{clean(p.get('project_number'))}</b><br>{clean(p.get('title'))}<br>{clean(p.get('lga'))}<br>Status: {clean(p.get('status'))}<br><small>{'Approximate LGA location' if not precise else 'Project coordinates'}</small>"
            folium.CircleMarker([lat, lon], radius=5 if precise else 4, weight=1, fill=True, fill_color=fill, color=fill, fill_opacity=.8, popup=popup, tooltip=clean(p.get("project_number")), opacity=.9).add_to(cluster)
            plotted += 1
        if bounds:
            m.fit_bounds(bounds, padding=(20, 20))
        st_folium(m, height=500, width=None, key=map_key)
        st.caption(f"{plotted:,} project locations shown ({exact:,} exact, {approximate:,} approximate). Approximate markers use the LGA centre with a small deterministic offset so multiple projects remain visible. OpenStreetMap base map.")
    else:
        counts = {}
        for _, p in f.iterrows():
            for name in split_lgas(p.get("lga", "")):
                counts[name] = counts.get(name, 0) + 1
        bounds = []
        for name, count in counts.items():
            point = next((xy for n, xy in LGA_CENTROIDS.items() if norm(n) == norm(name)), None)
            if not point:
                continue
            bounds.append(list(point))
            folium.CircleMarker(point, radius=max(7, min(24, 6 + count ** 0.35)), weight=1, fill=True, fill_color="#c95b22", color="#c95b22", fill_opacity=.55, popup=f"<b>{name}</b><br>{count:,} projects<br><small>Approximate LGA location</small>").add_to(m)
            plotted += 1
        if bounds:
            m.fit_bounds(bounds, padding=(20, 20))
        st_folium(m, height=500, width=None, key=map_key + "-summary")
        st.info(f"{total:,} projects match your filters. The map is showing {plotted} LGA summaries. Narrow the filters to 1,500 projects or fewer to show individual projects.")

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

# ---------- Project table + detail ----------
st.write("")
st.markdown("### Projects")

if len(f):
    display = f.copy()
    display["Project"] = display.get("title", "")
    display["Application"] = display.get("project_number", "")
    display["Address"] = display.get("address", "")
    display["LGA"] = display.get("lga", "")
    display["Status"] = display.get("status", "")
    display["Type"] = display.get("development_type", "")
    display["Dwellings"] = display.get("dwellings", "")
    display["Height"] = display.get("height", "")
    display["GFA"] = display.get("gfa", "")
    display["Cost"] = display.get("estimated_cost", "")
    table_cols = ["Application", "Project", "Address", "LGA", "Status", "Type", "Dwellings", "Height", "GFA", "Cost"]
    table_df = display[table_cols].sort_values(["Project", "Application"], na_position="last").reset_index(drop=True)

    table_col, detail_col = st.columns([1.65, 1])
    with table_col:
        st.caption(f"Showing {len(table_df):,} matching projects. Click a row to open its details.")
        event = st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            height=560,
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
    p = None
    if selected_rows:
        selected_application = table_df.iloc[selected_rows[0]]["Application"]
        matches = f[f.project_number.astype(str).eq(str(selected_application))]
        if len(matches):
            p = matches.iloc[0]

    with detail_col:
        st.markdown('<div class="detail-card">', unsafe_allow_html=True)
        if p is None:
            st.markdown("### Project details")
            st.markdown("Select a project row on the left to view its details here.")
            st.markdown('<div class="small-muted">This panel stays alongside the table so you no longer need to scroll down to a separate project selector.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f"### {clean(p.get('title')) or 'Project'}")
            st.caption(clean(p.get('project_number')))
            a, b = st.columns(2)
            a.metric("Status", clean(p.get("status")) or "—")
            b.metric("LGA", clean(p.get("lga")) or "—")
            st.markdown(f"**Address**  \n{clean(p.get('address')) or '—'}")
            st.markdown(f"**Assessment type**  \n{clean(p.get('assessment_type')) or '—'}")
            st.markdown(f"**Development type**  \n{clean(p.get('development_type')) or '—'}")
            st.divider()
            st.markdown("**Project metrics**")
            m1, m2 = st.columns(2)
            m1.metric("Dwellings", clean(p.get("dwellings")) or "—")
            m2.metric("Height / storeys", clean(p.get("height")) or "—")
            m3, m4 = st.columns(2)
            m3.metric("GFA / m²", clean(p.get("gfa")) or "—")
            m4.metric("Estimated cost", clean(p.get("estimated_cost")) or "—")
            m5, m6 = st.columns(2)
            m5.metric("Affordable housing", clean(p.get("affordable_housing")) or "—")
            m6.metric("Applicant", clean(p.get("applicant")) or "—")
            st.divider()
            st.markdown(f"**Decision**  \n{clean(p.get('decision')) or '—'}")
            st.markdown(f"**Determination date**  \n{clean(p.get('determination_date')) or '—'}")
            if clean(p.get("description")):
                st.markdown("**Proposal**")
                st.write(clean(p.get("description")))
            if clean(p.get("url")):
                st.link_button("Open official NSW Planning Portal record ↗", clean(p.get("url")), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
else:
    st.info("No projects match the current filters.")

st.write("")
st.caption("Weir Phillips Heritage · SSDA Tracker · Source: NSW Planning Portal public State Significant Applications records.")
