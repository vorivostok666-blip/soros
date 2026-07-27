import streamlit as st
import pandas as pd
import requests
import time
import altair as alt
import numpy as np
from common import fetch_mapping, fetch_latest, fetch_1h, fetch_24h, calc_ge_tax

# Konfigurasi Tampilan Halaman Web (Responsif untuk HP)
st.set_page_config(page_title="OSRS Global Flipping Radar", layout="centered")

st.title("⭐ OSRS Global Flipping Radar")
st.write("Sinyal *trading* otomatis untuk **SEMUA ITEM OSRS (F2P & Member)** dengan 4 Radar Terpisah & Dual Chart.")
st.caption(
    "ℹ️ Kolom **Maks Beli (BEP)** = batas harga beli tertinggi sebelum kamu balik modal (breakeven), "
    "dihitung dari Harga Jual dikurangi Pajak GE. Kalau kamu naikkan harga beli untuk mempercepat fill, "
    "jangan sampai melewati angka ini. Kolom **Status Harga** menandai seberapa lega ruang kenaikannya: "
    "🟢 Aman Dinaikkan (≥2% dari Harga Beli) · 🟡 Pas-pasan (0.5%–2%) · 🔴 Jangan Naikkan (<0.5%, nyaris tidak ada ruang)."
)
st.caption("Butuh strategi bahan mentah → barang jadi? Buka Low-Effort Processing untuk Decanting, Voidwaker, Godsword, Torva, dan lainnya.")
#if st.button("🏭 Buka Low-Effort Processing", type="primary", use_container_width=True):
    #st.switch_page("pages/1_low_effort_processing.py")

# ==========================================
# FUNGSI MENGAMBIL SEMUA ITEM DARI API WIKI (F2P + MEMBER)
# Catatan: fungsi fetch_mapping/fetch_1h/fetch_24h/fetch_latest sekarang
# ada di common.py supaya bisa dipakai bareng dengan halaman lain
# (Low-Effort Processing) tanpa duplikasi kode.
# ==========================================
@st.cache_data(ttl=60)
def fetch_market_data():
    try:
        df_map = fetch_mapping()
        df_1h = fetch_1h()
        df_24h = fetch_24h()
        df_latest = fetch_latest()

        # Gabungkan semua data berdasarkan ID
        master = df_1h.merge(df_24h, on='id').merge(df_latest, on='id').merge(df_map, on='id', how='inner')

        for col in ['Hourly_Low', 'Live_Low', 'Daily_Low', 'Daily_High', 'D_VolLow', 'H_VolLow', 'mappinglimit']:
            if col in master.columns:
                master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)

        # Hitung Pajak GE (2%, dibatasi maks 5 juta GP per item — penting sekarang
        # karena item Member bisa bernilai ratusan juta GP)
        master['Tax'] = master['Hourly_Low'].apply(calc_ge_tax)
        return master
    except Exception as e:
        st.error(f"Gagal mengambil data API: {e}")
        return pd.DataFrame()

