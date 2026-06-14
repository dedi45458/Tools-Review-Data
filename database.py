import os
import psycopg2
from psycopg2 import pool, extras
from psycopg2.extras import RealDictCursor
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables dari file .env
load_dotenv()

# ==========================================================
# KONFIGURASI KONEKSI DATABASE
# ==========================================================
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'pkbi_jabar_db'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', ''),
    'sslmode': os.getenv('DB_SSLMODE', 'require')
}

# Connection Pool untuk performa optimal
connection_pool = None

def initialize_pool():
    """Inisialisasi connection pool saat pertama kali dipanggil"""
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = pool.SimpleConnectionPool(
                1,  # Min connections
                20,  # Max connections
                **DB_CONFIG
            )
            print("✅ Connection pool berhasil diinisialisasi")
        except Exception as e:
            print(f"❌ Gagal inisialisasi connection pool: {e}")
            connection_pool = None

def dapatkan_koneksi_neon():
    """
    Mendapatkan koneksi dari pool atau membuat koneksi baru jika pool tidak tersedia.
    Fallback ke koneksi manual jika pool gagal.
    """
    global connection_pool
    
    # Coba gunakan pool terlebih dahulu
    if connection_pool is None:
        initialize_pool()
    
    if connection_pool:
        try:
            conn = connection_pool.getconn()
            if conn.closed == 0:
                return conn
        except Exception as e:
            print(f"⚠️ Error mendapatkan koneksi dari pool: {e}")
    
    # Fallback: Buat koneksi manual jika pool tidak tersedia
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"❌ Gagal koneksi ke database: {e}")
        return None

def kembalikan_koneksi(conn):
    """Mengembalikan koneksi ke pool"""
    global connection_pool
    if connection_pool and conn:
        try:
            connection_pool.putconn(conn)
        except:
            pass

# ==========================================================
# FUNGSI: HITUNG DAN AMBIL LOG VALIDASI
# ==========================================================
def hitung_dan_ambil_log_db():
    """
    Mengambil data log validasi dari database dan mengembalikan dua dictionary:
    1. dict_revisi: {key_db: is_revisi}
    2. dict_justifikasi: {key_db: justifikasi_text}
    """
    dict_revisi = {}
    dict_justifikasi = {}
    
    conn = dapatkan_koneksi_neon()
    if not conn:
        return dict_revisi, dict_justifikasi
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT 
                    Lembaga_SSR,
                    Tanggal,
                    ID_Klien,
                    Indikator_Kesalahan_Data,
                    is_revisi,
                    Justifikasi
                FROM log_validasi_review
                WHERE is_revisi = TRUE OR (Justifikasi IS NOT NULL AND Justifikasi != '')
            """)
            
            rows = cur.fetchall()
            for row in rows:
                key_db = f"{row['lembaga_ssr']}_{row['tanggal']}_{row['id_klien']}_{row['indikator_kesalahan_data']}"
                dict_revisi[key_db] = bool(row['is_revisi'])
                dict_justifikasi[key_db] = row['justifikasi'] or ""
                
        return dict_revisi, dict_justifikasi
    except Exception as e:
        print(f"❌ Error mengambil log validasi: {e}")
        return dict_revisi, dict_justifikasi
    finally:
        kembalikan_koneksi(conn)

# ==========================================================
# FUNGSI: AMBIL REKAP TREN
# ==========================================================
def ambil_rekap_tren():
    """
    Mengambil data rekap tren validasi per bulan untuk dashboard.
    Mengembalikan DataFrame dengan kolom: bulan, total_error, total_revisi, akurasi
    """
    conn = dapatkan_koneksi_neon()
    if not conn:
        return pd.DataFrame()
    
    try:
        query = """
            SELECT 
                DATE_TRUNC('month', created_at) as bulan,
                COUNT(*) as total_error,
                SUM(CASE WHEN is_revisi = TRUE THEN 1 ELSE 0 END) as total_revisi,
                ROUND(
                    (SUM(CASE WHEN is_revisi = TRUE THEN 1 ELSE 0 END)::DECIMAL / COUNT(*)) * 100, 
                    2
                ) as akurasi
            FROM log_validasi_review
            WHERE created_at >= NOW() - INTERVAL '6 months'
            GROUP BY DATE_TRUNC('month', created_at)
            ORDER BY bulan ASC
        """
        
        df = pd.read_sql_query(query, conn)
        return df
    except Exception as e:
        print(f"❌ Error mengambil rekap tren: {e}")
        return pd.DataFrame()
    finally:
        kembalikan_koneksi(conn)

# ==========================================================
# FUNGSI: JALANKAN AGREGASI TREN
# ==========================================================
def jalankan_agregasi_tren():
    """
    Menjalankan agregasi data tren dan menyimpannya ke tabel summary.
    Digunakan untuk optimasi query dashboard.
    """
    conn = dapatkan_koneksi_neon()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            # Hapus data agregasi lama
            cur.execute("DELETE FROM tren_validasi_summary")
            
            # Insert data agregasi baru
            cur.execute("""
                INSERT INTO tren_validasi_summary (
                    bulan, 
                    total_error, 
                    total_revisi, 
                    akurasi,
                    created_at
                )
                SELECT 
                    DATE_TRUNC('month', created_at) as bulan,
                    COUNT(*) as total_error,
                    SUM(CASE WHEN is_revisi = TRUE THEN 1 ELSE 0 END) as total_revisi,
                    ROUND(
                        (SUM(CASE WHEN is_revisi = TRUE THEN 1 ELSE 0 END)::DECIMAL / NULLIF(COUNT(*), 0)) * 100, 
                        2
                    ) as akurasi,
                    NOW() as created_at
                FROM log_validasi_review
                GROUP BY DATE_TRUNC('month', created_at)
            """)
            
        conn.commit()
        print("✅ Agregasi tren berhasil dijalankan")
        return True
    except Exception as e:
        conn.rollback()
        print(f"❌ Error menjalankan agregasi tren: {e}")
        return False
    finally:
        kembalikan_koneksi(conn)

# ==========================================================
# FUNGSI: KEYWORD MEDIA SOSIAL
# ==========================================================
def tambah_keyword_medsos(keyword):
    """
    Menambah keyword media sosial baru ke database.
    Mengembalikan True jika berhasil, False jika gagal.
    """
    if not keyword or not keyword.strip():
        return False
    
    conn = dapatkan_koneksi_neon()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO keyword_medsos (keyword, created_at)
                VALUES (%s, NOW())
                ON CONFLICT (keyword) DO NOTHING
            """, (keyword.strip(),))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"❌ Error menambah keyword medsos: {e}")
        return False
    finally:
        kembalikan_koneksi(conn)

