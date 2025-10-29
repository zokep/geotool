import streamlit as st
import pandas as pd, geopandas as gpd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import shapely.geometry as geom 
from shapely.geometry import Point, LineString, Polygon
import tempfile, zipfile, io, os, math, shutil, subprocess, simplekml
from pathlib import Path
from io import StringIO, BytesIO

st.set_page_config(page_title="GeoTool Streamlit", layout="wide")
df = None

st.markdown("""
    <style>
    .stApp {
        background: #0b1117;color:#e6edf3
    }
    section[data-testid="stSidebar"] .stMultiSelect {
        min-height: 120px !important;
        max-height: 300px !important;
        overflow-y: auto !important;
    }
    </style>
    """, unsafe_allow_html=True)

# ---------- SIDEBAR ----------
st.sidebar.header("🗂️ GeoTool Menu Utama")

uploaded = st.sidebar.file_uploader(
    "Upload data (CSV, XLSX, GeoJSON, KML, KMZ)",
    type=["csv", "xlsx", "geojson", "kml", "kmz"],
    accept_multiple_files=False
)
st.sidebar.markdown(" 🪶 Opsi Popup")




df = None
options = []

if uploaded:
    ext = uploaded.name.split('.')[-1].lower()
    try:
        if ext in ["csv", "xlsx"]:
            # deteksi otomatis untuk csv dan xlsx
            if ext == "csv":
                uploaded.seek(0)
                text = uploaded.read().decode('utf-8', errors='ignore')
                delimiter = ';' if ';' in text.splitlines()[0] else ','
                df = pd.read_csv(StringIO(text), delimiter=delimiter)
            else:
                df = pd.read_excel(uploaded)
        else:
            # format geospasial: kml/kmz/geojson
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
            tmp.write(uploaded.getbuffer())
            tmp.close()
            df = gpd.read_file(tmp.name)
        options = list(df.columns)
    except Exception as e:
        st.sidebar.error(f"Gagal membaca file: {e}")
        df = None
        options = []

# --- Multiselect selalu tampil ---
popup_cols = st.sidebar.multiselect(
    "Pilih kolom yang ingin ditampilkan di popup (opsional):",
    options=options,
    default=options[:min(5, len(options))]
)

# info bantu
if not options:
    st.sidebar.caption("Belum ada file yang dimuat atau file tidak memiliki kolom yang bisa dibaca.")

show_latlon = st.sidebar.checkbox("Selalu tampilkan Latitude & Longitude", value=True)


basemap_choice = st.sidebar.radio(
    "Basemap:",
    ["Google Hybrid", "OpenStreetMap", "ESRI Sat", "Blank"]
)

fit_bounds = st.sidebar.checkbox("🧭 Fit to Bounds Otomatis", value=True)
st.sidebar.button("🔄 Reset Peta", on_click=lambda: st.session_state.pop('data', None))

st.sidebar.markdown("---")
st.sidebar.subheader("💾 Ekspor Data")
# -------- Tombol ekspor 2 kolom per baris --------
col1, col2 = st.sidebar.columns(2)
with col1:
    exp_kml = st.button("Export KML")
    exp_geojson = st.button("Export GeoJSON")
    exp_shp = st.button("Export SHP (ZIP)")
with col2:
    exp_kmz = st.button("Export KMZ")
    exp_csv = st.button("Export CSV")
    exp_pdf = st.button("Export GeoPDF")
st.sidebar.markdown("---")
st.sidebar.caption("Versi Streamlit Mirip HTML | Offline-ready")

# ---------- UTILITAS ----------
def detect_lat_lon(df):
    """Mendeteksi kolom koordinat berdasarkan nama ATAU nilai"""
    lat_col = next((c for c in df.columns if any(k in c.lower() for k in ['lat','lintang','y'])), None)
    lon_col = next((c for c in df.columns if any(k in c.lower() for k in ['lon','long','bujur','x'])), None)
    if lat_col and lon_col:
        # tukar kalau ketahuan terbalik
        sample_lat = df[lat_col].dropna().astype(float).head(5)
        sample_lon = df[lon_col].dropna().astype(float).head(5)
        if sample_lat.abs().mean() > 90 and sample_lon.abs().mean() <= 90:
            lat_col, lon_col = lon_col, lat_col
    return lat_col, lon_col


