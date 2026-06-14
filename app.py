import dash
from dash import dcc, html, Input, Output, State, callback, ctx, no_update, dash_table
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import base64
import io
import re
from datetime import datetime
import plotly.graph_objects as go
from psycopg2 import extras

# ==========================================================
# IMPORT DARI database.py (Pastikan file ini ada di folder yang sama)
# ==========================================================
try:
    from database import (
        dapatkan_koneksi_neon,
        hitung_dan_ambil_log_db,
        ambil_rekap_tren,
        jalankan_agregasi_tren,
        tambah_keyword_medsos,
        ambil_keyword_medsos,
        import_data_rujukan
    )
except ImportError:
    print("⚠️ File database.py tidak ditemukan. Menggunakan Mock Functions.")
    def dapatkan_koneksi_neon(): return None
    def hitung_dan_ambil_log_db(): return {}, {}
    def ambil_rekap_tren(): return pd.DataFrame()
    def jalankan_agregasi_tren(): return True
    def tambah_keyword_medsos(k): return True
    def ambil_keyword_medsos(): return []
    def import_data_rujukan(df): return True

# ==========================================================
# GLOBAL STATE SERVER
# ==========================================================
server_state = {
    'df_penjangkauan': None,
    'df_referensi': None,
    'df_hasil_validasi': None,
    'total_entri': 0,
    'aturan_kustom': [],
    'medsoc_keywords': [],
    'riwayat_validasi': [] 
}

class MockST:
    session_state = {'aturan_kustom': [], 'medsoc_keywords': []}
st = MockST()