def ambil_keyword_medsos():
    """
    Mengambil semua keyword media sosial aktif dari database.
    Mengembalikan list of strings.
    """
    conn = dapatkan_koneksi_neon()
    if not conn:
        return []
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT keyword 
                FROM keyword_medsos 
                WHERE is_active = TRUE 
                ORDER BY keyword ASC
            """)
            keywords = [row[0] for row in cur.fetchall()]
            return keywords
    except Exception as e:
        print(f"❌ Error mengambil keyword medsos: {e}")
        return []
    finally:
        kembalikan_koneksi(conn)

def hapus_keyword_medsos(keyword):
    """
    Menonaktifkan keyword media sosial (soft delete).
    """
    conn = dapatkan_koneksi_neon()
    if not conn:
        return False
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE keyword_medsos 
                SET is_active = FALSE, updated_at = NOW()
                WHERE keyword = %s
            """, (keyword,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"❌ Error menghapus keyword medsos: {e}")
        return False
    finally:
        kembalikan_koneksi(conn)

# ==========================================================
# FUNGSI: IMPORT DATA RUJUKAN
# ==========================================================
def import_data_rujukan(df):
    """
    Import data rujukan dari DataFrame ke tabel data_rujukan.
    Menggunakan batch insert untuk performa optimal.
    """
    if df is None or df.empty:
        return False
    
    conn = dapatkan_koneksi_neon()
    if not conn:
        return False
    
    try:
        # Bersihkan nama kolom
        df.columns = [str(c).strip() for c in df.columns]
        
        # Identifikasi kolom penting
        col_id = next((c for c in df.columns if 'ID' in c.upper() or 'KLIEN' in c.upper()), None)
        col_nik = next((c for c in df.columns if 'NIK' in c.upper()), None)
        col_ssr = next((c for c in df.columns if 'SSR' in c.upper() or 'LEMBAGA' in c.upper()), None)
        
        if not all([col_id, col_ssr]):
            print("❌ Kolom ID atau SSR tidak ditemukan di DataFrame")
            return False
        
        # Siapkan data untuk insert
        data_to_insert = []
        for _, row in df.iterrows():
            data_to_insert.append((
                str(row.get(col_id, '')).strip(),
                str(row.get(col_nik, '')).strip() if col_nik else None,
                str(row.get(col_ssr, '')).strip().upper(),
                str(row.to_dict())  # Simpan seluruh data sebagai JSON
            ))
        
        with conn.cursor() as cur:
            # Hapus data lama dari SSR yang sama
            ssr_list = list(set([row[2] for row in data_to_insert]))
            if ssr_list:
                cur.execute("""
                    DELETE FROM data_rujukan 
                    WHERE lembaga_ssr = ANY(%s)
                """, (ssr_list,))
            
            # Insert data baru
            extras.execute_batch(
                cur,
                """
                INSERT INTO data_rujukan (
                    id_klien,
                    nik,
                    lembaga_ssr,
                    data_json,
                    created_at
                ) VALUES (%s, %s, %s, %s, NOW())
                """,
                data_to_insert,
                page_size=1000
            )
        
        conn.commit()
        print(f"✅ Berhasil import {len(data_to_insert)} data rujukan")
        return True
    except Exception as e:
        conn.rollback()
        print(f"❌ Error import data rujukan: {e}")
        return False
    finally:
        kembalikan_koneksi(conn)

# ==========================================================
# FUNGSI: CLOSE ALL CONNECTIONS
# ==========================================================
def close_all_connections():
    """Menutup semua koneksi di pool. Dipanggil saat aplikasi shutdown."""
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        print("✅ Semua koneksi database telah ditutup")

# ==========================================================
# TEST KONEKSI (Untuk debugging)
# ==========================================================
def test_connection():
    """Test koneksi ke database dan tampilkan informasi"""
    conn = dapatkan_koneksi_neon()
    if not conn:
        print("❌ Gagal koneksi ke database")
        return False
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            print(f"✅ Berhasil koneksi ke database!")
            print(f"Version: {version}")
            
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables = [row[0] for row in cur.fetchall()]
            print(f"Tabel yang tersedia: {', '.join(tables) if tables else 'Belum ada tabel'}")
            
        return True
    except Exception as e:
        print(f"❌ Error test koneksi: {e}")
        return False
    finally:
        kembalikan_koneksi(conn)

if __name__ == "__main__":
    # Test koneksi saat file dijalankan langsung
    print("=" * 50)
    print("Testing Database Connection")
    print("=" * 50)
    test_connection()
