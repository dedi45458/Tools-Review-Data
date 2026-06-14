import dash
from dash import dcc, html, Input, Output, State, callback, ctx, dash_table, no_update
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import base64
import io
import re
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px
from psycopg2 import extras

# ==========================================================
# IMPORT DARI database.py
# ==========================================================
try:
    from database import (
        dapatkan_koneksi_neon,
        simpan_log_ke_neon_chunked,
        jalankan_agregasi_tren,
        ambil_rekap_tren,
        hitung_dan_ambil_log_db,
        tambah_keyword_medsos,
        ambil_keyword_medsos,
        import_data_rujukan
    )
except ImportError:
    print("⚠️ File database.py tidak ditemukan. Menggunakan Mock Functions.")
    def dapatkan_koneksi_neon(): return None
    def simpan_log_ke_neon_chunked(*args): return True
    def jalankan_agregasi_tren(): return True
    def ambil_rekap_tren(): return pd.DataFrame()
    def hitung_dan_ambil_log_db(): return {}, {}
    def tambah_keyword_medsos(k): return True
    def ambil_keyword_medsos(): return ['Instagram', 'Facebook', 'Twitter']
    def import_data_rujukan(df): return True

# ==========================================================
# GLOBAL STATE
# ==========================================================
server_state = {
    'df_penjangkauan': None,
    'df_referensi': None,
    'df_hasil_validasi': None,
    'df_matriks': None,
    'total_entri': 0,
    'aturan_kustom': [],
    'medsoc_keywords': [],
    'proses_selesai': False,
    'file_uploaded': False,
    'current_menu': 'dashboard'
}

# ==========================================================
# INISIALISASI APP
# ==========================================================
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SLATE], suppress_callback_exceptions=True)
app.title = "Executive Review - PKBI Jabar"

# ==========================================================
# CUSTOM CSS - MODERN SOLID DARK MODE
# ==========================================================
CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

* {
    font-family: 'Inter', sans-serif;
}

body {
    background-color: #0f172a !important;
    color: #e2e8f0 !important;
    margin: 0;
    padding: 0;
}

/* Main Container */
.main-container {
    max-width: 1600px;
    margin: 0 auto;
    padding: 20px;
}

/* Modern Solid Card */
.solid-card {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 20px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    transition: all 0.3s ease;
}

.solid-card:hover {
    border-color: #475569;
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2);
}

/* Metrics Cards */
.metric-card {
    background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
    border: 1px solid #475569;
    border-radius: 16px;
    padding: 1.5rem;
    text-align: center;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
}

.metric-value {
    font-size: 2.5rem;
    font-weight: 700;
    color: #38bdf8 !important;
    margin: 0.5rem 0;
}

.metric-label {
    color: #94a3b8;
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-weight: 600;
}

/* Navigation */
.nav-container {
    background-color: #0f172a;
    border-bottom: 1px solid #1e293b;
    padding: 1rem 2rem;
    position: sticky;
    top: 0;
    z-index: 1000;
    backdrop-filter: blur(10px);
}

.nav-brand {
    font-size: 1.5rem;
    font-weight: 800;
    color: #f8fafc !important;
    text-decoration: none;
}

.nav-link {
    color: #94a3b8 !important;
    text-decoration: none !important;
    padding: 0.5rem 1rem;
    border-radius: 8px;
    transition: all 0.2s;
    font-weight: 500;
    margin: 0 0.5rem;
}

.nav-link:hover {
    color: #f8fafc !important;
    background-color: rgba(56, 189, 248, 0.1);
}

.nav-link.active {
    color: #38bdf8 !important;
    background-color: rgba(56, 189, 248, 0.15);
}

/* Buttons */
.btn-primary-modern {
    background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    padding: 12px 24px !important;
    border-radius: 8px !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 4px 6px rgba(14, 165, 233, 0.2) !important;
}

.btn-primary-modern:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 10px 20px rgba(14, 165, 233, 0.3) !important;
}

.btn-secondary-modern {
    background-color: #334155 !important;
    border: 1px solid #475569 !important;
    color: #e2e8f0 !important;
    font-weight: 600 !important;
    padding: 10px 20px !important;
    border-radius: 8px !important;
    transition: all 0.2s ease !important;
}

.btn-secondary-modern:hover {
    background-color: #475569 !important;
    transform: translateY(-1px) !important;
}

/* Upload Zone */
.upload-zone {
    border: 2px dashed #475569;
    border-radius: 12px;
    padding: 2rem;
    text-align: center;
    cursor: pointer;
    transition: all 0.3s;
    background-color: rgba(30, 41, 59, 0.5);
}