def export_to_shp(gdf):
    """Ekspor GeoDataFrame menjadi file SHP (ZIP)"""
    try:
        out_dir = tempfile.mkdtemp()
        shp_path = os.path.join(out_dir, "data.shp")
        gdf.to_file(shp_path)
        zip_path = os.path.join(out_dir, "shapefile.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for ext in [".shp", ".shx", ".dbf", ".prj"]:
                fpath = shp_path.replace(".shp", ext)
                if os.path.exists(fpath):
                    z.write(fpath, os.path.basename(fpath))
        return zip_path
    except Exception as e:
        st.error(f"Gagal ekspor SHP: {e}")
        return None


def export_to_kml(df, lat_col, lon_col, name_col=None, description_cols=None, output_path=None):
    
    # Validate columns
    missing = [col for col in [lat_col, lon_col] if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in DataFrame: {missing}")
    
    if name_col and name_col not in df.columns:
        name_col = None

    kml = simplekml.Kml()
    folder = kml.newfolder(name="Points")

    for _, row in df.iterrows():
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
            if pd.isna(lat) or pd.isna(lon):
                continue

            name = str(row[name_col]) if name_col and pd.notna(row[name_col]) else f"Point_{_}"

            # Create description
            description = ""
            if description_cols:
                desc_lines = []
                for col in description_cols:
                    if col in df.columns and pd.notna(row[col]):
                        desc_lines.append(f"<b>{col}:</b> {row[col]}")
                if desc_lines:
                    description = "<br>".join(desc_lines)

            pnt = folder.newpoint(name=name, coords=[(lon, lat)], description=description)
            # Optional: style
            pnt.style.iconstyle.icon.href = 'http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png'

        except (ValueError, TypeError, Exception):
            continue  # Skip invalid rows

    # Save to file
    if output_path:
        save_path = Path(output_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        kml.save(str(save_path))
        return str(save_path)
    else:
        # Use temporary file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".kml")
        tmp.close()  # Close so simplekml can write
        kml.save(tmp.name)
        return tmp.name

def export_to_kmz(df, lat_col, lon_col):
    kml_path = export_to_kml(df, lat_col, lon_col)
    kmz_path = kml_path.replace(".kml", ".kmz")
    with zipfile.ZipFile(kmz_path, "w") as z:
        z.write(kml_path, os.path.basename(kml_path))
    return kmz_path

def export_to_pdf(gdf):
    """Ekspor GeoDataFrame ke GeoPDF menggunakan GDAL."""
    tmp_dir = tempfile.mkdtemp()
    shp_path = os.path.join(tmp_dir, "map.shp")
    gdf.to_file(shp_path)

    pdf_path = os.path.join(tmp_dir, "map.pdf")
    try:
        subprocess.run([
            "gdal_translate", "-of", "PDF",
            shp_path, pdf_path,
            "-co", "GEO_ENCODING=ISO32000"
        ], check=True)
        return pdf_path
    except Exception as e:
        st.error(f"⚠️ Gagal membuat GeoPDF: {e}")
        return None

# ---------- PETA ----------
st.markdown("### 🗺️ Peta Interaktif")
center = [-6.9, 107.6]
tiles_dict = {
    "Google Hybrid": "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    "OpenStreetMap": "OpenStreetMap",
    "ESRI Sat": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "Blank":""
}

m = folium.Map(location=center, zoom_start=10,
               tiles=tiles_dict[basemap_choice], attr=basemap_choice)

data = None
lat_col = lon_col = None

# ---------- LOAD DATA ----------
if uploaded:
    ext = uploaded.name.split('.')[-1].lower()
    try:
        if ext == 'csv':
            from io import StringIO
            uploaded.seek(0)
            text = uploaded.read().decode('utf-8', errors='ignore')
            delimiter = ';' if ';' in text.splitlines()[0] else ','
            df = pd.read_csv(StringIO(text), delimiter=delimiter)
            lat_col, lon_col = detect_lat_lon(df)
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[lon_col], df[lat_col]))

        elif ext == 'xlsx':
            df = pd.read_excel(uploaded)
            lat_col, lon_col = detect_lat_lon(df)
            gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[lon_col], df[lat_col]))

        elif ext in ['geojson', 'kml', 'kmz']:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
            tmp.write(uploaded.getbuffer())
            tmp.close()
            gdf = gpd.read_file(tmp.name)
        data = gdf
        st.success(f"✅ Data berhasil dimuat ({len(gdf)} fitur).")
    except Exception as e:
        st.error(f"Gagal membaca file: {e}")
        data = None