# ==========================================
# VERIFIKASI SHOCK DIP (metodologi poignanttech.com —
# "Virtual Markets Part Four: Shocks and Dip Detection")
#
# Prinsip: dip "recency" saja (1 jam) tidak cukup, karena bisa jadi cuma
# pantulan balik dari spike (contoh kasus: Infinity Hat, Antidote++ di
# artikel aslinya). Untuk memastikan ini shock dip beneran, harga sekarang
# harus lebih rendah dari titik TERENDAH yang pernah tercatat dalam:
#   - 14 hari terakhir (granularitas per jam)  -> "biweekly floor"
#   - 30 hari terakhir (granularitas per hari) -> "monthly floor"
# Ditambah cek likuiditas (median volume > 0) supaya tidak menjebak
# barang yang jarang diperdagangkan.
# ==========================================
@st.cache_data(ttl=600)
def fetch_dip_verification(item_id):
    headers = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
    hasil = {
        'biweekly_floor': None,
        'monthly_floor': None,
        'monthly_median_vol_low': 0,
        'monthly_median_vol_high': 0,
        'daily_median_vol_low': 0,
        'daily_median_vol_high': 0,
        'error': None
    }
    num_cols = ['avgHighPrice', 'avgLowPrice', 'highPriceVolume', 'lowPriceVolume']
    errors = []

    # --- Histori per jam, ambil ~14 hari terakhir (biweekly floor) ---
    # Panggilan ini independen dari panggilan 24h di bawah — kalau salah satu
    # gagal (timeout/rate limit), yang lain tetap bisa dipakai.
    try:
        url_1h = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=1h&id={item_id}"
        resp_1h = requests.get(url_1h, headers=headers, timeout=15)
        resp_1h.raise_for_status()
        data_1h = resp_1h.json().get('data', [])
        if data_1h:
            df1h = pd.DataFrame(data_1h).tail(14 * 24)
            for c in num_cols:
                if c in df1h.columns:
                    df1h[c] = pd.to_numeric(df1h[c], errors='coerce')
            min_high = df1h['avgHighPrice'].min(skipna=True) if 'avgHighPrice' in df1h else None
            min_low = df1h['avgLowPrice'].min(skipna=True) if 'avgLowPrice' in df1h else None
            if pd.notna(min_high) and pd.notna(min_low):
                hasil['biweekly_floor'] = (min_high + min_low) / 2.0
            hasil['daily_median_vol_low'] = float(df1h['lowPriceVolume'].tail(24).median(skipna=True) or 0) if 'lowPriceVolume' in df1h else 0
            hasil['daily_median_vol_high'] = float(df1h['highPriceVolume'].tail(24).median(skipna=True) or 0) if 'highPriceVolume' in df1h else 0
        else:
            errors.append("1h: respons API kosong")
    except Exception as e:
        errors.append(f"1h: {type(e).__name__}")

    # --- Histori per hari, ambil 30 hari terakhir (monthly floor) ---
    try:
        url_24h = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep=24h&id={item_id}"
        resp_24h = requests.get(url_24h, headers=headers, timeout=15)
        resp_24h.raise_for_status()
        data_24h = resp_24h.json().get('data', [])
        if data_24h:
            df24h = pd.DataFrame(data_24h).tail(30)
            for c in num_cols:
                if c in df24h.columns:
                    df24h[c] = pd.to_numeric(df24h[c], errors='coerce')
            min_high = df24h['avgHighPrice'].min(skipna=True) if 'avgHighPrice' in df24h else None
            min_low = df24h['avgLowPrice'].min(skipna=True) if 'avgLowPrice' in df24h else None
            if pd.notna(min_high) and pd.notna(min_low):
                hasil['monthly_floor'] = (min_high + min_low) / 2.0
            hasil['monthly_median_vol_low'] = float(df24h['lowPriceVolume'].median(skipna=True) or 0) if 'lowPriceVolume' in df24h else 0
            hasil['monthly_median_vol_high'] = float(df24h['highPriceVolume'].median(skipna=True) or 0) if 'highPriceVolume' in df24h else 0
        else:
            errors.append("24h: respons API kosong")
    except Exception as e:
        errors.append(f"24h: {type(e).__name__}")

    hasil['error'] = "; ".join(errors) if errors else None
    return hasil

# ==========================================
# LOGIKA WAKTU & WARNA TOMBOL (KUNING / HIJAU)
# ==========================================
if 'last_update' not in st.session_state:
    st.session_state['last_update'] = time.time()

current_time = time.time()
is_outdated = (current_time - st.session_state['last_update']) > 60

if is_outdated:
    btn_bg = "#ffcc00"
    btn_text_color = "black"
    btn_hover = "#e6b800"
    btn_label = "⚠️ Data Outdated - Pindai Ulang"
else:
    btn_bg = "#28a745"
    btn_text_color = "white"
    btn_hover = "#218838"
    btn_label = "✅ Data Terupdate (Fresh)"

st.markdown(f"""
<style>
div[data-testid="stSidebar"] .stButton > button {{
    background-color: {btn_bg} !important;
    color: {btn_text_color} !important;
    border: 1px solid {btn_bg} !important;
    font-weight: bold;
}}
div[data-testid="stSidebar"] .stButton > button:hover {{
    background-color: {btn_hover} !important;
    border: 1px solid {btn_hover} !important;
    color: {btn_text_color} !important;
}}
</style>
""", unsafe_allow_html=True)