.upload-zone:hover {
    border-color: #38bdf8;
    background-color: rgba(56, 189, 248, 0.05);
}

/* DataTable Styling */
.dash-table-container {
    background: transparent !important;
    border: none !important;
}

.dash-spreadsheet-inner td {
    background-color: #1e293b !important;
    color: #e2e8f0 !important;
    border-bottom: 1px solid #334155 !important;
    font-size: 0.85rem;
    padding: 12px 15px !important;
}

.dash-spreadsheet-inner th {
    background-color: #0f172a !important;
    color: #94a3b8 !important;
    border-bottom: 2px solid #334155 !important;
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.75rem;
    letter-spacing: 0.5px;
}

.dash-spreadsheet tr:hover td {
    background-color: #334155 !important;
}

/* Section Title */
.section-title {
    color: #f8fafc;
    font-weight: 700;
    font-size: 1.5rem;
    margin-bottom: 1.5rem;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid #334155;
}

/* Badge */
.badge-medsos {
    background-color: rgba(56, 189, 248, 0.15);
    color: #38bdf8;
    border: 1px solid rgba(56, 189, 248, 0.3);
    padding: 6px 12px;
    border-radius: 20px;
    font-size: 0.85rem;
    font-weight: 500;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin: 4px;
}

/* Tabs */
.tab-container {
    background-color: #1e293b;
    border-radius: 12px;
    padding: 1rem;
    margin-bottom: 20px;
}

/* Form Controls */
.form-control-modern {
    background-color: #0f172a !important;
    border: 1px solid #334155 !important;
    color: #e2e8f0 !important;
    border-radius: 8px !important;
    padding: 10px 15px !important;
}

.form-control-modern:focus {
    border-color: #38bdf8 !important;
    box-shadow: 0 0 0 0.2rem rgba(56, 189, 248, 0.25) !important;
}

/* Alert */
.alert-modern {
    border-radius: 8px;
    border: none;
    padding: 1rem;
    margin-bottom: 1rem;
}

/* Sidebar */
.sidebar {
    background-color: #0f172a;
    border-right: 1px solid #1e293b;
    min-height: calc(100vh - 70px);
    padding: 2rem 1rem;
}

.sidebar-section {
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid #1e293b;
}

.sidebar-title {
    color: #38bdf8;
    font-weight: 600;
    font-size: 0.95rem;
    margin-bottom: 1rem;
}

/* Loading Spinner */
.loading-spinner {
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 2rem;
}

