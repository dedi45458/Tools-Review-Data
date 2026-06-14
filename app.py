import dash
from dash import dcc, html, dash_table, Input, Output, State, callback, ctx
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import base64
import io
import re
from datetime import datetime
import plotly.graph_objects as go

# ==========================================================
# IMPORT FUNGSI DARI database.py
# ==========================================================
from database import (
    dapatkan_koneksi_neon,
    simpan_log_ke_neon,
    jalankan_agregasi_tren,
    ambil_rekap_tren,
    hitung_dan_ambil_log_db,
    import_data_rujukan,
    tambah_keyword_medsos,
    ambil_keyword_medsos
)

# ==========================================================
# MOCK st.session_state (Agar fungsi asli tidak perlu diubah)
# ==========================================================
class MockSessionState(dict):
    pass

class MockST:
    def __init__(self):
        self.session_state = MockSessionState()
        self.session_state['aturan_kustom'] = []
        self.session_state['medsoc_keywords'] = []

st = MockST()

# Global state untuk Dash (menggantikan st.session_state untuk data besar)
server_state = {
    'df_review_list': [],
    'df_ref': None,
    'df_tabel_atas': None,
    'df_tabel_bawah': None,
    'total_entri': 0
}

# ==========================================================
# FUNGSI HELPER & ATURAN VALIDASI (SAMA PERSIS DENGAN ASLI)
# ==========================================================
def cek_kode(teks_kolom, kode_target):
    if pd.isna(teks_kolom) or str(teks_kolom).strip().lower() in ['', 'nan']: return False
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