# ==========================================================
# FUNGSI OPTIMASI VEKTORISASI (TIDAK BERUBAH)
# ==========================================================
def jalankan_review_data_optimized(df_asli, df_ref=None, nama_file=""):
    if df_asli.empty: 
        return pd.DataFrame()
    
    df = df_asli.copy()
    
    # 1. PRE-PROCESSING VEKTORISASI
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
            if main_headers[i] and 'UNNAMED' not in main_headers[i].upper(): current_main = main_headers[i]
            sub = sub_headers[i] if (sub_headers[i] and str(sub_headers[i]).lower() != 'nan') else ""
            if current_main and sub and 'UNNAMED' not in sub.upper(): columns_fixed.append(f"{current_main} - {sub}")
            elif sub and 'UNNAMED' not in sub.upper(): columns_fixed.append(sub)
            else: columns_fixed.append(main_headers[i])
        df.columns = columns_fixed
        df = df.drop(0).reset_index(drop=True)
        start_row_idx = 0 
    else:
        df.columns = [str(c).strip() for c in df.columns]
        start_row_idx = 0
        if len(df) > 0 and ('dd/mm/yyyy' in str(df.iloc[0].values).lower() or 'laki-laki' in str(df.iloc[0].values).lower()):
            start_row_idx = 1

    # Bersihkan data sekali saja
    df['id_clean'] = df.get('ID Klien', '').astype(str).str.replace("'", "", regex=False).str.strip()
    df['nik_clean'] = df.get('NIK', '').astype(str).str.replace("'", "", regex=False).str.replace('.0', '', regex=False).str.strip()
    df['v_ssr'] = df.get('Lembaga SSR', '').astype(str).str.strip().str.upper()
    df['v_petugas'] = df.get('Kode Petugas', '').astype(str).str.replace("'", "", regex=False).str.strip()
    df['v_kota'] = df.get('Nama Kota', '').astype(str).str.strip()
    df['v_tanggal'] = df.get('Tanggal', '').astype(str).str.split(' ').str[0]
    df['v_tipe_sasaran'] = df.get('Tipe Sasaran', df.get('Tipe Klien', '')).astype(str).str.replace('.0', '', regex=False).str.strip()
    df['jk'] = df.get('Jenis Kelamin', '').astype(str).str.replace('.0', '', regex=False).str.strip()
    df['jns_kontak'] = df.get('Jenis Kontak', '').astype(str).str.replace('.0', '', regex=False).str.strip()
    df['jns_kegiatan'] = df.get('Jenis Kegiatan', '').astype(str).str.strip()
    df['lokasi'] = df.get('Lokasi Outreach / Jenis Sosial Media', '').astype(str).str.strip()
    df['no_hp'] = df.get('No. HP / Nama Akun', '').astype(str).str.strip()
    df['vc1'] = df.get('Virtual & Tatap Muka', '').astype(str).str.replace('.0', '', regex=False).str.strip()
    
    df['ssr_id_key'] = df['v_ssr'] + "_" + df['id_clean']
    df['tgl_p'] = pd.to_datetime(df.get('Tanggal', ''), errors='coerce', format='%d/%m/%Y')
    
    is_file_rujukan = any('RUJUKAN' in str(c).upper() or 'FASYANKES' in str(c).upper() for c in df.columns)
    tahun_sekarang = datetime.now().year
    hari_ini = pd.Timestamp(datetime.now().date())

    # 2. PREPARE LOOKUP TABLES
    dict_revisi, dict_justifikasi = {}, {}
    try:
        dict_revisi, dict_justifikasi = hitung_dan_ambil_log_db()
    except: pass

    ref_ssr_id_to_nik, ref_nik_ssr_to_id = {}, {}
    
    if is_file_rujukan and df_ref is not None and not df_ref.empty:
        df_ref_cp = df_ref.copy()
        df_ref_cp.columns = [str(c).strip() for c in df_ref_cp.columns]
        col_id_ref = next((c for c in df_ref_cp.columns if 'ID' in c or 'Klien' in c), None)
        col_nik_ref = next((c for c in df_ref_cp.columns if 'NIK' in c), None)
        col_ssr_ref = next((c for c in df_ref_cp.columns if 'SSR' in c or 'Lembaga' in c), None)
        
        if col_id_ref and col_ssr_ref:
            df_ref_cp['ssr_clean'] = df_ref_cp[col_ssr_ref].astype(str).str.strip().str.upper()
            df_ref_cp['id_clean_ref'] = df_ref_cp[col_id_ref].astype(str).str.replace("'", "", regex=False).str.strip()
            df_ref_cp['nik_clean_ref'] = df_ref_cp[col_nik_ref].astype(str).str.replace("'", "", regex=False).str.replace('.0', '', regex=False).str.strip() if col_nik_ref else ''
            df_ref_cp['key_klien'] = df_ref_cp['ssr_clean'] + "_" + df_ref_cp['id_clean_ref']
            
            valid_ref = (df_ref_cp['id_clean_ref'] != 'nan') & (df_ref_cp['ssr_clean'] != 'nan')
            ref_ssr_id_to_nik = dict(zip(df_ref_cp.loc[valid_ref, 'key_klien'], df_ref_cp.loc[valid_ref, 'nik_clean_ref']))
            
            valid_nik = (df_ref_cp['nik_clean_ref'] != 'nan') & (df_ref_cp['nik_clean_ref'] != '') & (df_ref_cp['ssr_clean'] != 'nan')
            ref_nik_ssr_to_id = dict(zip(df_ref_cp.loc[valid_nik, 'nik_clean_ref'] + "_" + df_ref_cp.loc[valid_nik, 'ssr_clean'], df_ref_cp.loc[valid_nik, 'id_clean_ref']))

    df['ref_nik'] = df['ssr_id_key'].map(ref_ssr_id_to_nik)
    df['ref_id'] = (df['nik_clean'] + "_" + df['v_ssr']).map(ref_nik_ssr_to_id)

    # 3. PRE-COMPUTE AGGREGATIONS & FLAGS
    df['is_vo'] = (df['jns_kontak'] == '3')
    df['is_pwid'] = df['v_tipe_sasaran'].isin(['1401', '1403'])
    
    id_counts = df['ssr_id_key'].value_counts().to_dict()
    df['id_counts'] = df['ssr_id_key'].map(id_counts)

    col_info = next((c for c in df.columns if "INFORMASI" in str(c).upper() and "DIBERIKAN" in str(c).upper()), "")
    col_kegiatan = next((c for c in df.columns if "JENIS KEGIATAN" in str(c).upper()), "")
    col_ruj = next((c for c in df.columns if "RUJUKAN" in str(c).upper()), "")

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

    col_kie = [c for c in df.columns if 'KIE' in str(c).upper()]
    col_kon = [c for c in df.columns if 'KONDOM' in str(c).upper()]
    col_pel = [c for c in df.columns if 'PELICIN' in str(c).upper()]
    col_jar = [c for c in df.columns if 'JARUM' in str(c).upper() and 'KEMBALI' not in str(c).upper()]
    col_swab = [c for c in df.columns if 'SWAB' in str(c).upper() or 'ALKOHOL' in str(c).upper()]
    
    def safe_sum(cols):
        return df[cols].apply(pd.to_numeric, errors='coerce').sum(axis=1, skipna=True).fillna(0)

    df['log_kie'] = safe_sum(col_kie)
    df['log_kon'] = safe_sum(col_kon)
    df['log_pel'] = safe_sum(col_pel)
    df['log_jar'] = safe_sum(col_jar)
    df['log_swab'] = safe_sum(col_swab)
    df['jarum_kembali'] = pd.to_numeric(df.get('Jumlah Jarum Suntik Kembali', 0), errors='coerce').fillna(0)
    
    total_log_cols = ['log_kie', 'log_kon', 'log_pel', 'log_jar', 'log_swab']
    total_log_map = df.groupby('ssr_id_key')[total_log_cols].sum().sum(axis=1).to_dict()
    df['total_log_keseluruhan_klien'] = df['ssr_id_key'].map(total_log_map).fillna(0)

    # 4. EVALUASI ATURAN (VEKTORISASI)
    list_error_dfs = []
    keywords_aktif = st.session_state.get('medsoc_keywords', [])
    pattern_medsos = r'\b(' + '|'.join([re.escape(k) for k in keywords_aktif]) + r')\b' if keywords_aktif else r'\b(TIDAK_ADA_MEDSOS)\b'

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
            list_error_dfs.append(err_df)

    # Aturan Bawaan
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
    add_error("Penjangkauan tatap muka tapi lokasi outreach diindikasi ada nama medsos", (df['jns_kontak'].isin(['1', '2'])) & (df['lokasi'].str.contains(pattern_medsos, case=False, regex=True, na=False)))
    add_error("KD dikontak lebih dari 1x tapi tidak mendapat informasi HIV", (df['id_counts'] > 1) & (~df['pernah_dapat_info_hiv']))
    add_error("Logistik kosong (Konfirmasi)", df['total_log_keseluruhan_klien'] == 0)
    add_error("Popkun selain PWID menerima jarum suntik", (~df['is_pwid']) & (df['log_jar'] > 0))

    # 5. ATURAN KUSTOM
    aturan_kustom = st.session_state.get('aturan_kustom', [])
    if aturan_kustom:
        for idx, row in df.iterrows():
            context_data = {
                'row': row, 'id_clean': row['id_clean'], 'nik_clean': row['nik_clean'], 
                'v_ssr': row['v_ssr'], 'v_tanggal': row['v_tanggal'], 'v_petugas': row['v_petugas'],
                'v_kota': row['v_kota'], 'v_tipe_sasaran': row['v_tipe_sasaran'], 'umur': row.get('Umur'),
                'jk': row['jk'], 'jns_kontak': row['jns_kontak'], 'jns_kegiatan': row['jns_kegiatan'],
                'lokasi': row['lokasi'], 'info_diberikan': row.get(col_info, ''), 'rujukan': row.get(col_ruj, ''),
                'no_hp': row['no_hp'], 'vc1': row['vc1'], 'log_kie': row['log_kie'], 'log_kon': row['log_kon'],
                'log_pel': row['log_pel'], 'log_jar': row['log_jar'], 'log_swab': row['log_swab'],
                'jarum_kembali': row['jarum_kembali'], 'tgl_p': row['tgl_p'], 'hari_ini': hari_ini,
                'tahun_sekarang': tahun_sekarang, 'is_vo': row['is_vo'], 'is_pwid': row['is_pwid'],
                'id_counts': {row['id_clean']: row['id_counts']}, 'pernah_dapat_info_hiv': row['pernah_dapat_info_hiv'],
                'pernah_dapat_rujuk_tes': row['pernah_dapat_rujuk_tes'], 'is_file_rujukan': is_file_rujukan,
                'df_ref': df_ref, 'ref_ssr_id_to_nik': ref_ssr_id_to_nik, 'ref_nik_ssr_to_id': ref_nik_ssr_to_id,
                'total_log_keseluruhan_klien': row['total_log_keseluruhan_klien'], 'pattern_medsos': pattern_medsos
            }
            for rule in aturan_kustom:
                try:
                    if rule["periksa"](context_data):
                        err_row = row.to_dict()
                        err_row['INDIKATOR KESALAHAN DATA'] = rule["nama"]
                        err_row['validasi hasil review'] = "-"
                        err_row['Justifikasi'] = ""
                        err_row['Pilih'] = False
                        list_error_dfs.append(pd.DataFrame([err_row]))
                except: pass

    # 6. GABUNGKAN HASIL
    if not list_error_dfs: return pd.DataFrame()
    final_df = pd.concat(list_error_dfs, ignore_index=True)
    required_cols = ["Pilih", "Lembaga SSR", "Tanggal", "ID Klien", "Kode Petugas", "Nama Kota", "NIK", "Tipe Sasaran", "INDIKATOR KESALAHAN DATA", "validasi hasil review", "Justifikasi"]
    for col in required_cols:
        if col not in final_df.columns:
            final_df[col] = "" if col in ["Justifikasi", "validasi hasil review"] else False
    return final_df[required_cols]