# ==========================================
# FITUR INPUT MODAL BEBAS OLEH PENGGUNA
# ==========================================
st.sidebar.header("⚙️ Pengaturan Modal GE")
tipe_akun = st.sidebar.radio(
    "Tipe Akun", options=["Member (8 Slot)", "F2P (3 Slot)"], index=0,
    help="Menentukan berapa banyak slot Grand Exchange aktif yang kamu punya untuk radar ini."
)
jumlah_slot = 8 if tipe_akun.startswith("Member") else 3

total_modal = st.sidebar.number_input(
    "Masukkan Total Modal Anda (GP):", 
    min_value=50000, 
    value=1500000, 
    step=100000,
    format="%d",
    help=f"Modal ini akan dibagi rata ke {jumlah_slot} slot aktif Grand Exchange."
)

modal_per_slot = total_modal / jumlah_slot
st.sidebar.info(f"💰 Modal per Slot ({jumlah_slot} Slot): **{modal_per_slot:,.0f} GP**")

st.sidebar.header("🔬 Verifikasi Shock Mendalam")
st.sidebar.caption("Berdasarkan metodologi poignanttech.com — cek dip terhadap harga terendah 14 & 30 hari terakhir, bukan cuma rata-rata 24 jam.")
aktifkan_verifikasi_dalam = st.sidebar.checkbox(
    "Aktifkan Verifikasi Historis (14/30 Hari)",
    value=True,
    help="Mengecek ulang tiap kandidat dip dari Tabel 1 & 2 terhadap harga terendah historis 14 hari (per jam) & 30 hari (per hari) via API timeseries wiki OSRS. Ini menyaring 'dip palsu' yang sebenarnya cuma pantulan balik dari spike. Menambah waktu pindai karena butuh 2 panggilan API tambahan per item."
)
max_kandidat_verifikasi = st.sidebar.number_input(
    "Maks. Kandidat Diverifikasi", min_value=5, max_value=100, value=25, step=5,
    help="Batasi jumlah item yang diverifikasi mendalam (diambil dari kandidat dengan potensi untung tertinggi) supaya pindai tidak terlalu lama & tidak membebani API wiki."
)
min_profit_total = st.sidebar.number_input(
    "Min. Profit Total per Slot (GP)", min_value=0, value=5000, step=1000,
    help="Item dengan potensi untung per slot di bawah angka ini akan disaring dari Tabel 4 (Verified Shock Dips)."
)

if st.sidebar.button(btn_label):
    fetch_market_data.clear()
    st.session_state['last_update'] = time.time()
    st.rerun()

with st.spinner('Memindai seluruh pasar OSRS (F2P & Member)...'):
    master_data = fetch_market_data()