def jalankan_review_data(df_asli, df_ref=None, nama_file=""):
    list_kesalahan = []
    if df_asli.empty: return pd.DataFrame(list_kesalahan)
    
    df = df_asli.copy()
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
            
    is_file_rujukan = any('RUJUKAN' in str(c).upper() for c in df.columns) or any('FASYANKES' in str(c).upper() for c in df.columns)
    tahun_sekarang = datetime.now().year
    hari_ini = pd.Timestamp(datetime.now().date())

    keywords_aktif = st.session_state.get('medsoc_keywords', [])
    pattern_medsos_dinamis = r'\b(' + '|'.join([re.escape(k) for k in keywords_aktif]) + r')\b' if keywords_aktif else r'\b(TIDAK_ADA_MEDSOS)\b'

    try: dict_revisi, dict_justifikasi = hitung_dan_ambil_log_db()
    except: dict_revisi, dict_justifikasi = {}, {}

    ref_ssr_id_to_nik, ref_nik_ssr_to_id = {}, {}
    dict_pernah_cbs, dict_pernah_prep_rujukan = {}, {}
    
    if is_file_rujukan and df_ref is not None and not df_ref.empty:
        df_ref_cp = df_ref.copy()
        df_ref_cp.columns = [str(c).strip() for c in df_ref_cp.columns]
        col_id_ref = [c for c in df_ref_cp.columns if 'ID' in c or 'Klien' in c]
        col_nik_ref = [c for c in df_ref_cp.columns if 'NIK' in c]
        col_ssr_ref = [c for c in df_ref_cp.columns if 'SSR' in c or 'Lembaga' in c]
        col_layanan_ref = [c for c in df_ref_cp.columns if 'Jenis Layanan' in c or 'Layanan' in c]
        col_rujukan_ref = [c for c in df_ref_cp.columns if 'Rujukan' in c]

        if col_id_ref and col_ssr_ref:
            for _, r in df_ref_cp.iterrows():
                ssr_r = str(r[col_ssr_ref[0]]).strip().upper()
                id_r = str(r[col_id_ref[0]]).replace("'", "").strip()
                nik_r = str(r[col_nik_ref[0]]).replace("'", "").replace('.0', '').strip() if col_nik_ref else ''
                key_klien = f"{ssr_r}_{id_r}"
                if id_r and id_r != 'nan' and ssr_r and ssr_r != 'nan': ref_ssr_id_to_nik[key_klien] = nik_r
                if nik_r and nik_r != 'nan' and nik_r != '' and ssr_r and ssr_r != 'nan': ref_nik_ssr_to_id[f"{nik_r}_{ssr_r}"] = id_r
                if col_layanan_ref:
                    layanans = str(r[col_layanan_ref[0]]).replace("'", "").replace(" ", "").split(',')
                    if '5' in layanans or '6' in layanans: dict_pernah_cbs[key_klien] = True
                if col_rujukan_ref:
                    rujukans = str(r[col_rujukan_ref[0]]).replace("'", "").replace(" ", "").split(',')
                    if '5' in rujukans: dict_pernah_prep_rujukan[key_klien] = True

    df['id_mapped'] = df.get('ID Klien', pd.Series(dtype=str)).astype(str).str.replace("'", "").str.strip()
    df['ssr_id_key'] = df.get('Lembaga SSR', pd.Series(dtype=str)).astype(str).str.strip().str.upper() + "_" + df['id_mapped']
    dict_ssr_id_counts = df.iloc[start_row_idx:]['ssr_id_key'].value_counts().to_dict()
    
    def periksa_hiv(x): return '1' in str(x).replace("'", "").replace(" ", "").split(',')
    def periksa_rujukan(x): 
        s = str(x).replace("'", "").replace(" ", "").replace(".0", "")
        if '.' in s and ',' not in s: s = s.replace('.', ',')
        return '2' in s.split(',')

    col_info = next((c for c in df.columns if "INFORMASI" in str(c).upper() and "DIBERIKAN" in str(c).upper()), "")
    col_kegiatan = next((c for c in df.columns if "JENIS KEGIATAN" in str(c).upper()), "")
    col_ruj = next((c for c in df.columns if "RUJUKAN" in str(c).upper()), "")
    
    if col_info and col_kegiatan: df['is_info_hiv'] = df[col_info].apply(periksa_hiv) | df[col_kegiatan].apply(periksa_hiv)
    else: df['is_info_hiv'] = False
    if col_ruj: df['is_rujuk_tes'] = df[col_ruj].apply(periksa_rujukan)
    else: df['is_rujuk_tes'] = False

    dict_pernah_hiv = df.groupby('ssr_id_key')['is_info_hiv'].any().to_dict()
    dict_pernah_rujuk = df.groupby('ssr_id_key')['is_rujuk_tes'].any().to_dict()

    def _safe_float(val):
        try: return float(val) if pd.notna(val) and str(val).strip().lower() not in ['', 'nan'] else 0.0
        except: return 0.0

    col_kie_list = [c for c in df.columns if 'KIE' in str(c).upper()]
    col_kon_list = [c for c in df.columns if 'KONDOM' in str(c).upper()]
    col_pel_list = [c for c in df.columns if 'PELICIN' in str(c).upper()]
    col_jar_list = [c for c in df.columns if 'JARUM' in str(c).upper() and 'KEMBALI' not in str(c).upper()]
    col_swab_list = [c for c in df.columns if 'SWAB' in str(c).upper() or 'ALKOHOL' in str(c).upper()]
    semua_kolom_logistik = col_kie_list + col_kon_list + col_pel_list + col_jar_list + col_swab_list

    df['tmp_log'] = 0.0
    for col in semua_kolom_logistik: df['tmp_log'] += df[col].apply(_safe_float)
    df['kunci_klien_ref_log'] = df.get('Lembaga SSR', pd.Series(dtype=str)).astype(str).str.strip().str.upper() + "_" + df['id_mapped']
    dict_total_log_per_klien = df.groupby('kunci_klien_ref_log')['tmp_log'].sum().to_dict()

    aturan_kustom = st.session_state.get('aturan_kustom', [])
    SEMUA_ATURAN_AKTIF = ATURAN_VALIDASI_BAWAAN + aturan_kustom

    for idx in range(start_row_idx, len(df)):
        row = df.iloc[idx]
        v_ssr = str(row.get('Lembaga SSR', '')).strip().upper() if pd.notna(row.get('Lembaga SSR')) else ''
        v_petugas = str(row.get('Kode Petugas', '')).replace("'", "").strip() if pd.notna(row.get('Kode Petugas')) else ''
        v_kota = str(row.get('Nama Kota', '')).strip() if pd.notna(row.get('Nama Kota')) else ''
        v_tanggal = str(row.get('Tanggal', '')).split(' ')[0] if pd.notna(row.get('Tanggal')) else ''
        
        id_clean = str(row.get('ID Klien', '')).strip().replace("'", "")
        nik_clean = str(row.get('NIK', '')).strip().replace("'", "").replace('.0', '')
        v_tipe_sasaran = str(row.get('Tipe Sasaran', row.get('Tipe Klien', ''))).replace('.0', '').strip()
        umur = row.get('Umur', None)
        jk = str(row.get('Jenis Kelamin', '')).replace('.0', '').strip()
        jns_kontak = str(row.get('Jenis Kontak', '')).replace('.0', '').strip()
        jns_kegiatan = str(row.get('Jenis Kegiatan', '')).strip()
        lokasi = str(row.get('Lokasi Outreach / Jenis Sosial Media', '')).strip()
        info_diberikan = str(row.get(col_info, '')).strip() if col_info else ''
        rujukan = str(row.get(col_ruj, '')).strip() if col_ruj else ''
        no_hp = str(row.get('No. HP / Nama Akun', '')).strip()
        vc1 = str(row.get('Virtual & Tatap Muka', '')).replace('.0', '').strip()

        log_kie = sum(_safe_float(row.get(c, 0)) for c in col_kie_list)
        log_kon = sum(_safe_float(row.get(c, 0)) for c in col_kon_list)
        log_pel = sum(_safe_float(row.get(c, 0)) for c in col_pel_list)
        log_jar = sum(_safe_float(row.get(c, 0)) for c in col_jar_list)
        log_swab = sum(_safe_float(row.get(c, 0)) for c in col_swab_list)
        jarum_kembali = _safe_float(row.get('Jumlah Jarum Suntik Kembali', 0))

        tgl_raw = row.get('Tanggal', None)
        tgl_p = pd.to_datetime(tgl_raw, errors='coerce', format='%d/%m/%Y') if pd.notna(tgl_raw) and '/' in str(tgl_raw) else pd.to_datetime(tgl_raw, errors='coerce')

        kunci_klien_ref = f"{v_ssr}_{id_clean}"
        context_data = {
            'row': row, 'id_clean': id_clean, 'nik_clean': nik_clean, 'v_ssr': v_ssr, 'v_tanggal': v_tanggal,
            'v_petugas': v_petugas, 'v_kota': v_kota, 'v_tipe_sasaran': v_tipe_sasaran, 'umur': umur, 'jk': jk,
            'jns_kontak': jns_kontak, 'jns_kegiatan': jns_kegiatan, 'lokasi': lokasi, 'info_diberikan': info_diberikan,
            'rujukan': rujukan, 'no_hp': no_hp, 'vc1': vc1, 'log_kie': log_kie, 'log_kon': log_kon, 'log_pel': log_pel,
            'log_jar': log_jar, 'log_swab': log_swab, 'jarum_kembali': jarum_kembali, 'tgl_p': tgl_p, 'hari_ini': hari_ini,
            'tahun_sekarang': tahun_sekarang, 'is_vo': (jns_kontak == '3'), 'is_pwid': (v_tipe_sasaran in ['1401', '1403']),
            'id_counts': {id_clean: dict_ssr_id_counts.get(kunci_klien_ref, 0)}, 
            'pernah_dapat_info_hiv': dict_pernah_hiv.get(kunci_klien_ref, False), 
            'pernah_dapat_rujuk_tes': dict_pernah_rujuk.get(kunci_klien_ref, False),
            'is_file_rujukan': is_file_rujukan, 'df_ref': df_ref, 'ref_ssr_id_to_nik': ref_ssr_id_to_nik, 'ref_nik_ssr_to_id': ref_nik_ssr_to_id,
            'pernah_cbs_di_rujukan': dict_pernah_cbs.get(kunci_klien_ref, False),
            'pernah_prep_di_rujukan': dict_pernah_prep_rujukan.get(kunci_klien_ref, False),
            'total_log_keseluruhan_klien': dict_total_log_per_klien.get(kunci_klien_ref, 0.0),
            'pattern_medsos': pattern_medsos_dinamis
        }

        for rule in SEMUA_ATURAN_AKTIF:
            nama_ind = rule["nama"]
            try:
                if rule["periksa"](context_data):
                    key_db = f"{v_ssr}_{v_tanggal}_{id_clean}_{nama_ind}"
                    is_butuh_konfirmasi = "konfirmasi" in nama_ind.lower()
                    if is_butuh_konfirmasi and key_db in dict_justifikasi and not dict_revisi.get(key_db, False): continue
                        
                    status_validasi = "-"
                    justif_val = dict_justifikasi.get(key_db, "") if is_butuh_konfirmasi else ""
                    if key_db in dict_revisi: status_validasi = "kesalahan pada ID yang berulang (belum dilakukan revisi)"

                    list_kesalahan.append({
                        "Pilih": False, "Lembaga SSR": v_ssr, "Tanggal": v_tanggal, "ID Klien": id_clean, 
                        "Kode Petugas": v_petugas, "Nama Kota": v_kota, "NIK": nik_clean, "Tipe Sasaran": v_tipe_sasaran,
                        "INDIKATOR KESALAHAN DATA": nama_ind, "validasi hasil review": status_validasi, "Justifikasi": justif_val
                    })
            except: pass

    return pd.DataFrame(list_kesalahan)

