import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import time
import altair as alt
import numpy as np
import math
from pathlib import Path
from streamlit_autorefresh import st_autorefresh

# Konfigurasi Tampilan Halaman Web (Responsif untuk HP)
st.set_page_config(page_title="OSRS Global Flipping Radar", layout="wide")

# Auto-refresh seluruh app tiap 1 menit (60.000 ms) — pas dengan cache data (ttl=60
# detik), jadi dijamin selalu dapat data BARU tiap kali refresh tanpa sia-sia nanya
# ke API lebih sering dari yang perlu.
st_autorefresh(interval=1 * 60 * 1000, key="auto_refresh_1menit")

# ==========================================
# FUNGSI BERSAMA (dulu di common.py, sekarang digabung di sini
# supaya cuma ada 1 file .py yang perlu diurus di GitHub)
# ==========================================
HEADERS = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
BASE_URL = 'https://prices.runescape.wiki/api/v1/osrs'


@st.cache_data(ttl=3600)
def fetch_mapping():
    """Mapping SEMUA item OSRS: id, nama, limit beli per 4 jam, status member."""
    req = requests.get(f'{BASE_URL}/mapping', headers=HEADERS)
    df = pd.DataFrame(req.json())[['id', 'name', 'limit', 'members']]
    df.rename(columns={'name': 'mappingname', 'limit': 'mappinglimit'}, inplace=True)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    df['mappinglimit'] = pd.to_numeric(df['mappinglimit'], errors='coerce').fillna(0)
    df['Tipe'] = df['members'].apply(lambda m: '👑 Member' if m else '🆓 F2P')
    return df


@st.cache_data(ttl=60)
def fetch_latest():
    """Harga transaksi terakhir: Live_Low (insta-sell/beli) & Live_High (insta-buy/jual)."""
    req = requests.get(f'{BASE_URL}/latest', headers=HEADERS)
    df = pd.DataFrame.from_dict(req.json()['data'], orient='index').reset_index()
    df.rename(columns={'index': 'id', 'low': 'Live_Low', 'high': 'Live_High'}, inplace=True)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    for c in ['Live_Low', 'Live_High']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


@st.cache_data(ttl=60)
def fetch_1h():
    """Rata-rata harga & volume transaksi 1 jam terakhir untuk semua item."""
    req = requests.get(f'{BASE_URL}/1h', headers=HEADERS)
    df = pd.DataFrame.from_dict(req.json()['data'], orient='index').reset_index()
    df.rename(columns={
        'index': 'id', 'avgLowPrice': 'Hourly_Low', 'avgHighPrice': 'Hourly_High',
        'lowPriceVolume': 'H_VolLow', 'highPriceVolume': 'H_VolHigh'
    }, inplace=True)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    for c in ['Hourly_Low', 'Hourly_High', 'H_VolLow', 'H_VolHigh']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


@st.cache_data(ttl=60)
def fetch_24h():
    """Rata-rata harga & volume transaksi 24 jam terakhir untuk semua item."""
    req = requests.get(f'{BASE_URL}/24h', headers=HEADERS)
    df = pd.DataFrame.from_dict(req.json()['data'], orient='index').reset_index()
    df.rename(columns={
        'index': 'id', 'avgLowPrice': 'Daily_Low', 'avgHighPrice': 'Daily_High',
        'lowPriceVolume': 'D_VolLow', 'highPriceVolume': 'D_VolHigh'
    }, inplace=True)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    for c in ['Daily_Low', 'Daily_High', 'D_VolLow', 'D_VolHigh']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


def calc_ge_tax(sell_price):
    """
    Pajak resmi Grand Exchange OSRS (per Mei 2025): 2% dari harga jual,
    dibulatkan ke bawah, dibatasi maksimal 5.000.000 GP per item.
    Item yang dijual di bawah 50 GP tidak kena pajak sama sekali.
    """
    if sell_price is None or sell_price < 50:
        return 0
    return min(math.floor(sell_price * 0.02), 5_000_000)