# ---------- TAMPILKAN PETA ----------
if data is not None and not data.empty:
    point_count = line_count = poly_count = 0
    marker_cluster = MarkerCluster().add_to(m)
    bounds = []

    for _, row in data.iterrows():
        geom = row.geometry
        popup_html = "<br>".join(
            [f"<b>{c}:</b> {row[c]}" for c in popup_cols]
        ) if popup_cols else ""

        if geom.geom_type == 'Point':
            lat, lon = geom.y, geom.x
            bounds.append([lat, lon])
            point_count += 1
            folium.Marker(
                location=[lat, lon],
                icon=folium.Icon(color="blue", icon="map-marker", prefix="fa"),
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(marker_cluster)

        elif geom.geom_type == 'LineString':
            coords = [[pt[1], pt[0]] for pt in list(geom.coords)]
            bounds.extend(coords)
            line_count += 1
            folium.PolyLine(
                coords, color="red", weight=3, opacity=0.9, popup=popup_html
            ).add_to(m)

        elif geom.geom_type == 'Polygon':
            coords = [[pt[1], pt[0]] for pt in list(geom.exterior.coords)]
            bounds.extend(coords)
            poly_count += 1
            folium.Polygon(
                coords, color="green", fill=True, fill_opacity=0.4, popup=popup_html
            ).add_to(m)

    if fit_bounds and bounds:
        m.fit_bounds(bounds)

    total = point_count + line_count + poly_count
    st.success(
        f"✅ Data berhasil dimuat ({total} fitur: {point_count} titik, {line_count} garis, {poly_count} poligon)."
    )

else:
    st.warning("Kolom koordinat tidak ditemukan atau file kosong.")

# ---------- RENDER PETA KE STREAMLIT ----------
st_data = st_folium(m, width=1100, height=600)

# ---------- EKSPOR ----------
if data is not None:
    # pastikan kolom lat/lon tersedia untuk ekspor berbasis titik
    lat_for_export = None
    lon_for_export = None

    if 'lat' in data.columns and 'lon' in data.columns:
        lat_for_export, lon_for_export = 'lat', 'lon'
    elif lat_col and lon_col:
        lat_for_export, lon_for_export = lat_col, lon_col

    # --- Export GeoJSON ---
    if exp_geojson:
        try:
            out_dir = tempfile.mkdtemp()
            geojson_path = os.path.join(out_dir, "data.geojson")
            data.to_file(geojson_path, driver="GeoJSON")
            with open(geojson_path, "rb") as f:
                st.download_button("⬇️ Download GeoJSON", f, "data.geojson", "application/geo+json")
        except Exception as e:
            st.error(f"Gagal ekspor GeoJSON: {e}")

    # --- Export CSV ---
    if exp_csv:
        csv = data.drop(columns='geometry', errors='ignore').to_csv(index=False).encode('utf-8')
        st.download_button("⬇️ Download CSV", csv, "data.csv", "text/csv")

    # --- Export KML ---
    if exp_kml and lat_for_export and lon_for_export:
        kml_path = export_to_kml(data, lat_for_export, lon_for_export, description_cols=popup_cols)
        with open(kml_path, "rb") as f:
            st.download_button("⬇️ Download KML", f, "data.kml")

    # --- Export KMZ ---
    if exp_kmz and lat_for_export and lon_for_export:
        kmz_path = export_to_kmz(data, lat_for_export, lon_for_export)
        with open(kmz_path, "rb") as f:
            st.download_button("⬇️ Download KMZ", f, "data.kmz")

    # --- Export SHP ---
    if exp_shp:
        try:
            zip_path = export_to_shp(data)
            with open(zip_path, "rb") as f:
                st.download_button("⬇️ Download SHP (ZIP)", f, "data_shp.zip")
        except Exception as e:
            st.error(f"Gagal ekspor SHP: {e}")

    # --- Export GeoPDF ---
    if exp_pdf:
        try:
            pdf_path = export_to_pdf(data)
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    st.download_button("⬇️ Download GeoPDF", f, "map.pdf")
            else:
                st.warning("GeoPDF gagal dibuat — pastikan GDAL sudah terinstal.")
        except Exception as e:
            st.error(f"Gagal ekspor GeoPDF: {e}")

# ---------- TABEL DENGAN PAGINATION ----------
if data is not None:
    st.markdown("### 📋 Preview Data")
    page_size = 15
    total_pages = math.ceil(len(data) / page_size)
    page = st.number_input("Halaman:", min_value=1, max_value=total_pages, value=1, step=1)
    start = (page - 1) * page_size
    end = start + page_size
    st.dataframe(data.iloc[start:end])