ATURAN_VALIDASI_BAWAAN = [
    {"nama": "Tahun dalam tanggal penjangkauan lebih besar/kecil dari tahun sekarang", "periksa": lambda c: pd.notna(c['tgl_p']) and c['tgl_p'].year != c['tahun_sekarang']},
    {"nama": "Kode Petugas Kosong", "periksa": lambda c: pd.isna(c['row'].get('Kode Petugas')) or str(c['row'].get('Kode Petugas')).strip() in ['', 'nan', 'None']},
    {"nama": "Tanggal lebih besar dari tanggal hari ini", "periksa": lambda c: pd.notna(c['tgl_p']) and c['tgl_p'] > c['hari_ini']},
    {"nama": "IDKD kurang/lebih dari 10 digit karakter", "periksa": lambda c: c['id_clean'] != '' and (len(c['id_clean']) != 10 or not c['id_clean'].isalnum())},
    {"nama": "Digit nama kurang/lebih dari 4 digit karakter", "periksa": lambda c: c['id_clean'] != '' and (len(c['id_clean']) < 4 or not (c['id_clean'][:4].isalpha() or (c['id_clean'][:3].isalpha() and c['id_clean'][3] == '0')))},
    {"nama": "Digit tanggal lahir lebih/kurang dari 6 digit angka", "periksa": lambda c: c['id_clean'] != '' and len(c['id_clean']) == 10 and not c['id_clean'][4:].isdigit()},
    {"nama": "Ada tanda titik (.) pada penulisan IDKD", "periksa": lambda c: '.' in str(c['row'].get('ID Klien', ''))},
    {"nama": "Ada spasi pada penulisan IDKD", "periksa": lambda c: ' ' in str(c['row'].get('ID Klien', ''))},
    {"nama": "ID sama tapi NIK berbeda dengan data Semester/Tahun lalu (Konfirmasi)", "periksa": lambda c: c['is_file_rujukan'] and c['df_ref'] is not None and c['v_ssr'] and f"{c['v_ssr']}_{c['id_clean']}" in c['ref_ssr_id_to_nik'] and c['ref_ssr_id_to_nik'][f"{c['v_ssr']}_{c['id_clean']}"] != c['nik_clean']},
    {"nama": "NIK sama tapi ID berbeda dengan data Semester/Tahun lalu (Konfirmasi)", "periksa": lambda c: c['is_file_rujukan'] and c['df_ref'] is not None and c['v_ssr'] and c['nik_clean'] != '' and f"{c['nik_clean']}_{c['v_ssr']}" in c['ref_nik_ssr_to_id'] and c['ref_nik_ssr_to_id'][f"{c['nik_clean']}_{c['v_ssr']}"] != c['id_clean']},
    {"nama": "Usia KD dibawah 16 tahun (konfirmasi)", "periksa": lambda c: pd.notna(c['umur']) and str(c['umur']).strip() != '' and float(c['umur']) < 17},
    {"nama": "Usia KD diatas 70 tahun (konfirmasi)", "periksa": lambda c: pd.notna(c['umur']) and str(c['umur']).strip() != '' and float(c['umur']) > 70},
    {"nama": "Tahun lahir pada IDKD berbeda dengan Tahun lahir pada NIK (konfirmasi)", "periksa": lambda c: c['id_clean'] != '' and len(c['id_clean']) == 10 and c['nik_clean'] != '' and len(c['nik_clean']) == 16 and c['id_clean'][4:6] != (str(c['row'].get('NIK', '')) if str(c['row'].get('NIK', '')).startswith("'") else "'" + c['nik_clean'])[11:13]},
    {"nama": "NIK kurang/lebih dari 16 digit (konfirmasi)", "periksa": lambda c: c['nik_clean'] not in ['', 'nan', 'none', 'NaN', "'"] and len(c['nik_clean']) != 16},
    {"nama": "Kesalahan dalam penulisan NIK (00) (konfirmasi)", "periksa": lambda c: c['nik_clean'] != '' and c['nik_clean'].endswith('00')},
    {"nama": "Secara NIK harusnya perempuan bukan laki-laki (konfirmasi)", "periksa": lambda c: len(c['nik_clean']) == 16 and c['jk'] == '1' and int(c['nik_clean'][6:8]) > 31 if c['nik_clean'].isdigit() and len(c['nik_clean'])>=8 else False},
    {"nama": "LSL/Waria tapi jenis kelamin perempuan", "periksa": lambda c: c['v_tipe_sasaran'] in ['1304', '1301'] and c['jk'] == '2'},
    {"nama": "Jenis kontak dengan Jenis Kegiatan tidak sesuai", "periksa": lambda c: (c['jns_kontak'] == '1' and c['jns_kegiatan'] not in ['1', '5']) or (c['jns_kontak'] == '2' and c['jns_kegiatan'] not in ['2', '3', '4', '6', '7']) or (c['jns_kontak'] == '3' and c['jns_kegiatan'] != '8')},
    {"nama": "Jenis kontak Individual/kelompok tapi kolom Virtual dan Tatap Muka (VC1) tidak diisi", "periksa": lambda c: c['jns_kontak'] in ['1', '2'] and (c['vc1'] == '' or c['vc1'] == 'nan')},
    {"nama": "Penjangkauan tatap muka tapi lokasi outreach diindikasi ada nama medsos", "periksa": lambda c: c['jns_kontak'] in ['1', '2'] and c['pattern_medsos'] is not None and bool(re.search(c['pattern_medsos'], str(c['lokasi']), re.IGNORECASE))},
    {"nama": "Lokasi outreach diisi IDKD", "periksa": lambda c: c['lokasi'] != '' and c['lokasi'] != 'nan' and len(c['lokasi']) == 10 and c['lokasi'][:4].isalpha() and c['lokasi'][4:].isdigit()},
    {"nama": "Lokasi outreach diindikasi kurang spesifik atau kurang detil (digit huruf <17 digit) (konfirmasi)", "periksa": lambda c: c['lokasi'] != '' and c['lokasi'] != 'nan' and len(c['lokasi']) < 17 and not c['is_vo']},
    {"nama": "Lokasi outreach indikasi diisi nomer HP", "periksa": lambda c: c['lokasi'] != '' and c['lokasi'] != 'nan' and re.search(r'(08\d{8,11})|(\+62\d{8,11})', c['lokasi'].replace('-', '').replace(' ', ''))},
    {"nama": "Bukan PWID mendapatkan info 8 atau 9 (LASS, PTRM)", "periksa": lambda c: not c['is_pwid'] and (cek_kode(c['info_diberikan'], '8') or cek_kode(c['info_diberikan'], '9'))},
    {"nama": "LSL/TG/PWID menerima informasi PMTC (konfirmasi)", "periksa": lambda c: c['v_tipe_sasaran'] in ['1304', '1301', '1401'] and cek_kode(c['info_diberikan'], '6')},
    {"nama": "Konfirmasi jumlah KIE yang diberikan adalah wajar (konfirmasi)", "periksa": lambda c: c['log_kie'] > 5},
    {"nama": "Konfirmasi jumlah kondom yang diberikan adalah wajar (konfirmasi)", "periksa": lambda c: c['log_kon'] > 144},
    {"nama": "Konfirmasi jumlah pelicin yang diberikan adalah wajar (konfirmasi)", "periksa": lambda c: c['log_pel'] > 50},
    {"nama": "Konfirmasi jumlah jarum yang diberikan adalah wajar (konfirmasi)", "periksa": lambda c: c['log_jar'] > 10},
    {"nama": "Konfirmasi jumlah alkohol SWAB yang diberikan adalah wajar (konfirmasi)", "periksa": lambda c: c['log_swab'] > 50},
    {"nama": "VO tapi kolom Virtual dan Tatap Muka (VC1) diisi angka 1", "periksa": lambda c: c['is_vo'] and c['vc1'] == '1'},
    {"nama": "VO tapi lokasi outreach bukan nama medsos/kurang tepat mencatat nama aplikasi medsos", "periksa": lambda c: c['is_vo'] and str(c['lokasi']).strip() != '' and (c['pattern_medsos'] is None or not bool(re.search(c['pattern_medsos'], str(c['lokasi']), re.IGNORECASE)))},
    {"nama": "VO tapi menyerahkan jarum", "periksa": lambda c: c['is_vo'] and c['log_jar'] > 0},
    {"nama": "VO menerima logistik selain KIE", "periksa": lambda c: c['is_vo'] and (c['log_kon'] > 0 or c['log_pel'] > 0 or c['log_swab'] > 0)},
    {"nama": "VO tapi nama akun /No. Hp tidak diisi", "periksa": lambda c: c['is_vo'] and (c['no_hp'] == '' or c['no_hp'] == 'nan')},
    {"nama": "Tidak ada informasi satupun yang diberikan / tidak diisi", "periksa": lambda c: str(c.get('info_diberikan', '')).strip() == '' or str(c.get('info_diberikan', '')).strip().lower() in ['nan', 'none', 'null']},
    {"nama": "KD dikontak lebih dari 1x tapi tidak mendapat informasi HIV", "periksa": lambda c: c['id_clean'] != '' and c['id_counts'].get(c['id_clean'], 0) > 1 and not c['pernah_dapat_info_hiv']},
    {"nama": "KD telah menerima layanan CBS tapi tidak ada informasi CBS", "periksa": lambda c: c['pernah_cbs_di_rujukan'] and not cek_kode(c['info_diberikan'], '13')},
    {"nama": "KD ada rujukan PrEp di penjangkauan tapi tidak ada informasi PrEp", "periksa": lambda c: cek_kode(c['rujukan'], '5') and not cek_kode(c['info_diberikan'], '10')},
    {"nama": "KD telah menerima layanan PrEp tapi tidak ada rujukan PrEp di penjangkauan", "periksa": lambda c: c['pernah_prep_di_rujukan'] and not cek_kode(c['rujukan'], '5')},
    {"nama": "Logistik kosong (Konfirmasi)", "periksa": lambda c: c['total_log_keseluruhan_klien'] == 0},
    {"nama": "Tipe klien PWID tapi tidak menerima jarum (konfirmasi)", "periksa": lambda c: c['is_pwid'] and c['log_jar'] == 0 and not c['is_vo']},
    {"nama": "Tipe klien PWID tapi tidak menerima alkohol SWAB (konfirmasi)", "periksa": lambda c: c['is_pwid'] and c['log_swab'] == 0 and not c['is_vo']},
    {"nama": "Popkun selain PWID menerima jarum suntik", "periksa": lambda c: not c['is_pwid'] and c['log_jar'] > 0},
    {"nama": "Popkun selain PWID menerima alkohol swab", "periksa": lambda c: not c['is_pwid'] and c['log_swab'] > 0},
    {"nama": "Popkun selain PWID menyerahkan jarum", "periksa": lambda c: not c['is_pwid'] and c['jarum_kembali'] > 0},
    {"nama": "Tidak ada rujukan yang diberikan satupun / tidak diisi", "periksa": lambda c: c['rujukan'] == '' or c['rujukan'] == 'nan'},
    {"nama": "KD dikontak lebih dari 1x tetapi tidak ada Rujukan Tes HIV (konfirmasi)", "periksa": lambda c: c['id_clean'] != '' and c['id_counts'].get(c['id_clean'], 0) > 1 and not c['pernah_dapat_rujuk_tes']},
    {"nama": "Bukan penasun rujukan 3,4", "periksa": lambda c: not c['is_pwid'] and (cek_kode(c['rujukan'], '3') or cek_kode(c['rujukan'], '4'))}
]