# ==========================================
# NAVIGASI HALAMAN (pengganti sistem folder pages/ Streamlit)
# ==========================================
st.sidebar.header("📍 Navigasi")
halaman = st.sidebar.radio(
    "Pilih Halaman:",
    ["🎯 Shock Dip Radar", "🏭 Low Effort Processing"]
)
st.sidebar.divider()

if halaman == "🎯 Shock Dip Radar":
    st.title("⭐ OSRS Global Flipping Radar")
    st.write("Sinyal *trading* otomatis untuk **SEMUA ITEM OSRS (F2P & Member)** dengan 4 Radar Terpisah & Dual Chart.")
    st.caption(
        "ℹ️ Kolom **Maks Beli (BEP)** = batas harga beli tertinggi sebelum kamu balik modal (breakeven), "
        "dihitung dari Harga Jual dikurangi Pajak GE. Kalau kamu naikkan harga beli untuk mempercepat fill, "
        "jangan sampai melewati angka ini. Kolom **Status Harga** menandai seberapa lega ruang kenaikannya: "
        "🟢 Aman Dinaikkan (≥2% dari Harga Beli) · 🟡 Pas-pasan (0.5%–2%) · 🔴 Jangan Naikkan (<0.5%, nyaris tidak ada ruang)."
    )
    st.caption("🏭 Mau lihat strategi lain? Buka halaman **Low-Effort Processing** di sidebar kiri untuk margin bahan mentah → barang jadi (Decanting, Voidwaker, Godsword, Torva, dll).")

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
    # AUTO-REFRESH (5 MENIT) & TOMBOL REFRESH MANUAL
    # ==========================================
    st.session_state['last_update'] = time.time()

    st.markdown(f"""
    <style>
    div[data-testid="stSidebar"] .stButton > button {{
        background-color: #28a745 !important;
        color: white !important;
        border: 1px solid #28a745 !important;
        font-weight: bold;
    }}
    div[data-testid="stSidebar"] .stButton > button:hover {{
        background-color: #218838 !important;
        border: 1px solid #218838 !important;
        color: white !important;
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

    st.sidebar.caption("🔄 Auto-refresh aktif — data ambil ulang otomatis tiap 1 menit.")

    # Countdown JS murni (jalan di browser, per detik) -- sengaja TIDAK pakai rerun
    # Streamlit tiap detik karena itu akan bikin seluruh app lag/flicker. Timer ini
    # otomatis restart ke 1:00 tiap kali app rerun (baik dari auto-refresh 1 menit
    # maupun klik manual), jadi selalu sinkron dengan refresh yang sesungguhnya.
    with st.sidebar:
        components.html(f"""
            <!-- nonce:{time.time()} -->
            <div style="text-align:center; font-family:sans-serif; padding:4px 0;">
                <span id="cd-label" style="font-size:0.85em; color:#888;">Refresh berikutnya dalam</span><br>
                <span id="cd-timer" style="font-size:1.6em; font-weight:bold; color:#28a745;">01:00</span>
            </div>
            <script>
                let total = 60;
                const timerEl = document.getElementById('cd-timer');
                const labelEl = document.getElementById('cd-label');
                function tick() {{
                    if (total <= 0) {{
                        timerEl.textContent = "00:00";
                        timerEl.style.color = "#dc3545";
                        labelEl.textContent = "Sedang refresh...";
                        return;
                    }}
                    const m = String(Math.floor(total / 60)).padStart(2, '0');
                    const s = String(total % 60).padStart(2, '0');
                    timerEl.textContent = m + ":" + s;
                    if (total <= 10) {{
                        timerEl.style.color = "#dc3545";
                        labelEl.textContent = "⚠️ Bersiap-siap, refresh sebentar lagi";
                    }} else {{
                        timerEl.style.color = "#28a745";
                        labelEl.textContent = "Refresh berikutnya dalam";
                    }}
                    total -= 1;
                }}
                tick();
                setInterval(tick, 1000);
            </script>
        """, height=70)

    if st.sidebar.button("🔄 Refresh Sekarang"):
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

                # --- Deteksi apakah dip SUDAH MULAI PULIH (supaya tidak kejebak beli kemahalan) ---
                # Ambil titik harga TERENDAH dalam beberapa periode terakhir (window sama seperti
                # MA), lalu cek seberapa jauh harga SEKARANG sudah naik dari titik itu. Ini pakai
                # data yang sudah ke-fetch, tidak ada panggilan API tambahan.
                window_recent = df_c.tail(6).reset_index(drop=True)
                idx_min = window_recent['avgLowPrice'].idxmin()
                titik_terendah = window_recent['avgLowPrice'].iloc[idx_min]
                waktu_terendah = window_recent['Waktu'].iloc[idx_min]
                waktu_sekarang = df_c['Waktu'].iloc[-1]
                harga_sekarang = df_c['avgLowPrice'].iloc[-1]

                if titik_terendah > 0:
                    recovery_pct = (harga_sekarang - titik_terendah) / titik_terendah * 100
                    menit_sejak_terendah = (waktu_sekarang - waktu_terendah).total_seconds() / 60
                    waktu_label = f"{menit_sejak_terendah:.0f} menit lalu" if timestep_code == '5m' else f"{menit_sejak_terendah/60:.1f} jam lalu"

                    if recovery_pct <= 0.3:
                        st.success(f"🟢 **Masih di titik terendah** (tercatat {waktu_label}) — belum terlambat, harga belum naik berarti dari dasarnya.")
                    elif recovery_pct <= 1.5:
                        st.warning(f"🟡 **Sudah mulai pulih** — harga naik {recovery_pct:.1f}% dari titik terendah ({waktu_label}). Masih ada peluang, tapi jangan ditunda lagi.")
                    else:
                        st.error(f"🔴 **Kemungkinan sudah terlambat** — harga sudah naik {recovery_pct:.1f}% dari titik terendah ({waktu_label}). Dip ini kemungkinan sudah banyak diambil orang lain.")

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

else:
    st.title("🏭 Low-Effort Processing")
    st.write(
        "Margin dari mengubah **bahan setengah jadi** (intermediate goods) menjadi **barang jadi** "
        "(final goods) lewat proses NPC yang cepat & minim usaha — decanting, crushing, repair "
        "Barrows, rakit Voidwaker/Godsword/Torva, dan lain-lain."
    )
    st.caption(
        "Metodologi mengikuti poignanttech.com — *Virtual Markets Part Five: Low-Effort Processing*. "
        "⚠️ Beda dari radar shock-dip di Home: strategi ini butuh **modal jauh lebih besar per eksekusi** "
        "(beberapa resep butuh ratusan juta GP sekali jalan), ROI per transaksi cenderung kecil, dan "
        "beberapa resep butuh syarat skill/quest tertentu — selalu cek kolom **Syarat** sebelum eksekusi."
    )

    # ==========================================
    # SYARAT PER METODE (skill/quest/area requirement)
    # ==========================================
    RECIPE_REQUIREMENTS = {
        'Decant 3 to 4 (Bob Barter)': 'Tidak ada syarat skill — NPC Bob Barter di GE, harus Member',
        'Decant 4 to 1 (Bob Barter)': 'Tidak ada syarat skill — NPC Bob Barter di GE, harus Member',
        'Create Unfinished Potions (Zahur)': 'Desert Diary (Hard) ATAU Herblore cape — NPC Zahur di gurun',
        'Create Unfinished Blood Potions (Zahur)': 'Desert Diary (Hard) ATAU Herblore cape — NPC Zahur di gurun',
        'Crushing Nihil Shards (Wesley)': 'Tidak ada syarat skill — NPC Wesley di gurun',
        'Crushing Bird Nests (Wesley)': 'Tidak ada syarat skill — NPC Wesley di gurun',
        'Crushing Kebbit Teeth (Wesley)': 'Tidak ada syarat skill — NPC Wesley di gurun',
        'Crushing Dragon Scales (Wesley)': 'Tidak ada syarat skill — NPC Wesley di gurun',
        'Crushing Unicorn Horns (Wesley)': 'Tidak ada syarat skill — NPC Wesley di gurun',
        'Crushing Goat Horns (Wesley)': 'Tidak ada syarat skill — NPC Wesley di gurun',
        'Repair Broken Armour (POH - 80 smithing)': 'Smithing 80+, armour stand di POH (rumah sendiri)',
        'Repair Broken Weapon (POH - 80 smithing)': 'Smithing 80+, armour stand di POH (rumah sendiri)',
        'Bawa Hilt+Blade+Gem & 500K GP ke Madam Sikaro': 'Tidak ada syarat skill — + biaya tetap 500.000 GP, ke Ferox Enclave',
        'Gabungkan hilt + godsword blade': 'Tidak ada syarat',
        'Anvil + Broken Armour + 1 Bandosian Component (90 smithing)': 'Smithing 90+, The Frozen Door (akses Ancient Forge)',
        'Anvil + Broken Armour + 2 Bandosian Components (90 smithing)': 'Smithing 90+, The Frozen Door (akses Ancient Forge)',
        'Gabungkan Hydra Claw + Zamorakian Hasta': 'Tidak ada syarat',
        'Gabungkan Bandos Boots + Black tourmaline core': 'Tidak ada syarat',
        'Anvil + Anti-dragon shield + Draconic Visage (90 smithing)': 'Smithing 90+',
        'Gabungkan Master Wand + Kodai insignia': 'Tidak ada syarat',
        'Uncharge Black mask (10)': 'Tidak ada syarat',
        'Gabungkan 5 Venator shards': 'Tidak ada syarat',
    }


    @st.cache_data(ttl=3600)
    def load_recipes():
        path = Path(__file__).resolve().parent / "low_effort_recipes.csv"
        return pd.read_csv(path, na_values=["null", ""])


    with st.spinner("Memuat data resep & harga pasar terkini..."):
        recipes = load_recipes()
        df_map = fetch_mapping()
        df_latest = fetch_latest()
        df_1h = fetch_1h()

    price_ref = df_map.merge(df_latest, on='id', how='left').merge(df_1h, on='id', how='left').set_index('id')


    def get_ref(item_id):
        """Ambil baris referensi harga/limit/volume untuk 1 ID barang, atau None kalau tidak ada."""
        if pd.isna(item_id):
            return None
        try:
            item_id = int(item_id)
        except (ValueError, TypeError):
            return None
        if item_id not in price_ref.index:
            return None
        row = price_ref.loc[item_id]
        if isinstance(row, pd.DataFrame):  # jaga-jaga kalau ada id duplikat
            row = row.iloc[0]
        return row


    # ==========================================
    # HITUNG EKONOMI TIAP RESEP
    # ==========================================
    hasil_rows = []
    log_diagnostik = []

    for _, r in recipes.iterrows():
        nama_produk = r['ProductName']
        tipe_resep = r['RecipeType']
        product_ref = get_ref(r['id'])

        if product_ref is None:
            log_diagnostik.append({
                'Produk': nama_produk,
                'Masalah': f"ID produk {int(r['id'])} tidak ditemukan di /mapping — kemungkinan barang sudah berubah/dihapus sejak tabel resep ini dibuat (2024)."
            })
            continue

        total_low_cost = 0.0
        limit_kandidat = []
        ingredient_detail = []
        ingredient_bermasalah = False

        for n in [1, 2, 3]:
            ing_id = r.get(f'ingredient{n}id')
            ing_qty = r.get(f'ingredient{n}Qty')
            if pd.isna(ing_id) or pd.isna(ing_qty) or ing_qty == 0:
                continue

            ing_ref = get_ref(ing_id)
            if ing_ref is None:
                log_diagnostik.append({'Produk': nama_produk, 'Masalah': f"ID bahan {int(ing_id)} tidak ditemukan di /mapping — resep dilewati."})
                ingredient_bermasalah = True
                break

            harga_bahan = ing_ref['Live_Low']
            if not harga_bahan or harga_bahan <= 0:
                log_diagnostik.append({'Produk': nama_produk, 'Masalah': f"Bahan '{ing_ref['mappingname']}' tidak ada data harga saat ini — resep dilewati."})
                ingredient_bermasalah = True
                break

            total_low_cost += harga_bahan * ing_qty

            # Batas eksekusi per 4 jam: dari buy limit (sudah per 4 jam) & volume 1 jam x 4
            buy_limit = ing_ref['mappinglimit']
            vol_1h = ing_ref['H_VolLow']
            if buy_limit and buy_limit > 0:
                limit_kandidat.append(buy_limit / ing_qty)
            if vol_1h and vol_1h > 0:
                limit_kandidat.append((vol_1h * 4) / ing_qty)

            ingredient_detail.append({
                'Bahan': ing_ref['mappingname'], 'Qty Dibutuhkan': ing_qty,
                'Harga Satuan': round(harga_bahan), 'Subtotal': round(harga_bahan * ing_qty)
            })

        if ingredient_bermasalah:
            continue

        qty_produced = r['QtyProduced'] if pd.notna(r['QtyProduced']) and r['QtyProduced'] > 0 else 1
        processing_cost = r['ProcessingCost'] if pd.notna(r['ProcessingCost']) else 0

        live_low = product_ref['Live_Low']
        live_high = product_ref['Live_High']
        if not live_low or not live_high or live_low <= 0 or live_high <= 0:
            log_diagnostik.append({'Produk': nama_produk, 'Masalah': "Produk tidak ada data harga terkini — resep dilewati."})
            continue

        # Pajak dihitung terpisah untuk skenario jual di Low vs High (lebih akurat
        # daripada memakai satu nilai pajak untuk keduanya)
        tax_low = calc_ge_tax(live_low)
        tax_high = calc_ge_tax(live_high)

        modal_per_eksekusi = total_low_cost + processing_cost
        untung_low = (qty_produced * live_low) - modal_per_eksekusi - (qty_produced * tax_low)
        untung_high = (qty_produced * live_high) - modal_per_eksekusi - (qty_produced * tax_high)

        if (untung_low + untung_high) <= 0:
            continue  # kriteria artikel: buang resep yang totalnya negatif

        maks_eksekusi_likuiditas = min(limit_kandidat) if limit_kandidat else None

        roi_persen = (untung_low / modal_per_eksekusi * 100) if modal_per_eksekusi > 0 else 0

        hasil_rows.append({
            'Produk': nama_produk,
            'Metode': tipe_resep,
            'Syarat': RECIPE_REQUIREMENTS.get(tipe_resep, 'Cek OSRS Wiki'),
            'Modal/Eksekusi': round(modal_per_eksekusi),
            'Untung/Eksekusi (Low)': round(untung_low),
            'Untung/Eksekusi (High)': round(untung_high),
            'Maks Eksekusi (Likuiditas, 4 Jam)': int(maks_eksekusi_likuiditas) if maks_eksekusi_likuiditas is not None else None,
            'ROI (%)': round(roi_persen, 1),
            '_ingredients': ingredient_detail,
            '_qty_produced': qty_produced,
        })

    df_hasil = pd.DataFrame(hasil_rows)

    # ==========================================
    # MODAL & FILTER
    # ==========================================
    st.sidebar.header("⚙️ Pengaturan Low-Effort Processing")
    modal_tersedia = st.sidebar.number_input(
        "Modal Tersedia untuk Strategi Ini (GP):", min_value=0, value=5_000_000, step=500_000, format="%d",
        help="Terpisah dari modal radar shock-dip di Home. Dipakai untuk menghitung berapa kali kamu REALISTIS bisa eksekusi resep dengan modal ini."
    )

    if not df_hasil.empty:
        df_hasil['Maks Eksekusi (Modal)'] = df_hasil['Modal/Eksekusi'].apply(
            lambda m: int(modal_tersedia // m) if m > 0 else None
        )
        df_hasil['Maks Eksekusi Realistis'] = df_hasil.apply(
            lambda row: min(x for x in [row['Maks Eksekusi (Likuiditas, 4 Jam)'], row['Maks Eksekusi (Modal)']] if x is not None)
            if (row['Maks Eksekusi (Likuiditas, 4 Jam)'] is not None or row['Maks Eksekusi (Modal)'] is not None) else 0,
            axis=1
        )
        df_hasil['Profit Realistis (Low)'] = df_hasil['Untung/Eksekusi (Low)'] * df_hasil['Maks Eksekusi Realistis']
        df_hasil['Profit Realistis (High)'] = df_hasil['Untung/Eksekusi (High)'] * df_hasil['Maks Eksekusi Realistis']
        df_hasil['Bisa Dijalankan?'] = df_hasil['Modal/Eksekusi'].apply(lambda m: '✅' if m <= modal_tersedia else '🔴 Modal Kurang')

    metode_tersedia = sorted(df_hasil['Metode'].unique().tolist()) if not df_hasil.empty else []
    metode_pilihan = st.sidebar.multiselect("Filter Kategori Resep", options=metode_tersedia, default=metode_tersedia)
    sembunyikan_modal_kurang = st.sidebar.checkbox("Sembunyikan resep yang modalnya kurang", value=False)

    st.divider()

    if df_hasil.empty:
        st.warning("Tidak ada resep yang menghasilkan margin positif saat ini.")
    else:
        df_tampil = df_hasil[df_hasil['Metode'].isin(metode_pilihan)].copy()
        if sembunyikan_modal_kurang:
            df_tampil = df_tampil[df_tampil['Bisa Dijalankan?'] == '✅']
        df_tampil = df_tampil.sort_values(by='Profit Realistis (High)', ascending=False)

        st.subheader(f"📋 {len(df_tampil)} Resep Menguntungkan Ditemukan")
        st.caption(
            "Diurutkan dari **Profit Realistis (High)** tertinggi — sudah memperhitungkan batas modal & "
            "likuiditas bahan, bukan cuma margin per unit. 'Untung/Eksekusi (Low/High)' = profit SEKALI proses "
            "kalau produk terjual di harga Low (cepat) atau High (lebih untung, lebih lama)."
        )
        st.dataframe(
            df_tampil[['Produk', 'Metode', 'Syarat', 'Bisa Dijalankan?', 'Modal/Eksekusi',
                       'Untung/Eksekusi (Low)', 'Untung/Eksekusi (High)', 'Maks Eksekusi Realistis',
                       'Profit Realistis (Low)', 'Profit Realistis (High)', 'ROI (%)']],
            use_container_width=True
        )

        st.divider()

        # ==========================================
        # DETAIL RESEP TERPILIH (rincian bahan)
        # ==========================================
        st.subheader("🔍 Rincian Bahan per Resep")
        if not df_tampil.empty:
            produk_pilihan = st.selectbox("Pilih produk untuk lihat rincian bahan:", df_tampil['Produk'].tolist())
            baris = df_hasil[df_hasil['Produk'] == produk_pilihan].iloc[0]
            st.write(f"**Metode:** {baris['Metode']} · **Syarat:** {baris['Syarat']}")
            st.write(f"1 kali eksekusi menghasilkan **{baris['_qty_produced']:g}x {produk_pilihan}**, butuh bahan:")
            st.dataframe(pd.DataFrame(baris['_ingredients']), use_container_width=True)
            c1, c2, c3 = st.columns(3)
            c1.metric("Modal per Eksekusi", f"{baris['Modal/Eksekusi']:,.0f} GP")
            c2.metric("Maks Eksekusi Realistis", f"{baris['Maks Eksekusi Realistis']:,.0f}x")
            c3.metric("Profit Realistis (High)", f"{baris['Profit Realistis (High)']:,.0f} GP")
        else:
            st.info("Tidak ada resep yang cocok dengan filter saat ini.")

    with st.expander(f"🔍 Detail Diagnostik ({len(log_diagnostik)} resep dilewati) — cek di sini kalau ada resep yang hilang"):
        st.caption(
            "Tabel resep berasal dari data yang dipublikasikan April 2024 dan tidak lagi di-update oleh penulis "
            "aslinya, jadi beberapa ID barang bisa jadi sudah berubah. Baris di sini menunjukkan resep mana yang "
            "dilewati beserta alasannya."
        )
        if log_diagnostik:
            st.dataframe(pd.DataFrame(log_diagnostik), use_container_width=True)
        else:
            st.write("Tidak ada masalah ID — semua 79 resep berhasil diproses.")