# ==========================================================
# FUNGSI CHUNKING DATABASE NEON
# ==========================================================
def simpan_log_ke_neon_chunked(list_log_db, chunk_size=5000):
    if not list_log_db: return True
    conn = dapatkan_koneksi_neon()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            for i in range(0, len(list_log_db), chunk_size):
                chunk = list_log_db[i : i + chunk_size]
                extras.execute_batch(
                    cur, 
                    """
                    INSERT INTO log_validasi_review 
                    (Lembaga_SSR, Tanggal, ID_Klien, Indikator_Kesalahan_Data, is_revisi, Justifikasi, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (Lembaga_SSR, Tanggal, ID_Klien, Indikator_Kesalahan_Data) 
                    DO UPDATE SET 
                        is_revisi = EXCLUDED.is_revisi, 
                        Justifikasi = EXCLUDED.Justifikasi,
                        updated_at = NOW()
                    """,
                    [tuple(row) for row in chunk],
                    page_size=1000
                )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error DB: {e}")
        return False
    finally:
        conn.close()

# ==========================================================
# INISIALISASI APP & TEMA MODERN SOLID DARK
# ==========================================================
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SLATE])

# CSS Custom untuk Modern Solid Dark
CUSTOM_CSS = """
    body { 
        background-color: #0f172a !important; /* Slate 900 - Solid Dark */
        font-family: 'Inter', system-ui, -apple-system, sans-serif; 
        color: #e2e8f0; /* Slate 200 */
        margin: 0;
        min-height: 100vh;
    }
    
    /* Modern Solid Card Style */
    .solid-card {
        background-color: #1e293b; /* Slate 800 */
        border: 1px solid #334155; /* Slate 700 Border */
        border-radius: 12px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        margin-bottom: 20px;
        transition: border-color 0.2s ease;
    }
    .solid-card:hover { 
        border-color: #475569; /* Slightly lighter on hover */
    }
    
    /* Typography & Metrics */
    .metric-value { 
        color: #f8fafc !important; 
        font-weight: 700; 
        font-size: 2.2rem; 
        margin: 0; 
        line-height: 1.2; 
    }
    .metric-label { 
        color: #94a3b8; /* Slate 400 */
        font-size: 0.85rem; 
        margin-top: 8px; 
        text-transform: uppercase; 
        letter-spacing: 0.5px; 
        font-weight: 600;
    }
    
    /* Accent Colors for Metrics */
    .text-accent-blue { color: #38bdf8 !important; } /* Sky 400 */
    .text-accent-red { color: #fb7185 !important; } /* Rose 400 - Softer than pure red */
    .text-accent-green { color: #34d399 !important; } /* Emerald 400 */

    /* Buttons */
    .btn-modern-primary { 
        background-color: #0ea5e9 !important; /* Sky 500 */
        border: none !important; 
        color: #ffffff !important; 
        font-weight: 600 !important;
        border-radius: 8px !important;
        padding: 10px 20px !important;
        transition: all 0.2s ease;
    }
    .btn-modern-primary:hover { 
        background-color: #0284c7 !important; /* Sky 600 */
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(14, 165, 233, 0.25);
    }
    
    /* Upload Zone */
    .upload-zone {
        border: 2px dashed #475569; /* Slate 600 */
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
    
    /* DataTable Styling - Solid & Clean */
    .dash-table-container { 
        background: transparent !important; 
        border: none !important; 
    }
    .dash-spreadsheet-inner td { 
        background-color: #1e293b !important; /* Slate 800 */
        color: #e2e8f0 !important; 
        border-bottom: 1px solid #334155 !important; 
        font-size: 0.85rem;
        padding: 12px 15px !important;
    }
    .dash-spreadsheet-inner th { 
        background-color: #0f172a !important; /* Slate 900 Header */
        color: #94a3b8 !important; 
        border-bottom: 2px solid #334155 !important; 
        font-weight: 600;
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.5px;
    }
    .dash-spreadsheet tr:hover td {
        background-color: #334155 !important; /* Slate 700 Hover */
    }
    
    /* Navigation */
    .nav-link { 
        color: #94a3b8 !important; 
        font-weight: 500; 
        margin: 0 15px; 
        text-decoration: none !important; 
        padding: 8px 0 !important;
        border-bottom: 2px solid transparent;
        transition: all 0.2s;
    }
    .nav-link:hover { color: #e2e8f0 !important; }
    .nav-link.active { 
        color: #38bdf8 !important; 
        border-bottom-color: #38bdf8; 
    }
    
    /* Layout Utilities */
    .main-content { 
        padding-top: 100px; 
        padding-left: 2.5%; 
        padding-right: 2.5%; 
        max-width: 1650px; 
        margin: 0 auto; 
    }
    .section-title {
        color: #f8fafc;
        font-weight: 600;
        margin-bottom: 1.5rem;
        font-size: 1.25rem;
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
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>{CUSTOM_CSS}</style>
    </head>
    <body>
        {{%app_entry%}}
        <footer> {{%config%}} {{%scripts%}} {{%renderer%}} </footer>
    </body>
</html>
'''

# ==========================================================
# LAYOUT UTAMA: SOLID DARK MODE
# ==========================================================
app.layout = html.Div([
    # 1. TOP NAVBAR (Solid, Fixed)
    html.Div([
        dbc.Row([
            dbc.Col(html.H3("PKBI Jabar", style={'color': '#f8fafc', 'margin': '0', 'fontWeight': '800', 'fontSize': '1.5rem'}), width="auto"),
            dbc.Col(html.Div([
                html.A("Dashboard", href="#", className="nav-link active", id="nav-dashboard"),
                html.A("Riwayat", href="#", className="nav-link", id="nav-riwayat"),
                html.A("Laporan", href="#", className="nav-link", id="nav-laporan"),
            ], style={'display': 'flex', 'alignItems': 'center', 'height': '100%', 'justifyContent': 'flex-start'}), width=True),
            dbc.Col(html.Div([
                dbc.Button("⚙️", color="transparent", className="me-2", style={'fontSize': '1.2rem', 'padding': '0'}),
                html.Div(style={'width': '32px', 'height': '32px', 'borderRadius': '50%', 'background': '#0ea5e9', 'display': 'inline-block'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'flex-end'}), width="auto")
        ], align="center", className="g-0")
    ], style={
        'position': 'fixed', 'top': '0', 'left': '0', 'right': '0',
        'height': '70px', 'zIndex': '1000',
        'backgroundColor': '#0f172a', 'borderBottom': '1px solid #1e293b',
        'padding': '0 2.5%'
    }),

    # 2. MAIN CONTENT AREA
    html.Div(className="main-content", children=[
        
        # TAB CONTENT CONTAINER
        html.Div(id="tab-content-container", children=[
            
            # === DASHBOARD TAB ===
            html.Div(id="tab-dashboard", children=[
                # Control Bar Section
                dbc.Row([
                    dbc.Col([
                        dcc.Upload(
                            id='upload-penjangkauan',
                            children=html.Div([
                                html.I(className="bi bi-cloud-upload", style={'fontSize': '2rem', 'color': '#38bdf8', 'marginBottom': '10px', 'display': 'block'}),
                                html.Div("Upload File Penjangkauan & Rujukan", style={'fontWeight': '600', 'color': '#f8fafc', 'fontSize': '1.1rem'}),
                                html.Div("Drag & drop atau klik untuk memilih file (.xlsx, .csv)", style={'fontSize': '0.85rem', 'color': '#94a3b8', 'marginTop': '5px'})
                            ]),
                            className="upload-zone",
                            multiple=False
                        ),
                        html.Div(id="status-upload-penjangkauan", style={'marginTop': '10px', 'fontSize': '0.85rem', 'color': '#38bdf8'})
                    ], width=8),
                    dbc.Col([
                        html.Div([
                            html.Label("Pilih Aturan Validasi", style={'color': '#94a3b8', 'fontSize': '0.85rem', 'marginBottom': '5px'}),
                            dbc.Select(id="select-aturan", options=[{"label": "Aturan Validasi Bawaan", "value": "default"}], className="mb-3", style={'backgroundColor': '#0f172a', 'color': '#e2e8f0', 'borderColor': '#334155'}),
                            
                            html.Label("Keyword Media Sosial", style={'color': '#94a3b8', 'fontSize': '0.85rem', 'marginBottom': '5px'}),
                            dbc.Select(id="select-medsos", options=[{"label": "Keyword Medsos Default", "value": "default"}], className="mb-3", style={'backgroundColor': '#0f172a', 'color': '#e2e8f0', 'borderColor': '#334155'}),
                            
                            dbc.Button("Jalankan Validasi", id="btn-jalankan", className="btn-modern-primary w-100 py-3 mt-2", size="lg")
                        ], className="solid-card h-100 d-flex flex-column justify-content-center")
                    ], width=4)
                ], className="mb-4 g-3"),

                # Metrics Row
                dbc.Row([
                    dbc.Col(dbc.Card([
                        html.H2(id="metric-total-data", className="metric-value text-accent-blue"), 
                        html.P("Total Data Diproses", className="metric-label")
                    ], className="solid-card text-center border-0"), width=4),
                    
                    dbc.Col(dbc.Card([
                        html.H2(id="metric-temuan", className="metric-value text-accent-red"), 
                        html.P("Temuan Error", className="metric-label")
                    ], className="solid-card text-center border-0"), width=4),
                    
                    dbc.Col(dbc.Card([
                        html.H2(id="metric-akurasi", className="metric-value text-accent-green"), 
                        html.P("Tingkat Akurasi", className="metric-label")
                    ], className="solid-card text-center border-0"), width=4),
                ], className="mb-4 g-3"),

                # Main Workspace: Data Table
                html.Div([
                    html.H4("Hasil Review Detail", className="section-title"),
                    dcc.Loading(
                        id="loading-table",
                        type="circle",
                        color="#38bdf8",
                        children=dash_table.DataTable(
                            id='tabel-detail',
                            editable=True,
                            page_size=20,
                            style_table={'overflowX': 'auto', 'borderRadius': '12px'},
                            css=[{'selector': '.dash-spreadsheet-container', 'rule': 'border-radius: 12px; overflow: hidden;'}]
                        )
                    ),
                    dbc.Row([
                        dbc.Col(dbc.Button("💾 Simpan Progres ke Database", id="btn-simpan", className="btn-modern-primary w-100 mt-3"), width=6),
                        dbc.Col(html.Div(id="status-simpan", className="mt-3 text-center", style={'color': '#e2e8f0'}), width=6)
                    ])
                ], className="solid-card")
            ]),

            # === RIWAYAT TAB (Hidden by default) ===
            html.Div(id="tab-riwayat", style={'display': 'none'}, children=[
                html.H4("Riwayat Sesi Validasi", className="section-title"),
                html.Div([
                    dash_table.DataTable(
                        id='tabel-riwayat',
                        columns=[
                            {"name": "Waktu", "id": "waktu"},
                            {"name": "Periode", "id": "periode"},
                            {"name": "Total Data", "id": "total_data"},
                            {"name": "Temuan", "id": "temuan"},
                            {"name": "Akurasi", "id": "akurasi"},
                            {"name": "Status Arsip", "id": "status_arsip"},
                            {"name": "Aksi", "id": "aksi"}
                        ],
                        page_size=15,
                        style_table={'overflowX': 'auto', 'borderRadius': '12px'}
                    )
                ], className="solid-card"),
                dbc.Alert("ℹ️ Riwayat validasi tersimpan otomatis setiap kali tombol 'Jalankan Validasi' ditekan.", 
                          color="info", className="mt-3", 
                          style={'backgroundColor': 'rgba(56, 189, 248, 0.1)', 'borderColor': 'rgba(56, 189, 248, 0.3)', 'color': '#38bdf8'})
            ]),

            # === LAPORAN TAB (Hidden by default) ===
            html.Div(id="tab-laporan", style={'display': 'none'}, children=[
                html.H4("Pusat Unduhan Laporan", className="section-title"),
                dbc.Row([
                    dbc.Col(dbc.Card([
                        html.H5("Laporan Rekap Kesalahan (Excel)", style={'color': '#f8fafc', 'fontWeight': '600'}),
                        html.P("Download matriks kesalahan per SSR dan indikator.", style={'color': '#94a3b8', 'fontSize': '0.9rem', 'marginTop': '10px'}),
                        dbc.Button("📥 Download Excel", id="btn-dl-excel", className="btn-modern-primary w-100 mt-3")
                    ], className="solid-card"), width=6),
                    dbc.Col(dbc.Card([
                        html.H5("Laporan Tren Bulanan (PDF)", style={'color': '#f8fafc', 'fontWeight': '600'}),
                        html.P("Download grafik tren validasi semester terakhir.", style={'color': '#94a3b8', 'fontSize': '0.9rem', 'marginTop': '10px'}),
                        dbc.Button("📄 Download PDF", id="btn-dl-pdf", className="btn-modern-primary w-100 mt-3")
                    ], className="solid-card"), width=6)
                ])
            ])
        ])
    ])
])

# ==========================================================
# CALLBACKS: NAVIGASI TAB
# ==========================================================
@callback(
    [Output('tab-dashboard', 'style'), Output('tab-riwayat', 'style'), Output('tab-laporan', 'style'),
     Output('nav-dashboard', 'className'), Output('nav-riwayat', 'className'), Output('nav-laporan', 'className')],
    [Input('nav-dashboard', 'n_clicks'), Input('nav-riwayat', 'n_clicks'), Input('nav-laporan', 'n_clicks')]
)
def switch_tab(n_dash, n_riw, n_lap):
    triggered = ctx.triggered_id
    base_class = "nav-link"
    active_class = "nav-link active"
    
    if triggered == 'nav-riwayat':
        return {'display': 'none'}, {'display': 'block'}, {'display': 'none'}, base_class, active_class, base_class
    elif triggered == 'nav-laporan':
        return {'display': 'none'}, {'display': 'none'}, {'display': 'block'}, base_class, base_class, active_class
    else: # Default Dashboard
        return {'display': 'block'}, {'display': 'none'}, {'display': 'none'}, active_class, base_class, base_class

# ==========================================================
# CALLBACKS: UPLOAD FILES
# ==========================================================
def parse_contents(contents, filename):
    if not contents: return None
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
        if 'csv' in filename: return pd.read_csv(io.StringIO(decoded.decode('utf-8')), low_memory=False)
        else: return pd.read_excel(io.BytesIO(decoded))
    except: return None

@callback(Output('status-upload-penjangkauan', 'children'), Input('upload-penjangkauan', 'contents'), State('upload-penjangkauan', 'filename'))
def update_upload_status(contents, filename):
    if contents:
        df = parse_contents(contents, filename)
        if df is not None:
            server_state['df_penjangkauan'] = df
            return f"✅ {filename} berhasil dimuat ({len(df):,} baris)"
    return ""

# ==========================================================
# CALLBACKS: JALANKAN VALIDASI & UPDATE METRIKS
# ==========================================================
@callback(
    [Output('metric-total-data', 'children'), Output('metric-temuan', 'children'), Output('metric-akurasi', 'children'),
     Output('tabel-detail', 'data'), Output('tabel-detail', 'columns'), Output('status-simpan', 'children')],
    Input('btn-jalankan', 'n_clicks'), prevent_initial_call=True
)
def run_validation(n_clicks):
    df_raw = server_state.get('df_penjangkauan')
    if df_raw is None or df_raw.empty:
        return "0", "0", "0%", [], [], "⚠️ Silakan upload file penjangkauan terlebih dahulu!"

    # Jalankan engine vektorisasi
    df_errors = jalankan_review_data_optimized(df_raw, server_state.get('df_referensi'))
    server_state['df_hasil_validasi'] = df_errors
    
    tot_data = len(df_raw)
    tot_err = len(df_errors) if df_errors is not None else 0
    akurasi = max(0, 100 - (tot_err / tot_data * 100)) if tot_data > 0 else 100.0

    # Simpan ke Riwayat
    server_state['riwayat_validasi'].append({
        'waktu': datetime.now().strftime('%d/%m/%Y %H:%M'),
        'periode': 'Periode Aktif',
        'total_data': f"{tot_data:,}",
        'temuan': f"{tot_err:,}",
        'akurasi': f"{akurasi:.2f}%",
        'status_arsip': '⏳ Pending',
        'aksi': 'Lihat Detail'
    })

    cols = [{"name": i, "id": i, "editable": (i in ['Pilih', 'Justifikasi'])} for i in df_errors.columns] if df_errors is not None else []
    data = df_errors.to_dict('records') if df_errors is not None else []

    return f"{tot_data:,}", f"{tot_err:,}", f"{akurasi:.1f}%", data, cols, "✅ Validasi selesai! Silakan review tabel di bawah."

# ==========================================================
# CALLBACKS: SIMPAN KE DATABASE (CHUNKED)
# ==========================================================
@callback(Output('status-simpan', 'children', allow_duplicate=True), Input('btn-simpan', 'n_clicks'), State('tabel-detail', 'data'), prevent_initial_call=True)
def save_to_db(n_clicks, table_data):
    if not table_data: return "ℹ️ Tidak ada data untuk disimpan."
    
    list_log = []
    for row in table_data:
        if bool(row.get('Pilih', False)) or ("konfirmasi" in str(row.get('INDIKATOR KESALAHAN DATA', '')).lower() and str(row.get('Justifikasi', '')).strip() != ""):
            list_log.append((
                str(row.get('Lembaga SSR', '')), str(row.get('Tanggal', '')), str(row.get('ID Klien', '')),
                str(row.get('INDIKATOR KESALAHAN DATA', '')), bool(row.get('Pilih', False)), 
                str(row.get('Justifikasi', '')).strip()
            ))
            
    if list_log:
        if simpan_log_ke_neon_chunked(list_log):
            # Update status arsip di riwayat
            if server_state['riwayat_validasi']:
                server_state['riwayat_validasi'][-1]['status_arsip'] = '✅ Tersimpan'
            return f"🎉 Berhasil menyimpan {len(list_log)} baris ke Neon Database!"
        return "❌ Gagal menyimpan ke database."
    return "ℹ️ Centang 'Pilih' atau isi 'Justifikasi' untuk menyimpan."

# ==========================================================
# CALLBACKS: UPDATE TABEL RIWAYAT
# ==========================================================
@callback(Output('tabel-riwayat', 'data'), Input('nav-riwayat', 'n_clicks'), prevent_initial_call=True)
def update_riwayat_table(n):
    return server_state.get('riwayat_validasi', [])

if __name__ == '__main__':
    app.run_server(debug=True, port=8050)