if not master_data.empty:
    
    def apply_safety_lock(df):
        def safe_calc_qty(row):
            price = row['Live_Low']
            limit = row['mappinglimit']
            vol_harian = row['D_VolLow']
            if price <= 0: return 0
            max_afford = modal_per_slot / price
            max_vol_market = max(1.0, vol_harian * 0.03)
            valid_limits = [max_afford, max_vol_market]
            if limit > 0: valid_limits.append(limit)
            return int(max(min(valid_limits), 0))
            
        df['Beli_Berapa_Biji'] = df.apply(safe_calc_qty, axis=1)
        df = df[df['Beli_Berapa_Biji'] > 0].copy()
        df['Total_Untung_Slot'] = df['Untung_Per_Biji'] * df['Beli_Berapa_Biji']
        df['ROI_Persen'] = (df['Untung_Per_Biji'] / df['Live_Low']) * 100

        # --- Batas aman menaikkan harga beli ---
        # Kalau kamu naikkan harga beli (Live_Low) supaya order lebih cepat fill,
        # jangan sampai melewati titik breakeven ini: Harga Jual - Pajak.
        # Di atas angka ini, order tetap akan laku tapi kamu justru RUGI walau
        # sudah kena pajak GE (pajak dipotong dari sisi JUAL, bukan ditambah ke beli).
        df['Batas_Beli_Maks'] = df['Hourly_Low'] - df['Tax']
        df['Ruang_Naik_Persen'] = ((df['Batas_Beli_Maks'] - df['Live_Low']) / df['Live_Low']) * 100

        def tanda_ruang(pct):
            if pct >= 2:
                return '🟢 Aman Dinaikkan'
            elif pct >= 0.5:
                return '🟡 Pas-pasan'
            else:
                return '🔴 Jangan Naikkan'
        df['Tanda_Ruang_Naik'] = df['Ruang_Naik_Persen'].apply(tanda_ruang)

        return df

    # ==========================================
    # TABEL 1: SEMUA ITEM (ANJLOK > 2%)
    # ==========================================
    st.subheader("🔥 Tabel 1: Global — Anjlok Tajam (> 2%)")
    st.write("Semua barang (F2P & Member) di game yang sedang mengalami diskon besar dan menguntungkan:")

    df_f2p_2pct = master_data[
        (master_data['Live_Low'] > 0) & 
        (master_data['Hourly_Low'] > (master_data['Live_Low'] * 1.02)) & 
        (((master_data['Daily_Low'] + master_data['Daily_High']) / 2.0) > master_data['Live_Low']) & 
        ((master_data['Hourly_Low'] - master_data['Live_Low'] - master_data['Tax']) > 0)
    ].copy()

    if not df_f2p_2pct.empty:
        df_f2p_2pct['Untung_Per_Biji'] = df_f2p_2pct['Hourly_Low'] - df_f2p_2pct['Live_Low'] - df_f2p_2pct['Tax']
        res_f2p1 = apply_safety_lock(df_f2p_2pct).sort_values(by='Total_Untung_Slot', ascending=False)
        res_f2p1_display = res_f2p1.rename(columns={'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Hourly_Low': 'Harga Jual', 'Beli_Berapa_Biji': 'Jml Beli', 'Total_Untung_Slot': 'Pr. Untung', 'ROI_Persen': 'ROI (%)', 'D_VolLow': 'Vol Harian', 'Batas_Beli_Maks': 'Maks Beli (BEP)', 'Tanda_Ruang_Naik': 'Status Harga'})
        st.dataframe(res_f2p1_display[['Nama Barang', 'Tipe', 'Harga Beli', 'Maks Beli (BEP)', 'Status Harga', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']], use_container_width=True)
    else:
        res_f2p1 = pd.DataFrame()
        st.warning("⏳ Tidak ada item yang sedang anjlok > 2% saat ini.")

    st.divider()

    # ==========================================
    # TABEL 2: SEMUA ITEM (TURUN TIPIS 0.5% - 2%)
    # ==========================================
    st.subheader("⚡ Tabel 2: Global — Turun Tipis (0.5% - 2% / Main Cepat)")
    st.write("Semua barang (F2P & Member) berliku cepat yang sedang turun tipis — cocok untuk *scalping* kilat:")

    df_f2p_05pct = master_data[
        (master_data['Live_Low'] > 0) & 
        (master_data['Hourly_Low'] > (master_data['Live_Low'] * 1.005)) & 
        (master_data['Hourly_Low'] <= (master_data['Live_Low'] * 1.02)) & 
        (((master_data['Daily_Low'] + master_data['Daily_High']) / 2.0) > master_data['Live_Low']) & 
        ((master_data['Hourly_Low'] - master_data['Live_Low'] - master_data['Tax']) > 0)
    ].copy()

    if not df_f2p_05pct.empty:
        df_f2p_05pct['Untung_Per_Biji'] = df_f2p_05pct['Hourly_Low'] - df_f2p_05pct['Live_Low'] - df_f2p_05pct['Tax']
        res_f2p2 = apply_safety_lock(df_f2p_05pct).sort_values(by='Total_Untung_Slot', ascending=False)
        res_f2p2_display = res_f2p2.rename(columns={'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Hourly_Low': 'Harga Jual', 'Beli_Berapa_Biji': 'Jml Beli', 'Total_Untung_Slot': 'Pr. Untung', 'ROI_Persen': 'ROI (%)', 'D_VolLow': 'Vol Harian', 'Batas_Beli_Maks': 'Maks Beli (BEP)', 'Tanda_Ruang_Naik': 'Status Harga'})
        st.dataframe(res_f2p2_display[['Nama Barang', 'Tipe', 'Harga Beli', 'Maks Beli (BEP)', 'Status Harga', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']], use_container_width=True)
    else:
        res_f2p2 = pd.DataFrame()
        st.info("💡 Tidak ada item yang sedang turun tipis (0.5%-2%) saat ini.")

    st.divider()

    # ==========================================
    # TABEL 3: RADAR SULTAN & HIGH-MARGIN
    # ==========================================
    st.subheader("💎 Tabel 3: Global — Radar SULTAN & High-Margin")
    st.write("Memindai seluruh item bernilai tinggi (F2P & Member) yang memberikan **Untung ≥ 15.000 GP/biji** ATAU **Anjlok Ekstrem (> 3%)**:")

    master_data['Untung_Per_Biji'] = master_data['Hourly_Low'] - master_data['Live_Low'] - master_data['Tax']
    df_f2p_jackpot = master_data[
        (master_data['Live_Low'] > 0) & 
        (master_data['Untung_Per_Biji'] > 0) &
        (
            (master_data['Untung_Per_Biji'] >= 15000) | 
            (master_data['Hourly_Low'] > (master_data['Live_Low'] * 1.03))
        )
    ].copy()

    if not df_f2p_jackpot.empty:
        res_f2p_jack = apply_safety_lock(df_f2p_jackpot).sort_values(by='Total_Untung_Slot', ascending=False)
        res_f2p_jack = res_f2p_jack.rename(columns={'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Hourly_Low': 'Harga Jual', 'Beli_Berapa_Biji': 'Jml Beli', 'Total_Untung_Slot': 'Pr. Untung', 'ROI_Persen': 'ROI (%)', 'D_VolLow': 'Vol Harian', 'Batas_Beli_Maks': 'Maks Beli (BEP)', 'Tanda_Ruang_Naik': 'Status Harga'})
        st.success("🚨 ADA PELUANG SULTAN YANG WORTH-IT!")
        st.dataframe(res_f2p_jack[['Nama Barang', 'Tipe', 'Harga Beli', 'Maks Beli (BEP)', 'Status Harga', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']], use_container_width=True)
    else:
        st.info("💡 Sedang tidak ada barang Sultan ber-margin besar saat ini.")

    st.divider()

    # ==========================================
    # TABEL 4: VERIFIED SHOCK DIPS (Filter Historis Ketat)
    # Metodologi: poignanttech.com — "Virtual Markets Part Four:
    # Shocks and Dip Detection". Kandidat dari Tabel 1 & 2 diverifikasi
    # ulang terhadap harga TERENDAH historis 14 hari & 30 hari, plus
    # cek likuiditas, supaya dip "bekas spike" tidak lolos.
    # ==========================================
    st.subheader("🛡️ Tabel 4: Verified Shock Dips (Anti-Jebakan Spike)")
    st.write(
        "Kandidat dari Tabel 1 & 2 diverifikasi ulang terhadap harga **terendah** historis "
        "14 hari (per jam) dan 30 hari (per hari). Item hanya lolos kalau harga sekarang "
        "lebih rendah dari titik terendah historis tersebut — ini menyaring barang yang "
        "cuma 'kembali normal' setelah spike, bukan shock dip beneran."
    )

    if aktifkan_verifikasi_dalam:
        kandidat_shock = pd.concat([res_f2p1, res_f2p2], ignore_index=True)

        if not kandidat_shock.empty:
            kandidat_shock = kandidat_shock.drop_duplicates(subset='id').sort_values(
                by='Total_Untung_Slot', ascending=False
            ).head(int(max_kandidat_verifikasi))

            hasil_verifikasi = []
            log_diagnostik = []
            total_kandidat = len(kandidat_shock)
            progress_bar = st.progress(0, text="Memverifikasi histori harga...")

            for idx, (_, row) in enumerate(kandidat_shock.iterrows()):
                v = fetch_dip_verification(int(row['id']))
                progress_bar.progress(
                    (idx + 1) / total_kandidat,
                    text=f"Memverifikasi {row['mappingname']} ({idx + 1}/{total_kandidat})..."
                )
                time.sleep(0.15)  # jeda kecil antar item, biar tidak membebani/kena limit API wiki

                lolos_biweekly = (v['biweekly_floor'] is not None) and (row['Live_Low'] < v['biweekly_floor'])
                lolos_monthly = (v['monthly_floor'] is not None) and (row['Live_Low'] < v['monthly_floor'])
                lolos_likuiditas = (
                    v['monthly_median_vol_low'] > 0 and v['monthly_median_vol_high'] > 0 and
                    v['daily_median_vol_low'] > 0 and v['daily_median_vol_high'] > 0
                )
                lolos_profit_min = row['Total_Untung_Slot'] >= min_profit_total
                lolos_semua = lolos_biweekly and lolos_monthly and lolos_likuiditas and lolos_profit_min

                log_diagnostik.append({
                    'Nama Barang': row['mappingname'],
                    'Harga Skrg': row['Live_Low'],
                    'Floor 14 Hari': round(v['biweekly_floor']) if v['biweekly_floor'] is not None else None,
                    'Floor 30 Hari': round(v['monthly_floor']) if v['monthly_floor'] is not None else None,
                    '14 Hari?': '✅' if lolos_biweekly else '❌',
                    '30 Hari?': '✅' if lolos_monthly else '❌',
                    'Likuid?': '✅' if lolos_likuiditas else '❌',
                    'Profit Min?': '✅' if lolos_profit_min else '❌',
                    'Status': '🟢 LOLOS' if lolos_semua else '⛔ Gagal',
                    'Error API': v['error'] if v['error'] else '-'
                })

                if lolos_semua:
                    hasil_verifikasi.append(row)

            progress_bar.empty()

            if hasil_verifikasi:
                df_verified = pd.DataFrame(hasil_verifikasi).sort_values(by='Total_Untung_Slot', ascending=False)
                df_verified = df_verified.rename(columns={
                    'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Hourly_Low': 'Harga Jual',
                    'Beli_Berapa_Biji': 'Jml Beli', 'Total_Untung_Slot': 'Pr. Untung',
                    'ROI_Persen': 'ROI (%)', 'D_VolLow': 'Vol Harian',
                    'Batas_Beli_Maks': 'Maks Beli (BEP)', 'Tanda_Ruang_Naik': 'Status Harga'
                })
                st.success(f"✅ {len(df_verified)} item lolos verifikasi shock dip historis!")
                st.dataframe(
                    df_verified[['Nama Barang', 'Tipe', 'Harga Beli', 'Maks Beli (BEP)', 'Status Harga', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']],
                    use_container_width=True
                )
            else:
                st.info("💡 Tidak ada kandidat yang lolos verifikasi historis ketat saat ini. Coba lagi nanti, atau turunkan ambang profit minimum / naikkan jumlah kandidat di sidebar.")

            with st.expander(f"🔍 Detail Diagnostik ({total_kandidat} kandidat diperiksa) — cek di sini kalau tabel di atas kosong"):
                st.caption(
                    "Kalau kolom 'Error API' terisi untuk banyak baris, berarti tabel kosong karena masalah "
                    "koneksi/API — coba lagi nanti. Kalau 'Error API' kosong tapi tetap ❌ di kolom 14/30 Hari, "
                    "berarti memang belum ada shock dip beneran saat ini (bukan bug) — item cuma turun dalam "
                    "konteks jangka pendek, tapi belum memecahkan rekor terendah 14/30 hari."
                )
                st.dataframe(pd.DataFrame(log_diagnostik), use_container_width=True)
        else:
            st.info("💡 Tidak ada kandidat dari Tabel 1 & 2 untuk diverifikasi saat ini.")
    else:
        st.info("🔕 Verifikasi shock mendalam sedang dimatikan. Aktifkan di sidebar untuk memfilter dip palsu (bekas spike) menggunakan histori harga 14/30 hari.")

    st.divider()

    # ==========================================
    # DUAL CHART (SEMUA ITEM)
    # ==========================================
    st.header("📈 Dual Chart Analisis (Semua Item)")
    st.write("Pilih barang apa saja dari seluruh item OSRS (F2P & Member) untuk melihat grafik 5m & 1h secara bersamaan.")

    daftar_item = master_data.sort_values(by='mappingname')[['id', 'mappingname']].drop_duplicates()
    pilihan_nama = st.selectbox("Pilih Barang:", daftar_item['mappingname'].tolist(), index=0)
    id_terpilih = daftar_item[daftar_item['mappingname'] == pilihan_nama]['id'].values[0]

    @st.cache_data(ttl=180)
    def fetch_chart_data(item_id, timestep):
        headers = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep={timestep}&id={item_id}"
        try:
            res = requests.get(url, headers=headers).json()
            if 'data' in res and len(res['data']) > 0:
                df_chart = pd.DataFrame(res['data'])
                df_chart['Waktu'] = pd.to_datetime(df_chart['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Jakarta').dt.tz_localize(None)
                df_chart['avgLowPrice'] = df_chart['avgLowPrice'].ffill().bfill()
                df_chart['avgHighPrice'] = df_chart['avgHighPrice'].ffill().bfill()
                for vcol in ['lowPriceVolume', 'highPriceVolume']:
                    if vcol in df_chart.columns:
                        df_chart[vcol] = pd.to_numeric(df_chart[vcol], errors='coerce').fillna(0)
                    else:
                        df_chart[vcol] = 0
                return df_chart
        except Exception:
            pass
        return pd.DataFrame()

    def render_chart(timestep_label, timestep_code):
        st.subheader(f"⏱️ Interval: {timestep_label}")
        df_c = fetch_chart_data(id_terpilih, timestep_code)
        if not df_c.empty and len(df_c) > 10:
            df_c = df_c.sort_values('Waktu').reset_index(drop=True)
            df_c['MA_Low'] = df_c['avgLowPrice'].rolling(window=6, min_periods=1).mean()
            df_c['MA_High'] = df_c['avgHighPrice'].rolling(window=6, min_periods=1).mean()
            df_c['Saran_Beli'] = df_c.apply(lambda r: r['avgLowPrice'] if r['avgLowPrice'] < (r['MA_Low'] / 1.02) else None, axis=1)
            df_c['Saran_Jual'] = df_c.apply(lambda r: r['avgHighPrice'] if r['avgHighPrice'] > (r['MA_High'] * 1.015) else None, axis=1)

            # --- Deteksi lonjakan volume (konfirmasi shock, bukan cuma noise) ---
            # Total_Vol = gabungan volume transaksi Low + High per periode.
            # Vol_MA = rata-rata volume 6 periode SEBELUMNYA (di-shift, supaya
            # periode saat ini tidak ikut mempengaruhi baseline-nya sendiri).
            df_c['Total_Vol'] = df_c['lowPriceVolume'] + df_c['highPriceVolume']
            df_c['Vol_MA'] = df_c['Total_Vol'].rolling(window=6, min_periods=1).mean().shift(1)
            vol_now = df_c['Total_Vol'].iloc[-1]
            vol_baseline = df_c['Vol_MA'].iloc[-1]
            if pd.notna(vol_baseline) and vol_baseline > 0:
                rasio_vol = vol_now / vol_baseline
            else:
                rasio_vol = None

            test_steps = min(6, int(len(df_c) * 0.2))
            train_end = len(df_c) - test_steps
            train_d = df_c.iloc[max(0, train_end-15):train_end].copy()
            test_d = df_c.iloc[train_end:].copy()
            
            df_eval = pd.DataFrame(columns=['Waktu', 'Proyeksi_Beli', 'Proyeksi_Jual'])
            acc_l, acc_h = 0.0, 0.0
            ada_forecast = len(train_d) > 2
            if ada_forecast:
                x_tr = np.arange(len(train_d))
                p_l = np.polyfit(x_tr, train_d['avgLowPrice'], 1)
                p_h = np.polyfit(x_tr, train_d['avgHighPrice'], 1)
                x_te = np.arange(len(train_d) - 1, len(train_d) + test_steps)
                dates_c = [train_d['Waktu'].iloc[-1]] + test_d['Waktu'].tolist()
                pr_l = np.polyval(p_l, x_te)
                pr_h = np.polyval(p_h, x_te)
                df_eval = pd.DataFrame({'Waktu': dates_c, 'Proyeksi_Beli': pr_l, 'Proyeksi_Jual': pr_h})
                
                err_l = np.mean(np.abs((test_d['avgLowPrice'].values - pr_l[1:]) / test_d['avgLowPrice'].values)) * 100
                err_h = np.mean(np.abs((test_d['avgHighPrice'].values - pr_h[1:]) / test_d['avgHighPrice'].values)) * 100
                acc_l = max(0.0, 100.0 - err_l)
                acc_h = max(0.0, 100.0 - err_h)

            if ada_forecast:
                c1, c2, c3 = st.columns(3)
                c1.metric(f"🎯 Akurasi Beli ({timestep_label})", f"{acc_l:.1f}%")
                c2.metric(f"🎯 Akurasi Jual ({timestep_label})", f"{acc_h:.1f}%")
            else:
                c3 = st.columns(1)[0]

            if rasio_vol is not None:
                label_vol = "🚀 Lonjakan Volume!" if rasio_vol >= 2 else ("📈 Sedikit Naik" if rasio_vol >= 1.2 else "➖ Normal/Sepi")
                c3.metric("📊 Volume vs Rata-rata", f"{rasio_vol:.1f}x", label_vol)
            else:
                c3.metric("📊 Volume vs Rata-rata", "N/A")

            l_low = alt.Chart(df_c).mark_line(color='#00a8ff', strokeWidth=2).encode(x=alt.X('Waktu:T', title='Waktu (WIB)'), y=alt.Y('avgLowPrice:Q', title='Harga (GP)', scale=alt.Scale(zero=False)))
            l_high = alt.Chart(df_c).mark_line(color='#e84118', strokeWidth=2).encode(x='Waktu:T', y='avgHighPrice:Q')
            l_f_low = alt.Chart(df_eval).mark_line(color='#00d2d3', strokeDash=[4, 4], strokeWidth=3).encode(x='Waktu:T', y='Proyeksi_Beli:Q')
            l_f_high = alt.Chart(df_eval).mark_line(color='#ff9f43', strokeDash=[4, 4], strokeWidth=3).encode(x='Waktu:T', y='Proyeksi_Jual:Q')
            pt_buy = alt.Chart(df_c.dropna(subset=['Saran_Beli'])).mark_point(shape='triangle-up', size=160, color='#00e676', filled=True).encode(x='Waktu:T', y='Saran_Beli:Q')
            pt_sell = alt.Chart(df_c.dropna(subset=['Saran_Jual'])).mark_point(shape='triangle-down', size=160, color='#ff1744', filled=True).encode(x='Waktu:T', y='Saran_Jual:Q')

            final_chart = alt.layer(l_low, l_high, l_f_low, l_f_high, pt_buy, pt_sell).interactive()
            st.altair_chart(final_chart, use_container_width=True)

            # --- Bar chart volume (konfirmasi visual shock vs noise) ---
            st.caption("📊 Volume transaksi per periode — cari **batang yang mendadak jauh lebih tinggi** dari batang-batang di sekitarnya, itu tanda shock beneran (bandingkan posisinya dengan titik jatuhnya harga di grafik atas).")
            bar_vol = alt.Chart(df_c).mark_bar(color='#a4b0be').encode(
                x=alt.X('Waktu:T', title='Waktu (WIB)'),
                y=alt.Y('Total_Vol:Q', title='Volume (Low+High)')
            )
            line_vol_ma = alt.Chart(df_c).mark_line(color='#2f3542', strokeDash=[3, 3], strokeWidth=1.5).encode(
                x='Waktu:T', y='Vol_MA:Q'
            )
            st.altair_chart(alt.layer(bar_vol, line_vol_ma).interactive(), use_container_width=True)
        else:
            st.warning(f"Data historis tidak cukup untuk interval {timestep_label}.")

    # Tampilkan Dual Chart
    render_chart("5 Menit (Scalping / Jangka Pendek)", "5m")
    st.divider()
    render_chart("1 Jam (Macro / Tren Utama)", "1h")

    st.divider()
    st.info(f"💡 Info: Perhitungan menggunakan total modal **{total_modal:,} GP** yang dibagi ke {jumlah_slot} slot GE (**{modal_per_slot:,.0f} GP per slot**).")

else:
    st.error("Gagal memuat data master pasar. Silakan klik tombol perbarui.")