/* Responsive */
@media (max-width: 768px) {
    .metric-value {
        font-size: 1.8rem;
    }
    .main-container {
        padding: 10px;
    }
}
"""

app.index_string = f'''
<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>Executive Review - PKBI Jabar</title>
        {{%favicon%}}
        {{%css%}}
        <style>{CUSTOM_CSS}</style>
    </head>
    <body>
        {{%app_entry%}}
        <footer> {{%config%}} {{%scripts%}} {{%renderer%}} </footer>
    </body>
</html>
'''

# ==========================================================
# LAYOUT UTAMA
# ==========================================================
app.layout = html.Div([
    # Navigation Bar
    html.Div(className="nav-container", children=[
        html.Div(className="main-container", children=[
            html.Row([
                html.Col(html.A("📊 PKBI Jabar", href="#", className="nav-brand"), width="auto"),
                html.Col(html.Div([
                    html.A("Dashboard", href="#", id="nav-dashboard", className="nav-link active"),
                    html.A("Pengaturan Medsos", href="#", id="nav-medsos", className="nav-link"),
                ], style={'textAlign': 'right'}), width=True)
            ], align="center")
        ])
    ]),

    # Main Content
    html.Div(className="main-container", children=[
        # Content will be updated by callback
        html.Div(id="page-content")
    ]),

    # Store untuk menyimpan state
    dcc.Store(id='store-state', data=server_state),
    dcc.Store(id='store-trigger', data={})
])

# ==========================================================
# FUNGSI HELPER
# ==========================================================
def cek_kode(teks_kolom, kode_target):
    if pd.isna(teks_kolom) or str(teks_kolom).strip().lower() in ['', 'nan']: 
        return False
    clean_str = str(teks_kolom).replace("'", "").replace(" ", "")
    mentah_list = clean_str.split(",")
    list_kode = [kode.split('.')[0] for kode in mentah_list if kode != '']
    return str(kode_target) in list_kode

def buat_fungsi_validasi_kustom(target, kondisi, pembanding):
    if kondisi == "Panjang karakter tidak sama dengan (!=)":
        return lambda c: str(c.get(target, '')).strip() != '' and len(str(c.get(target, ''))) != int(pembanding)
    elif kondisi == "Panjang karakter kurang dari ( < )":
        return lambda c: str(c.get(target, '')).strip() != '' and len(str(c.get(target, ''))) < int(pembanding)
    elif kondisi == "Kosong / Blank":
        return lambda c: str(c.get(target, '')).strip() == '' or pd.isna(c.get(target)) or str(c.get(target)) == 'nan'
    elif kondisi == "Mengandung teks tertentu":
        return lambda c: pembanding.lower() in str(c.get(target, '')).lower()
    elif kondisi == "Sama dengan teks/angka tertentu":
        return lambda c: str(c.get(target, '')).strip().lower() == pembanding.strip().lower()
    return lambda c: False

# ==========================================================
# ATURAN VALIDASI BAWAAN
# ==========================================================
ATURAN_VALIDASI_BAWAAN = [
    {"nama": "Tahun dalam tanggal penjangkauan lebih besar/kecil dari tahun sekarang", "periksa": lambda c: pd.notna(c['tgl_p']) and c['tgl_p'].year != c['tahun_sekarang']},
    {"nama": "Kode Petugas Kosong", "periksa": lambda c: pd.isna(c['row'].get('Kode Petugas')) or str(c['row'].get('Kode Petugas')).strip() in ['', 'nan', 'None']},
    {"nama": "Tanggal lebih besar dari tanggal hari ini", "periksa": lambda c: pd.notna(c['tgl_p']) and c['tgl_p'] > c['hari_ini']},
    {"nama": "IDKD kurang/lebih dari 10 digit karakter", "periksa": lambda c: c['id_clean'] != '' and (len(c['id_clean']) != 10 or not c['id_clean'].isalnum())},
    {"nama": "NIK kurang/lebih dari 16 digit (konfirmasi)", "periksa": lambda c: c['nik_clean'] not in ['', 'nan', 'none', 'NaN', "'"] and len(c['nik_clean']) != 16},
    {"nama": "Kesalahan dalam penulisan NIK (00) (konfirmasi)", "periksa": lambda c: c['nik_clean'] != '' and c['nik_clean'].endswith('00')},
    {"nama": "LSL/Waria tapi jenis kelamin perempuan", "periksa": lambda c: c['v_tipe_sasaran'] in ['1304', '1301'] and c['jk'] == '2'},
    {"nama": "VO tapi menyerahkan jarum", "periksa": lambda c: c['is_vo'] and c['log_jar'] > 0},
    {"nama": "VO menerima logistik selain KIE", "periksa": lambda c: c['is_vo'] and (c['log_kon'] > 0 or c['log_pel'] > 0 or c['log_swab'] > 0)},
    {"nama": "Lokasi outreach indikasi diisi nomer HP", "periksa": lambda c: c['lokasi'] != '' and c['lokasi'] != 'nan' and re.search(r'(08\d{8,11})|(\+62\d{8,11})', str(c['lokasi']).replace('-', '').replace(' ', ''))},
    {"nama": "Penjangkauan tatap muka tapi lokasi outreach diindikasi ada nama medsos", "periksa": lambda c: c['jns_kontak'] in ['1', '2'] and c['pattern_medsos'] and bool(re.search(c['pattern_medsos'], str(c['lokasi']), re.IGNORECASE))},
    {"nama": "KD dikontak lebih dari 1x tapi tidak mendapat informasi HIV", "periksa": lambda c: c['id_clean'] != '' and c['id_counts'].get(c['id_clean'], 0) > 1 and not c['pernah_dapat_info_hiv']},
    {"nama": "Logistik kosong (Konfirmasi)", "periksa": lambda c: c['total_log_keseluruhan_klien'] == 0},
    {"nama": "Popkun selain PWID menerima jarum suntik", "periksa": lambda c: not c['is_pwid'] and c['log_jar'] > 0},
]

# ==========================================================
# ENGINE VALIDASI
# ==========================================================
def jalankan_review_data(df_asli, df_ref=None):
    list_kesalahan = []
    if df_asli.empty: 
        return pd.DataFrame(list_kesalahan)
    
    df = df_asli.copy()
    
    # Pre-processing
    cek_sub_header = False
    if len(df) > 0:
        baris_pertama = str(df.iloc[0].values).upper()
        if any(k in baris_pertama for k in ['KIE', 'KONDOM', 'PELICIN', 'JARUM', 'SWAB']):
            cek_sub_header = True

    if cek_sub_header:
        columns_fixed = []
        main_headers = [str(c).strip() for c in df.columns]
        sub_headers = [str(x).strip() for x in df.iloc[0].values]
        current_main = ""
        for i in range(len(main_headers)):
            if main_headers[i] and 'UNNAMED' not in main_headers[i].upper():
                current_main = main_headers[i]
            sub = sub_headers[i] if (sub_headers[i] and str(sub_headers[i]).lower() != 'nan') else ""
            if current_main and sub and 'UNNAMED' not in sub.upper():
                columns_fixed.append(f"{current_main} - {sub}")
            elif sub and 'UNNAMED' not in sub.upper():
                columns_fixed.append(sub)
            else:
                columns_fixed.append(main_headers[i])
        df.columns = columns_fixed
        df = df.drop(0).reset_index(drop=True)
    else:
        df.columns = [str(c).strip() for c in df.columns]

    # Variables
    tahun_sekarang = datetime.now().year
    hari_ini = pd.Timestamp(datetime.now().date())
    
    keywords_aktif = ambil_keyword_medsos()
    pattern_medsos = r'\b(' + '|'.join([re.escape(k) for k in keywords_aktif]) + r')\b' if keywords_aktif else None
    
    dict_revisi, dict_justifikasi = hitung_dan_ambil_log_db()
    
    # Pre-compute
    df['id_clean'] = df.get('ID Klien', '').astype(str).str.replace("'", "").str.strip()
    df['nik_clean'] = df.get('NIK', '').astype(str).str.replace("'", "").str.replace('.0', '').str.strip()
    df['v_ssr'] = df.get('Lembaga SSR', '').astype(str).str.strip().str.upper()
    df['v_petugas'] = df.get('Kode Petugas', '').astype(str).str.replace("'", "").str.strip()
    df['v_kota'] = df.get('Nama Kota', '').astype(str).str.strip()
    df['v_tanggal'] = df.get('Tanggal', '').astype(str).str.split(' ').str[0]
    df['v_tipe_sasaran'] = df.get('Tipe Sasaran', df.get('Tipe Klien', '')).astype(str).str.replace('.0', '').str.strip()
    df['jk'] = df.get('Jenis Kelamin', '').astype(str).str.replace('.0', '').str.strip()
    df['jns_kontak'] = df.get('Jenis Kontak', '').astype(str).str.replace('.0', '').str.strip()
    df['jns_kegiatan'] = df.get('Jenis Kegiatan', '').astype(str).str.strip()
    df['lokasi'] = df.get('Lokasi Outreach / Jenis Sosial Media', '').astype(str).str.strip()
    df['no_hp'] = df.get('No. HP / Nama Akun', '').astype(str).str.strip()
    df['vc1'] = df.get('Virtual & Tatap Muka', '').astype(str).str.replace('.0', '').str.strip()
    
    df['ssr_id_key'] = df['v_ssr'] + "_" + df['id_clean']
    df['tgl_p'] = pd.to_datetime(df.get('Tanggal', ''), errors='coerce', format='%d/%m/%Y')
    
    is_file_rujukan = any('RUJUKAN' in str(c).upper() for c in df.columns)
    
    # Aggregations
    id_counts = df['ssr_id_key'].value_counts().to_dict()
    
    col_info = next((c for c in df.columns if "INFORMASI" in str(c).upper() and "DIBERIKAN" in str(c).upper()), "")
    col_kegiatan = next((c for c in df.columns if "JENIS KEGIATAN" in str(c).upper()), "")
    col_ruj = next((c for c in df.columns if "RUJUKAN" in str(c).upper()), "")
    
    def safe_sum(cols):
        return df[cols].apply(pd.to_numeric, errors='coerce').sum(axis=1, skipna=True).fillna(0)
    
    col_kie = [c for c in df.columns if 'KIE' in str(c).upper()]
    col_kon = [c for c in df.columns if 'KONDOM' in str(c).upper()]
    col_pel = [c for c in df.columns if 'PELICIN' in str(c).upper()]
    col_jar = [c for c in df.columns if 'JARUM' in str(c).upper() and 'KEMBALI' not in str(c).upper()]
    col_swab = [c for c in df.columns if 'SWAB' in str(c).upper() or 'ALKOHOL' in str(c).upper()]
    
    df['log_kie'] = safe_sum(col_kie)
    df['log_kon'] = safe_sum(col_kon)
    df['log_pel'] = safe_sum(col_pel)
    df['log_jar'] = safe_sum(col_jar)
    df['log_swab'] = safe_sum(col_swab)
    
    total_log_cols = ['log_kie', 'log_kon', 'log_pel', 'log_jar', 'log_swab']
    total_log_map = df.groupby('ssr_id_key')[total_log_cols].sum().sum(axis=1).to_dict()
    df['total_log_keseluruhan_klien'] = df['ssr_id_key'].map(total_log_map).fillna(0)
    
    df['is_vo'] = (df['jns_kontak'] == '3')
    df['is_pwid'] = df['v_tipe_sasaran'].isin(['1401', '1403'])
    
    if col_info and col_kegiatan:
        df['is_info_hiv'] = df[col_info].astype(str).str.contains(r'\b1\b', regex=True, na=False) | df[col_kegiatan].astype(str).str.contains(r'\b1\b', regex=True, na=False)
    else:
        df['is_info_hiv'] = False
        
    if col_ruj:
        df['is_rujuk_tes'] = df[col_ruj].astype(str).str.replace('.', ',', regex=False).str.contains(r'\b2\b', regex=True, na=False)
    else:
        df['is_rujuk_tes'] = False

    pernah_hiv_map = df.groupby('ssr_id_key')['is_info_hiv'].any().to_dict()
    pernah_rujuk_map = df.groupby('ssr_id_key')['is_rujuk_tes'].any().to_dict()
    df['pernah_dapat_info_hiv'] = df['ssr_id_key'].map(pernah_hiv_map).fillna(False)
    df['pernah_dapat_rujuk_tes'] = df['ssr_id_key'].map(pernah_rujuk_map).fillna(False)

    # Validasi
    def add_error(rule_name, mask):
        if mask.any():
            err_df = df[mask].copy()
            err_df['INDIKATOR KESALAHAN DATA'] = rule_name
            
            is_konfirmasi = "konfirmasi" in rule_name.lower()
            if is_konfirmasi:
                err_df['key_db'] = err_df['v_ssr'] + "_" + err_df['v_tanggal'] + "_" + err_df['id_clean'] + "_" + rule_name
                valid_to_show = []
                for idx, row in err_df.iterrows():
                    if row['key_db'] in dict_justifikasi and not dict_revisi.get(row['key_db'], False):
                        continue
                    valid_to_show.append(idx)
                err_df = err_df.loc[valid_to_show].copy()
                
                err_df['validasi hasil review'] = err_df['key_db'].map(lambda k: "kesalahan pada ID yang berulang (belum dilakukan revisi)" if k in dict_revisi else "-")
                err_df['Justifikasi'] = err_df['key_db'].map(lambda k: dict_justifikasi.get(k, ""))
                err_df = err_df.drop(columns=['key_db'])
            else:
                err_df['validasi hasil review'] = "-"
                err_df['Justifikasi'] = ""
                
            err_df['Pilih'] = False
            list_kesalahan.append(err_df[['Pilih', 'Lembaga SSR', 'Tanggal', 'ID Klien', 'Kode Petugas', 'Nama Kota', 'NIK', 'Tipe Sasaran', 'INDIKATOR KESALAHAN DATA', 'validasi hasil review', 'Justifikasi']])

    # Jalankan aturan
    add_error("Tahun dalam tanggal penjangkauan lebih besar/kecil dari tahun sekarang", df['tgl_p'].dt.year != tahun_sekarang)
    add_error("Kode Petugas Kosong", df['v_petugas'].isin(['', 'nan', 'None']) | df['v_petugas'].isna())
    add_error("Tanggal lebih besar dari tanggal hari ini", df['tgl_p'] > hari_ini)
    add_error("IDKD kurang/lebih dari 10 digit karakter", (df['id_clean'] != '') & (df['id_clean'].str.len() != 10))
    add_error("NIK kurang/lebih dari 16 digit (konfirmasi)", (df['nik_clean'] != '') & (df['nik_clean'].str.len() != 16))
    add_error("Kesalahan dalam penulisan NIK (00) (konfirmasi)", (df['nik_clean'] != '') & (df['nik_clean'].str.endswith('00')))
    add_error("LSL/Waria tapi jenis kelamin perempuan", df['v_tipe_sasaran'].isin(['1304', '1301']) & (df['jk'] == '2'))
    add_error("VO tapi menyerahkan jarum", df['is_vo'] & (df['log_jar'] > 0))
    add_error("VO menerima logistik selain KIE", df['is_vo'] & ((df['log_kon'] > 0) | (df['log_pel'] > 0) | (df['log_swab'] > 0)))
    add_error("Lokasi outreach indikasi diisi nomer HP", df['lokasi'].str.contains(r'(08\d{8,11})|(\+62\d{8,11})', regex=True, na=False))
    if pattern_medsos:
        add_error("Penjangkauan tatap muka tapi lokasi outreach diindikasi ada nama medsos", (df['jns_kontak'].isin(['1', '2'])) & (df['lokasi'].str.contains(pattern_medsos, case=False, regex=True, na=False)))
    add_error("KD dikontak lebih dari 1x tapi tidak mendapat informasi HIV", (df['ssr_id_key'].map(id_counts) > 1) & (~df['pernah_dapat_info_hiv']))
    add_error("Logistik kosong (Konfirmasi)", df['total_log_keseluruhan_klien'] == 0)
    add_error("Popkun selain PWID menerima jarum suntik", (~df['is_pwid']) & (df['log_jar'] > 0))

    if list_kesalahan:
        return pd.concat(list_kesalahan, ignore_index=True)
    return pd.DataFrame(columns=['Pilih', 'Lembaga SSR', 'Tanggal', 'ID Klien', 'Kode Petugas', 'Nama Kota', 'NIK', 'Tipe Sasaran', 'INDIKATOR KESALAHAN DATA', 'validasi hasil review', 'Justifikasi'])

# ==========================================================
# LAYOUT PAGES
# ==========================================================
def create_dashboard_layout():
    return html.Div([
        # Upload Section
        html.Div(className="solid-card", children=[
            html.Row([
                html.Col([
                    html.Div(className="upload-zone", children=[
                        html.I(className="bi bi-cloud-upload", style={'fontSize': '2rem', 'color': '#38bdf8', 'marginBottom': '10px', 'display': 'block'}),
                        html.Div("Upload File Penjangkauan & Rujukan", style={'fontWeight': '600', 'color': '#f8fafc', 'fontSize': '1.1rem'}),
                        html.Div("Drag & drop atau klik untuk memilih file (.xlsx, .csv)", style={'fontSize': '0.85rem', 'color': '#94a3b8', 'marginTop': '5px'})
                    ]),
                    dcc.Upload(id='upload-penjangkauan', children=html.Div(), style={'display': 'none'}),
                    html.Div(id="status-upload", style={'marginTop': '10px', 'fontSize': '0.85rem', 'color': '#38bdf8'})
                ], width=8),
                html.Col([
                    html.Div([
                        html.Label("Pilih Aturan Validasi", style={'color': '#94a3b8', 'fontSize': '0.85rem', 'marginBottom': '5px'}),
                        dbc.Select(id="select-aturan", options=[{"label": "Aturan Validasi Bawaan", "value": "default"}], className="mb-3", style={'backgroundColor': '#0f172a', 'color': '#e2e8f0', 'borderColor': '#334155'}),
                        dbc.Button("🚀 Jalankan Validasi", id="btn-jalankan", className="btn-primary-modern w-100 py-3 mt-2", size="lg")
                    ], style={'padding': '1rem'})
                ], width=4)
            ])
        ]),

        # Metrics
        html.Div(id='metrics-section', children=[
            html.Row([
                html.Col(html.Div(className="metric-card", children=[
                    html.Div("Total Data Diproses", className="metric-label"),
                    html.H2(id="metric-total-data", className="metric-value", children="0"),
                ]), width=4),
                html.Col(html.Div(className="metric-card", children=[
                    html.Div("Temuan Error", className="metric-label"),
                    html.H2(id="metric-temuan", className="metric-value", style={'color': '#fb7185 !important'}, children="0"),
                ]), width=4),
                html.Col(html.Div(className="metric-card", children=[
                    html.Div("Tingkat Akurasi", className="metric-label"),
                    html.H2(id="metric-akurasi", className="metric-value", style={'color': '#34d399 !important'}, children="0%"),
                ]), width=4),
            ])
        ], style={'display': 'none'}),

        # Results Section
        html.Div(id='results-section', children=[
            html.Div([
                html.H4("📋 Rekap Kesalahan (Matriks)", className="section-title"),
                html.Div(id='matriks-container')
            ], className="solid-card"),
            
            html.Div([
                html.H4("🔍 Hasil Review Detail", className="section-title"),
                dcc.Loading(id="loading-table", type="circle", color="#38bdf8", children=[
                    html.Div(id='table-container')
                ]),
                html.Div([
                    dbc.Button("💾 Simpan Progres ke Database", id="btn-simpan", className="btn-secondary-modern w-100 mt-3"),
                    html.Div(id="status-simpan", className="mt-3 text-center", style={'color': '#e2e8f0'})
                ])
            ], className="solid-card", style={'marginTop': '20px'})
        ], style={'display': 'none'})
    ])

def create_medsos_layout():
    list_medsos = ambil_keyword_medsos()
    badges_html = [html.Span(f"🔹 {m}", className="badge-medsos") for m in list_medsos]
    
    return html.Div([
        html.Div(className="solid-card", children=[
            html.H3("⚙️ Pengaturan Keyword Media Sosial", className="section-title"),
            html.P("Gunakan menu ini untuk menambahkan atau melihat daftar nama media sosial yang digunakan sebagai filter pada pencarian Lokasi Outreach.", style={'color': '#94a3b8', 'marginBottom': '2rem'}),
            
            html.Row([
                html.Col([
                    html.Div([
                        html.H5("➕ Tambah Medsos Baru", style={'color': '#f8fafc', 'marginBottom': '1rem'}),
                        dbc.Input(id="input-medsos-baru", placeholder="Contoh: Instagram, Facebook, TikTok", type="text", className="form-control-modern mb-3"),
                        dbc.Button("Simpan Keyword", id="btn-tambah-medsos", className="btn-primary-modern w-100")
                    ], style={'padding': '1.5rem', 'backgroundColor': '#0f172a', 'borderRadius': '8px'})
                ], width=4),
                html.Col([
                    html.Div([
                        html.H5(f"📋 Daftar Keyword Aktif ({len(list_medsos)})", style={'color': '#f8fafc', 'marginBottom': '1rem'}),
                        html.Div(badges_html, id='medsos-badges-container', style={'padding': '1rem', 'backgroundColor': 'rgba(0,0,0,0.2)', 'borderRadius': '8px', 'minHeight': '100px'})
                    ], style={'padding': '1.5rem'})
                ], width=8)
            ])
        ])
    ])

# ==========================================================
# CALLBACKS
# ==========================================================
@callback(
    [Output('page-content', 'children'),
     Output('nav-dashboard', 'className'),
     Output('nav-medsos', 'className')],
    [Input('nav-dashboard', 'n_clicks'), Input('nav-medsos', 'n_clicks')]
)
def navigate(n_dash, n_medsos):
    triggered_id = ctx.triggered_id
    
    if triggered_id == 'nav-medsos':
        return create_medsos_layout(), 'nav-link', 'nav-link active'
    else:
        return create_dashboard_layout(), 'nav-link active', 'nav-link'

@callback(
    [Output('status-upload', 'children'),
     Output('store-state', 'data', allow_duplicate=True)],
    Input('upload-penjangkauan', 'contents'),
    State('upload-penjangkauan', 'filename'),
    State('store-state', 'data'),
    prevent_initial_call=True
)
def handle_upload(contents, filename, state):
    if contents is None:
        return no_update, no_update
    
    try:
        content_type, content_string = contents.split(',')
        decoded = base64.b64decode(content_string)
        
        if 'csv' in filename:
            df = pd.read_csv(io.StringIO(decoded.decode('utf-8')), low_memory=False)
        else:
            df = pd.read_excel(io.BytesIO(decoded))
        
        state['df_penjangkauan'] = df
        state['file_uploaded'] = True
        
        return html.Div([
            html.I(className="bi bi-check-circle", style={'color': '#34d399', 'marginRight': '5px'}),
            f"✅ {filename} berhasil dimuat ({len(df):,} baris)"
        ]), state
    except Exception as e:
        return html.Div([
            html.I(className="bi bi-x-circle", style={'color': '#fb7185', 'marginRight': '5px'}),
            f"❌ Error: {str(e)}"
        ]), no_update

@callback(
    [Output('metrics-section', 'style'),
     Output('results-section', 'style'),
     Output('metric-total-data', 'children'),
     Output('metric-temuan', 'children'),
     Output('metric-akurasi', 'children'),
     Output('matriks-container', 'children'),
     Output('table-container', 'children'),
     Output('store-state', 'data', allow_duplicate=True)],
    Input('btn-jalankan', 'n_clicks'),
    State('store-state', 'data'),
    prevent_initial_call=True
)
def run_validation(n_clicks, state):
    if not state.get('file_uploaded') or state.get('df_penjangkauan') is None:
        return {'display': 'none'}, {'display': 'none'}, "0", "0", "0%", "", "", no_update
    
    with dcc.Loading(id="loading", type="circle"):
        df_raw = state['df_penjangkauan']
        df_errors = jalankan_review_data(df_raw)
        state['df_hasil_validasi'] = df_errors
        state['proses_selesai'] = True
        
        tot_data = len(df_raw)
        tot_err = len(df_errors)
        akurasi = max(0, 100 - (tot_err / tot_data * 100)) if tot_data > 0 else 100.0
        
        # Create matriks
        if not df_errors.empty:
            matriks_html = html.Div([
                dash_table.DataTable(
                    data=df_errors.groupby(['INDIKATOR KESALAHAN DATA', 'Lembaga SSR']).size().reset_index(name='Jumlah').pivot(index='INDIKATOR KESALAHAN DATA', columns='Lembaga SSR', values='Jumlah').fillna(0).reset_index(),
                    page_size=10,
                    style_table={'overflowX': 'auto'},
                    style_cell={'textAlign': 'center', 'padding': '10px'},
                    style_header={'backgroundColor': '#0f172a', 'fontWeight': 'bold', 'color': '#94a3b8'}
                )
            ])
        else:
            matriks_html = html.Div("✨ Tidak ada kesalahan ditemukan. Data bersih!", style={'color': '#34d399', 'padding': '1rem', 'textAlign': 'center'})
        
        # Create table
        if not df_errors.empty:
            table_html = html.Div([
                dash_table.DataTable(
                    id='tabel-detail',
                    data=df_errors.to_dict('records'),
                    columns=[{"name": i, "id": i, "editable": (i in ['Pilih', 'Justifikasi'])} for i in df_errors.columns],
                    editable=True,
                    page_size=20,
                    style_table={'overflowX': 'auto', 'borderRadius': '12px'},
                    row_deletable=False,
                    filter_action="native",
                    sort_action="native",
                )
            ])
        else:
            table_html = html.Div("Tidak ada data error untuk ditampilkan.", style={'color': '#94a3b8', 'padding': '1rem', 'textAlign': 'center'})
        
        return {'display': 'block'}, {'display': 'block'}, f"{tot_data:,}", f"{tot_err:,}", f"{akurasi:.1f}%", matriks_html, table_html, state

@callback(
    Output('status-simpan', 'children'),
    Input('btn-simpan', 'n_clicks'),
    State('tabel-detail', 'data'),
    State('store-state', 'data'),
    prevent_initial_call=True
)
def save_to_database(n_clicks, table_data, state):
    if not table_data:
        return "ℹ️ Tidak ada data untuk disimpan."
    
    list_log = []
    for row in table_data:
        if bool(row.get('Pilih', False)) or ("konfirmasi" in str(row.get('INDIKATOR KESALAHAN DATA', '')).lower() and str(row.get('Justifikasi', '')).strip() != ""):
            list_log.append((
                str(row.get('Lembaga SSR', '')),
                str(row.get('Tanggal', '')),
                str(row.get('ID Klien', '')),
                str(row.get('INDIKATOR KESALAHAN DATA', '')),
                bool(row.get('Pilih', False)),
                str(row.get('Justifikasi', '')).strip()
            ))
    
    if list_log:
        if simpan_log_ke_neon_chunked(list_log):
            return f"🎉 Berhasil menyimpan {len(list_log)} baris ke database!"
        return "❌ Gagal menyimpan ke database."
    return "ℹ️ Centang 'Pilih' atau isi 'Justifikasi' untuk menyimpan."

@callback(
    [Output('medsos-badges-container', 'children'),
     Output('input-medsos-baru', 'value')],
    Input('btn-tambah-medsos', 'n_clicks'),
    State('input-medsos-baru', 'value'),
    prevent_initial_call=True
)
def tambah_medsos(n_clicks, medsos_baru):
    if not medsos_baru:
        return no_update, no_update
    
    sukses = tambah_keyword_medsos(medsos_baru)
    list_medsos = ambil_keyword_medsos()
    badges_html = [html.Span(f"🔹 {m}", className="badge-medsos") for m in list_medsos]
    
    if sukses:
        return badges_html, ""
    return badges_html, medsos_baru

# ==========================================================
# RUN APP
# ==========================================================
if __name__ == '__main__':
    app.run(debug=True, port=8050)