# ==========================================================
# INISIALISASI APLIKASI DASH & TEMA GLASSMORPHISM
# ==========================================================
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SLATE])

app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>Executive Review - PKBI Jabar</title>
        {%favicon%}
        {%css%}
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body { 
                background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%) !important; 
                font-family: 'Inter', sans-serif; 
                color: #cbd5e1;
                margin: 0;
            }
            .glass-card {
                background: rgba(255, 255, 255, 0.03);
                backdrop-filter: blur(12px);
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 16px;
                padding: 2rem;
                box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.2);
                margin-bottom: 20px;
                color: #f8fafc;
            }
            .main-title { font-size: 2.2rem; font-weight: 800; margin-bottom: 0.2rem; letter-spacing: -0.5px; color: #f8fafc; }
            .sub-title { font-size: 1.1rem; color: #94a3b8 !important; margin-bottom: 2rem; font-weight: 400; }
            .metric-value { color: #38bdf8 !important; font-weight: 700; font-size: 2rem; margin: 0; }
            .metric-label { color: #94a3b8; font-size: 0.9rem; margin-bottom: 5px; }
            
            .sidebar {
                background: rgba(15, 23, 42, 0.8);
                backdrop-filter: blur(10px);
                border-right: 1px solid rgba(255, 255, 255, 0.05);
                min-height: 100vh;
                padding: 2rem 1.5rem;
            }
            .main-content { padding: 2rem; }
            
            /* Override DBC & Dash Components */
            .card, .dash-table, .form-control, .input-group, .btn, .Select-control {
                background-color: rgba(255, 255, 255, 0.05) !important;
                border: 1px solid rgba(255, 255, 255, 0.1) !important;
                color: #f8fafc !important;
            }
            .btn-primary { background-color: #38bdf8 !important; border-color: #38bdf8 !important; color: #0f172a !important; font-weight: 600;}
            .btn-primary:hover { background-color: #0ea5e9 !important; }
            
            /* Tabs */
            .tab { color: #94a3b8 !important; background-color: transparent !important; border: none !important; }
            .tab--selected { color: #38bdf8 !important; border-bottom: 2px solid #38bdf8 !important; }
            
            /* Data Tables */
            .dash-table-container .dash-spreadsheet-container { background-color: transparent !important; border: none !important; }
            .dash-spreadsheet-inner td { background-color: rgba(255, 255, 255, 0.02) !important; color: #cbd5e1 !important; border-color: rgba(255, 255, 255, 0.05) !important; }
            .dash-spreadsheet-inner th { background-color: rgba(255, 255, 255, 0.05) !important; color: #f8fafc !important; border-color: rgba(255, 255, 255, 0.1) !important; }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer> {%config%} {%scripts%} {%renderer%} </footer>
    </body>
</html>
'''

# ==========================================================
# LAYOUT APLIKASI
# ==========================================================
app.layout = dbc.Container([
    dbc.Row([
        # SIDEBAR
        dbc.Col([
            html.H3("🛠️ Control Panel", style={'color': '#f8fafc', 'marginBottom': '5px'}),
            html.P("Sistem Navigasi & Manajemen", style={'color': '#94a3b8', 'fontSize': '0.85rem', 'marginTop': '0'}),
            html.Hr(style={'borderColor': 'rgba(255,255,255,0.1)'}),
            
            dcc.RadioItems(
                id="menu-navigasi",
                options=[
                    {"label": " 🎯 Dashboard Review Data", "value": "dashboard"},
                    {"label": " ⚙️ Pengaturan Keyword Medsos", "value": "medsos"}
                ],
                value="dashboard",
                labelStyle={'display': 'block', 'padding': '10px', 'color': '#cbd5e1', 'cursor': 'pointer', 'borderRadius': '8px'},
                className="mb-4"
            ),
            
            html.Div(id="sidebar-dashboard-controls"),
            html.Div(id="sidebar-medsos-controls", style={'display': 'none'})
        ], width=3, className="sidebar px-0"),
        
        # MAIN CONTENT
        dbc.Col([
            html.Div([
                html.H1("📊 Tools Review Data PKBI Jawa Barat", className="main-title"),
                html.P("Sistem Penelaahan Kualitas Data Penjangkauan & Rujukan Terpadu (Neon DB)", className="sub-title")
            ]),
            html.Div(id="main-dashboard-content"),
            html.Div(id="main-medsos-content", style={'display': 'none'})
        ], width=9, className="main-content")
    ])
], fluid=True)

# ==========================================================
# CALLBACKS: NAVIGASI MENU
# ==========================================================
@callback(
    [Output('sidebar-dashboard-controls', 'style'),
     Output('sidebar-medsos-controls', 'style'),
     Output('main-dashboard-content', 'style'),
     Output('main-medsos-content', 'style')],
    Input('menu-navigasi', 'value')
)
def toggle_menu(menu):
    if menu == 'dashboard':
        return {'display': 'block'}, {'display': 'none'}, {'display': 'block'}, {'display': 'none'}
    else:
        return {'display': 'none'}, {'display': 'block'}, {'display': 'none'}, {'display': 'block'}

# ==========================================================
# CALLBACKS: UPLOAD FILE
# ==========================================================
def parse_contents(contents, filename):
    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    try:
        if 'csv' in filename: return pd.read_csv(io.StringIO(decoded.decode('utf-8')))
        else: return pd.read_excel(io.BytesIO(decoded))
    except: return None

@callback(
    Output('upload-status-ref', 'children', allow_duplicate=True),
    Input('upload-ref-data', 'contents'),
    State('upload-ref-data', 'filename'),
    prevent_initial_call=True
)
def upload_ref(contents, filename):
    if contents:
        df = parse_contents(contents, filename)
        if df is not None:
            server_state['df_ref'] = df
            return "✅ File referensi tersimpan di memori."
    return ""

@callback(
    Output('upload-status-ref', 'children', allow_duplicate=True),
    Input('btn-update-ref', 'n_clicks'),
    prevent_initial_call=True
)
def update_ref_db(n_clicks):
    if server_state['df_ref'] is not None:
        if import_data_rujukan(server_state['df_ref']): return "✅ Database referensi diperbarui!"
        else: return "❌ Gagal mengupdate database."
    return "⚠️ Unggah file terlebih dahulu."

@callback(
    Output('upload-status-raw', 'children'),
    Input('upload-raw-data', 'contents'),
    State('upload-raw-data', 'filename'),
    prevent_initial_call=True
)
def upload_raw(contents_list, filenames):
    if contents_list:
        server_state['df_review_list'] = []
        for c, name in zip(contents_list, filenames):
            df = parse_contents(c, name)
            if df is not None: server_state['df_review_list'].append((name, df))
        return f"📁 {len(contents_list)} file siap diproses."
    return ""

# ==========================================================
# CALLBACKS: ATURAN KUSTOM
# ==========================================================
@callback(
    Output('list-aturan-aktif', 'children'),
    Input('btn-tambah-aturan', 'n_clicks'),
    [State('input-nama-ind', 'value'), State('select-kolom', 'value'), State('select-kondisi', 'value'), State('input-pembanding', 'value')],
    prevent_initial_call=True
)
def add_custom_rule(n_clicks, nama, kolom, kondisi, pembanding):
    if nama and (kondisi == "Kosong / Blank" or pembanding):
        mapping_kunci = {"NIK": "nik_clean", "ID Klien": "id_clean", "Umur": "umur", "Lembaga SSR": "v_ssr", "Kode Petugas": "v_petugas", "Lokasi Outreach / Jenis Sosial Media": "lokasi", "Informasi Yang diberikan": "info_diberikan", "Rujukan": "rujukan"}
        kunci_target = mapping_kunci.get(kolom, "")
        fungsi_validasi = buat_fungsi_validasi_kustom(kunci_target, kondisi, pembanding or "")
        st.session_state['aturan_kustom'].append({"nama": nama, "periksa": fungsi_validasi})
        
    return [html.Div(f"📌 {r['nama']}", style={'fontSize': '0.85rem', 'color': '#cbd5e1', 'padding': '4px 0'}) for r in st.session_state['aturan_kustom']]

# ==========================================================
# CALLBACKS: EKSEKUSI VALIDASI UTAMA
# ==========================================================
@callback(
    [Output('metric-total-data', 'children'),
     Output('metric-total-temuan', 'children'),
     Output('metric-akurasi', 'children'),
     Output('tabel-matriks', 'data'),
     Output('tabel-matriks', 'columns'),
     Output('grafik-tren', 'figure'),
     Output('tabel-detail', 'data'),
     Output('tabel-detail', 'columns'),
     Output('status-proses', 'children')],
    Input('btn-jalankan', 'n_clicks'),
    prevent_initial_call=True
)
def run_validation(n_clicks):
    if not server_state['df_review_list']:
        return "0", "0", "0%", [], [], go.Figure(), [], [], "⚠️ Silakan unggah berkas Raw Data terlebih dahulu!"
        
    all_errs, total_records = [], 0
    detected_ssrs = set()

    for name, df_target in server_state['df_review_list']:
        total_records += len(df_target)
        df_res = jalankan_review_data(df_target, server_state['df_ref'], nama_file=name)
        if not df_res.empty:
            all_errs.append(df_res)
            detected_ssrs.update(df_res['Lembaga SSR'].unique())

    server_state['total_entri'] = total_records
    tot_data = total_records
    
    if all_errs:
        df_bawah = pd.concat(all_errs, ignore_index=True)
        tot_err = len(df_bawah)
        akurasi = max(0, 100 - (tot_err / tot_data * 100)) if tot_data > 0 else 100.0
        
        active_ssrs = sorted(list(detected_ssrs))
        DAFTAR_INDIKATOR_AKTIF = [r["nama"] for r in (ATURAN_VALIDASI_BAWAAN + st.session_state['aturan_kustom'])]
        
        matrix_rows = []
        for ind in DAFTAR_INDIKATOR_AKTIF:
            r_dict = {"INDIKATOR KESALAHAN DATA": ind}
            total_ind_err = sum(len(df_bawah[(df_bawah['INDIKATOR KESALAHAN DATA'] == ind) & (df_bawah['Lembaga SSR'] == ssr)]) for ssr in active_ssrs)
            r_dict["Jumlah per indikator"] = total_ind_err
            r_dict["%"] = (total_ind_err / tot_err * 100) if tot_err > 0 else 0.0
            for ssr in active_ssrs: r_dict[ssr] = len(df_bawah[(df_bawah['INDIKATOR KESALAHAN DATA'] == ind) & (df_bawah['Lembaga SSR'] == ssr)])
            matrix_rows.append(r_dict)
            
        df_atas = pd.DataFrame(matrix_rows)
        df_atas = df_atas[df_atas['Jumlah per indikator'] > 0].reset_index(drop=True)
        
        server_state['df_tabel_atas'] = df_atas
        server_state['df_tabel_bawah'] = df_bawah
        
        matriks_data = df_atas.to_dict('records')
        matriks_cols = [{'name': i, 'id': i} for i in df_atas.columns]
        
        detail_data = df_bawah.to_dict('records')
        detail_cols = [{'name': i, 'id': i, 'editable': (i in ['Pilih', 'Justifikasi'])} for i in df_bawah.columns]
        
        # Grafik Tren
        fig = go.Figure()
        df_tren = ambil_rekap_tren()
        if not df_tren.empty:
            df_pivot = df_tren.pivot_table(index='periode', columns='indikator_kesalahan', values='jumlah_kesalahan', aggfunc='sum', fill_value=0)
            for col in df_pivot.columns:
                fig.add_trace(go.Scatter(x=df_pivot.index, y=df_pivot[col], mode='lines', name=col, fill='tozeroy'))
        fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#cbd5e1", legend=dict(bgcolor="rgba(0,0,0,0)"))
        
        return f"{tot_data:,}", f"{tot_err:,}", f"{akurasi:.1f}%", matriks_data, matriks_cols, fig, detail_data, detail_cols, "✅ Validasi selesai!"
    else:
        return f"{tot_data:,}", "0", "100%", [], [], go.Figure(), [], [], "✨ Data bersih!"

# ==========================================================
# CALLBACKS: SIMPAN PROGRES & ARSIP
# ==========================================================
@callback(
    Output('status-save', 'children'),
    Input('btn-simpan', 'n_clicks'),
    State('tabel-detail', 'data'),
    prevent_initial_call=True
)
def save_progress(n_clicks, table_data):
    if not table_data: return "ℹ️ Tidak ada data."
    list_log_db = []
    for row in table_data:
        ind_text = str(row.get('INDIKATOR KESALAHAN DATA', ''))
        text_justifikasi = str(row.get('Justifikasi', '')).strip()
        is_konfirmasi = "konfirmasi" in ind_text.lower()
        is_pilih = bool(row.get('Pilih', False))
        
        if is_pilih or (is_konfirmasi and text_justifikasi not in ["", "None"]):
            list_log_db.append((
                str(row.get('Lembaga SSR', '')), str(row.get('Tanggal', '')), str(row.get('ID Klien', '')),
                ind_text, is_pilih, text_justifikasi if is_konfirmasi else ""
            ))
            
    if list_log_db:
        if simpan_log_ke_neon(list_log_db): return f"🎉 Berhasil menyimpan {len(list_log_db)} baris!"
        return "❌ Gagal menyimpan."
    return "ℹ️ Tidak ada data yang diproses."

@callback(
    Output('status-arsip', 'children'),
    Input('btn-arsip', 'n_clicks'),
    prevent_initial_call=True
)
def arsip_tren(n_clicks):
    if jalankan_agregasi_tren(): return "🎉 Data berhasil diarsipkan!"
    return "❌ Gagal memproses arsip."

# ==========================================================
# CALLBACKS: MEDIOS
# ==========================================================
@callback(
    Output('list-medsos', 'children'),
    [Input('btn-tambah-medsos', 'n_clicks'), Input('menu-navigasi', 'value')],
    State('input-medsos', 'value'),
    prevent_initial_call=True
)
def manage_medsos(n_clicks, menu, nilai_medsos):
    if ctx.triggered_id == 'btn-tambah-medsos' and nilai_medsos:
        tambah_keyword_medsos(nilai_medsos.lower())
        
    list_medsos = ambil_keyword_medsos()
    st.session_state['medsoc_keywords'] = list_medsos
    
    return [
        html.Span(f"🔹 {m}", style={
            'backgroundColor': 'rgba(56, 189, 248, 0.15)', 'color': '#38bdf8',
            'border': '1px solid rgba(56, 189, 248, 0.3)', 'padding': '6px 12px',
            'borderRadius': '20px', 'fontSize': '0.85rem', 'fontWeight': '500'
        }) for m in list_medsos
    ]

# ==========================================================
# RENDER KONTEN DINAMIS (DIPANGGIL SAAT APP START)
# ==========================================================
@app.callback(
    [Output('sidebar-dashboard-controls', 'children'),
     Output('main-dashboard-content', 'children'),
     Output('sidebar-medsos-controls', 'children'),
     Output('main-medsos-content', 'children')],
    Input('menu-navigasi', 'value')
)
def render_content(menu):
    # Sidebar Dashboard
    sidebar_dash = html.Div([
        html.H5("📁 MANAJEMEN BERKAS", style={'color': '#38bdf8', 'fontSize': '0.95rem'}),
        html.P("Data HIV+ Semester Lalu (.xlsx)", style={'color': '#cbd5e1', 'fontSize': '0.9rem'}),
        dcc.Upload(id='upload-ref-data', children=html.Div(['Drag & Drop atau ', html.A('Pilih File')], style={'color': '#38bdf8'}),
                   style={'width': '100%', 'height': '60px', 'lineHeight': '60px', 'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px', 'textAlign': 'center', 'margin': '10px 0', 'background': 'rgba(255,255,255,0.05)'}, multiple=False),
        html.Div(id='upload-status-ref', style={'fontSize': '0.8rem', 'color': '#94a3b8'}),
        dbc.Button("🔄 Update Database Referensi", id="btn-update-ref", color="secondary", className="w-100 mt-2 mb-3", size="sm"),
        
        html.P("Raw Data Penjangkauan (Multi-File)", style={'color': '#cbd5e1', 'fontSize': '0.9rem'}),
        dcc.Upload(id='upload-raw-data', children=html.Div(['Drag & Drop atau ', html.A('Pilih Raw Data')], style={'color': '#38bdf8'}),
                   style={'width': '100%', 'height': '60px', 'lineHeight': '60px', 'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px', 'textAlign': 'center', 'margin': '10px 0', 'background': 'rgba(255,255,255,0.05)'}, multiple=True),
        html.Div(id='upload-status-raw', style={'fontSize': '0.8rem', 'color': '#94a3b8'}),
        
        html.Hr(style={'borderColor': 'rgba(255,255,255,0.1)', 'margin': '20px 0'}),
        html.H5("⚙️ PARAMETER VALIDASI", style={'color': '#38bdf8', 'fontSize': '0.95rem'}),
        dbc.Card([
            dbc.CardBody([
                html.P("✨ Buat Aturan Kustom", style={'fontWeight': 'bold', 'color': '#f8fafc'}),
                dbc.Input(id='input-nama-ind', placeholder="Nama Indikator", className="mb-2"),
                dbc.Select(id='select-kolom', options=[{"label": k, "value": k} for k in ["NIK", "ID Klien", "Umur", "Lembaga SSR", "Kode Petugas", "Lokasi Outreach / Jenis Sosial Media", "Informasi Yang diberikan", "Rujukan"]], className="mb-2"),
                dbc.Select(id='select-kondisi', options=[{"label": k, "value": k} for k in ["Panjang karakter tidak sama dengan (!=)", "Panjang karakter kurang dari ( < )", "Kosong / Blank", "Mengandung teks tertentu", "Sama dengan teks/angka tertentu"]], className="mb-2"),
                dbc.Input(id='input-pembanding', placeholder="Nilai Pembanding", className="mb-2"),
                dbc.Button("➕ Daftarkan Aturan", id="btn-tambah-aturan", color="primary", className="w-100")
            ])
        ], className="glass-card mt-3", style={'padding': '1rem'}),
        html.Div(id='list-aturan-aktif', className="mt-3"),
        html.Hr(style={'borderColor': 'rgba(255,255,255,0.1)', 'margin': '20px 0'}),
        dbc.Button("🚀 Jalankan Penelaahan", id="btn-jalankan", color="primary", className="w-100 mt-3", size="lg"),
        html.Div(id='status-proses', className="mt-3 text-center")
    ])

    # Main Dashboard
    main_dash = html.Div([
        dbc.Row([
            dbc.Col(dbc.Card([html.P("Total Data Diproses", className="metric-label"), html.H2(id="metric-total-data", className="metric-value")], className="glass-card"), width=4),
            dbc.Col(dbc.Card([html.P("Total Temuan", className="metric-label"), html.H2(id="metric-total-temuan", className="metric-value")], className="glass-card"), width=4),
            dbc.Col(dbc.Card([html.P("Tingkat Akurasi", className="metric-label"), html.H2(id="metric-akurasi", className="metric-value")], className="glass-card"), width=4),
        ], className="mb-4"),
        
        dcc.Tabs([
            dcc.Tab(label='📋 Rekap Kesalahan (Matriks)', children=[
                html.Div([dash_table.DataTable(id='tabel-matriks', page_size=15)], className="glass-card mt-4")
            ]),
            dcc.Tab(label='📈 Analisis Tren Semester', children=[
                html.Div([dcc.Graph(id='grafik-tren', style={'backgroundColor': 'transparent'})], className="glass-card mt-4")
            ])
        ]),
        
        html.H3("🔍 Hasil Review Penjangkauan", className="mt-4", style={'color': '#f8fafc'}),
        html.Div([
            dash_table.DataTable(id='tabel-detail', editable=True, page_size=15, style_table={'maxHeight': '600px', 'overflowY': 'scroll'}),
            dbc.Row([
                dbc.Col(dbc.Button("💾 Simpan Progres", id="btn-simpan", color="secondary", className="w-100 mt-3"), width=4),
                dbc.Col(html.Div(id="status-save", className="mt-3"), width=8)
            ])
        ], className="glass-card mt-3"),
        
        html.H3("⚙️ Manajemen Akhir Periode", className="mt-4", style={'color': '#f8fafc'}),
        dbc.Alert("⚠️ Gunakan tombol ini HANYA JIKA periode bulanan sudah selesai.", color="warning", style={'backgroundColor': 'rgba(255, 193, 7, 0.1)', 'borderColor': 'rgba(255, 193, 7, 0.3)', 'color': '#ffc107'}),
        dbc.Button("🚀 Tutup Periode & Arsipkan", id="btn-arsip", color="primary", className="w-100 mt-2"),
        html.Div(id="status-arsip", className="mt-2 text-center")
    ])

    # Sidebar Medsos
    sidebar_medsos = html.Div([
        html.H5("⚙️ MEDSOS SETTINGS", style={'color': '#38bdf8'}),
        html.P("Kelola keyword media sosial untuk validasi lokasi outreach.", style={'color': '#94a3b8', 'fontSize': '0.9rem'})
    ])

    # Main Medsos
    main_medsos = html.Div([
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    html.H4("➕ Tambah Medsos Baru", style={'color': '#f8fafc'}),
                    dbc.Input(id="input-medsos", placeholder="Contoh: grindr", className="mb-3"),
                    dbc.Button("Simpan Keyword", id="btn-tambah-medsos", color="primary", className="w-100")
                ], className="glass-card")
            ], width=5),
            dbc.Col([
                dbc.Card([
                    html.H4("📋 Daftar Keyword Aktif", style={'color': '#f8fafc'}),
                    html.Div(id="list-medsos", style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'padding': '15px', 'border': '1px solid rgba(255,255,255,0.1)', 'borderRadius': '8px', 'backgroundColor': 'rgba(0,0,0,0.2)'})
                ], className="glass-card")
            ], width=7)
        ])
    ])

    return sidebar_dash, main_dash, sidebar_medsos, main_medsos

if __name__ == '__main__':
    app.run_server(debug=True, port=8050)
