import streamlit as st
import pandas as pd
import requests
import time
import altair as alt  # Library bawaan Streamlit untuk grafik interaktif tingkat lanjut

# Konfigurasi Tampilan Halaman Web (Responsif untuk HP)
st.set_page_config(page_title="OSRS F2P Dip Bot", layout="centered")

st.title("📊 OSRS F2P Dip Trading Bot")
st.write("Sinyal *trading* otomatis khusus F2P berbasis analisis penurunan harga (*price dip*) + Grafik Indikator Masuk/Keluar.")

# ==========================================
# LOGIKA WAKTU & WARNA TOMBOL (KUNING / HIJAU)
# ==========================================
if 'last_update' not in st.session_state:
    st.session_state['last_update'] = time.time()

current_time = time.time()
is_outdated = (current_time - st.session_state['last_update']) > 60

if is_outdated:
    btn_bg = "#ffcc00"       # Kuning
    btn_text_color = "black"
    btn_hover = "#e6b800"
    btn_label = "⚠️ Data Outdated - Pindai Ulang"
else:
    btn_bg = "#28a745"       # Hijau
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
total_modal = st.sidebar.number_input(
    "Masukkan Total Modal Anda (GP):", 
    min_value=1000, 
    value=100000,  # Default modal 100k
    step=5000,
    format="%d",
    help="Modal ini akan dibagi rata ke 3 slot aktif Grand Exchange."
)

modal_per_slot = total_modal / 3
st.sidebar.info(f"💰 Modal per Slot (3 Slot): **{modal_per_slot:,.0f} GP**")

# Fungsi untuk mengambil data pasar dari API Wiki
@st.cache_data(ttl=60)
def fetch_market_data():
    headers = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
    try:
        req_map = requests.get('https://prices.runescape.wiki/api/v1/osrs/mapping', headers=headers)
        df_map = pd.DataFrame(req_map.json())[['id', 'name', 'limit', 'members']]
        df_map = df_map[df_map['members'] == False]
        df_map.rename(columns={'name': 'mappingname', 'limit': 'mappinglimit'}, inplace=True)

        req_1h = requests.get('https://prices.runescape.wiki/api/v1/osrs/1h', headers=headers)
        df_1h = pd.DataFrame.from_dict(req_1h.json()['data'], orient='index').reset_index()
        df_1h.rename(columns={'index': 'id', 'avgLowPrice': 'Hourly_Low', 'lowPriceVolume': 'H_VolLow'}, inplace=True)

        req_24h = requests.get('https://prices.runescape.wiki/api/v1/osrs/24h', headers=headers)
        df_24h = pd.DataFrame.from_dict(req_24h.json()['data'], orient='index').reset_index()
        df_24h.rename(columns={'index': 'id', 'avgLowPrice': 'Daily_Low', 'avgHighPrice': 'Daily_High', 'lowPriceVolume': 'D_VolLow'}, inplace=True)

        req_latest = requests.get('https://prices.runescape.wiki/api/v1/osrs/latest', headers=headers)
        df_latest = pd.DataFrame.from_dict(req_latest.json()['data'], orient='index').reset_index()
        df_latest.rename(columns={'index': 'id', 'low': 'Live_Low', 'high': 'Live_High'}, inplace=True)

        for df in [df_1h, df_24h, df_latest, df_map]:
            df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)

        master = df_1h.merge(df_24h, on='id').merge(df_latest, on='id').merge(df_map, on='id', how='inner')
        
        for col in ['Hourly_Low', 'Live_Low', 'Daily_Low', 'Daily_High', 'D_VolLow', 'H_VolLow', 'mappinglimit']:
            if col in master.columns:
                master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)

        master['Tax'] = master['Hourly_Low'].apply(lambda x: 0 if x < 100 else round((x * 0.02) - 0.5))
        return master
    except Exception as e:
        st.error(f"Gagal mengambil data API: {e}")
        return pd.DataFrame()

# Tombol Eksekusi
if st.sidebar.button(btn_label):
    fetch_market_data.clear()
    st.session_state['last_update'] = time.time()
    st.rerun()

# Ambil data pasar utama
with st.spinner('Memindai pasar untuk mencari barang laku...'):
    master_data = fetch_market_data()

if not master_data.empty:
    
    # Fungsi pemroses sinyal
    def process_signals(df, threshold_multiplier, min_d_vol, min_h_vol, max_d_vol=float('inf'), sort_by_volume_score=False):
        filtered = df[
            (df['Live_Low'] > 0) & 
            (df['Hourly_Low'] > (df['Live_Low'] * threshold_multiplier)) & 
            (((df['Daily_Low'] + df['Daily_High']) / 2.0) > df['Live_Low']) & 
            ((df['Hourly_Low'] - df['Live_Low'] - df['Tax']) > 0) & 
            (df['D_VolLow'] >= min_d_vol) & 
            (df['D_VolLow'] <= max_d_vol) & 
            (df['H_VolLow'] >= min_h_vol) & 
            (df['Daily_High'] > df['Daily_Low'])
        ].copy()

        if filtered.empty:
            return pd.DataFrame()

        filtered['Untung_Per_Biji'] = filtered['Hourly_Low'] - filtered['Live_Low'] - filtered['Tax']
        
        def safe_calc_qty(row):
            price = row['Live_Low']
            limit = row['mappinglimit']
            if price <= 0:
                return 0
            max_afford = modal_per_slot / price
            if limit > 0:
                return int(min(limit, max_afford))
            return int(max_afford)

        filtered['Beli_Berapa_Biji'] = filtered.apply(safe_calc_qty, axis=1)
        filtered = filtered[filtered['Beli_Berapa_Biji'] > 0].copy()
        
        if filtered.empty:
            return pd.DataFrame()

        filtered['Total_Untung_Slot'] = filtered['Untung_Per_Biji'] * filtered['Beli_Berapa_Biji']
        filtered['ROI_Persen'] = (filtered['Untung_Per_Biji'] / filtered['Live_Low']) * 100
        
        if sort_by_volume_score:
            filtered['Skor'] = filtered['Untung_Per_Biji'] * filtered['D_VolLow']
            result = filtered.sort_values(by='Skor', ascending=False).head(3)
        else:
            result = filtered.sort_values(by='Total_Untung_Slot', ascending=False).head(3)
        
        result = result.rename(columns={
            'mappingname': 'Nama Barang',
            'Live_Low': 'Harga Beli',
            'Hourly_Low': 'Harga Jual',
            'Beli_Berapa_Biji': 'Jml Beli',
            'Total_Untung_Slot': 'Pr. Untung',
            'ROI_Persen': 'ROI (%)',
            'D_VolLow': 'Vol Harian'
        })
        
        return result[['Nama Barang', 'Harga Beli', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']]

    # ==========================================
    # TAMPILAN 1: JACKPOT (> 5% Anjlok, Vol < 100)
    # ==========================================
    st.subheader("🎯 Tabel 1: JACKPOT! Barang Sepi Anjlok Ekstrem (> 5%)")
    df_jackpot = process_signals(master_data, threshold_multiplier=1.05, min_d_vol=1, min_h_vol=0, max_d_vol=100, sort_by_volume_score=False)
    if not df_jackpot.empty:
        st.success("🚨 ADA BARANG JACKPOT! Segera pasang Buy Offer sebelum keduluan pemain lain!")
        st.dataframe(df_jackpot, use_container_width=True)
    else:
        st.info("Sedang tidak ada barang ber-volume rendah yang 'panic sell' saat ini.")

    st.divider()

    # ==========================================
    # TAMPILAN 2: ANJLOK TAJAM (> 2% Anjlok)
    # ==========================================
    st.subheader("🔥 Tabel 2: Anjlok Tajam (> 2%)")
    df_tajam = process_signals(master_data, threshold_multiplier=1.02, min_d_vol=500, min_h_vol=5, sort_by_volume_score=False)
    if not df_tajam.empty:
        st.dataframe(df_tajam, use_container_width=True)
    else:
        st.warning("Tidak ada item F2P yang anjlok di atas 2% saat ini.")

    st.divider()

    # ==========================================
    # TAMPILAN 3: LONGGAR (> 0.5% Anjlok + Super Laris)
    # ==========================================
    st.subheader("⚡ Tabel 3: Turun Tipis tapi Super Laris (> 0.5%)")
    df_laris = process_signals(master_data, threshold_multiplier=1.005, min_d_vol=1500, min_h_vol=15, sort_by_volume_score=True)
    if not df_laris.empty:
        st.dataframe(df_laris, use_container_width=True)
    else:
        st.warning("Tidak ada item super laris yang memenuhi kriteria saat ini.")

    st.divider()

    # ==========================================
    # FITUR GRAFIK + INDIKATOR SARAN BELI & JUAL (2% THRESHOLD)
    # ==========================================
    st.header("📈 Analisis Grafik + Indikator Masuk & Keluar")
    st.write("Grafik interaktif ini memetakan riwayat harga sekaligus memberikan **Tanda Segitiga** otomatis berbasis algoritma *2% Dip Threshold*.")

    daftar_item = master_data.sort_values(by='mappingname')[['id', 'mappingname']].drop_duplicates()
    
    col1, col2 = st.columns([3, 1])
    with col1:
        pilihan_nama = st.selectbox("Pilih Barang F2P:", daftar_item['mappingname'].tolist(), index=0)
    with col2:
        rentang_waktu = st.selectbox("Interval:", ["5m", "1h", "6h", "24h"], index=1, help="5m=5 menit, 1h=1 jam, 6h=6 jam, 24h=1 hari")

    id_terpilih = daftar_item[daftar_item['mappingname'] == pilihan_nama]['id'].values[0]

    @st.cache_data(ttl=180)
    def fetch_chart_data(item_id, timestep):
        headers = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
        url = f"https://prices.runescape.wiki/api/v1/osrs/timeseries?timestep={timestep}&id={item_id}"
        try:
            res = requests.get(url, headers=headers).json()
            if 'data' in res and len(res['data']) > 0:
                df_chart = pd.DataFrame(res['data'])
                df_chart['Waktu'] = pd.to_datetime(df_chart['timestamp'], unit='s')
                df_chart['avgLowPrice'] = df_chart['avgLowPrice'].ffill().bfill()
                df_chart['avgHighPrice'] = df_chart['avgHighPrice'].ffill().bfill()
                return df_chart
        except Exception:
            pass
        return pd.DataFrame()

    with st.spinner(f"Memuat grafik untuk {pilihan_nama}..."):
        df_chart = fetch_chart_data(id_terpilih, rentang_waktu)

    if not df_chart.empty and 'avgLowPrice' in df_chart.columns:
        
        # --- LOGIKA PENENTUAN TITIK BELI (DIP 2%) & TITIK JUAL ---
        # 1. Hitung Moving Average (Rata-rata bergerak) 6 periode sebelumnya sebagai acuan normal
        df_chart['MA_Low'] = df_chart['avgLowPrice'].rolling(window=6, min_periods=1).mean()
        df_chart['MA_High'] = df_chart['avgHighPrice'].rolling(window=6, min_periods=1).mean()
        
        # 2. 🟢 Saran Beli: Ketika harga beli jatuh >= 2% dari rata-rata pergerakan sebelumnya
        df_chart['Saran_Beli'] = df_chart.apply(
            lambda row: row['avgLowPrice'] if row['avgLowPrice'] < (row['MA_Low'] / 1.02) else None, axis=1
        )
        
        # 3. 🔴 Saran Jual: Ketika harga jual melonjak >= 1.5% di atas rata-rata (Take Profit!)
        df_chart['Saran_Jual'] = df_chart.apply(
            lambda row: row['avgHighPrice'] if row['avgHighPrice'] > (row['MA_High'] * 1.015) else None, axis=1
        )

        # --- PEMBUATAN GRAFIK ALTAIR BERLAPIS (LAYERED CHART) ---
        # A. Garis Harga Beli (Biru)
        line_low = alt.Chart(df_chart).mark_line(color='#00a8ff', strokeWidth=2).encode(
            x=alt.X('Waktu:T', title='Waktu'),
            y=alt.Y('avgLowPrice:Q', title='Harga (GP)', scale=alt.Scale(zero=False)), # zero=False agar auto-zoom!
            tooltip=[
                alt.Tooltip('Waktu:T', title='Waktu', format='%H:%M'),
                alt.Tooltip('avgLowPrice:Q', title='Harga Beli', format=',.0f'),
                alt.Tooltip('avgHighPrice:Q', title='Harga Jual', format=',.0f')
            ]
        )
        
        # B. Garis Harga Jual (Merah/Orange)
        line_high = alt.Chart(df_chart).mark_line(color='#e84118', strokeWidth=2).encode(
            x='Waktu:T',
            y='avgHighPrice:Q'
        )

        # C. Tanda Segitiga Hijau (Saran Beli)
        points_buy = alt.Chart(df_chart.dropna(subset=['Saran_Beli'])).mark_point(
            shape='triangle-up', size=180, color='#00e676', filled=True, opacity=1
        ).encode(
            x='Waktu:T',
            y='Saran_Beli:Q',
            tooltip=[
                alt.Tooltip('Waktu:T', title='Waktu Beli', format='%H:%M'),
                alt.Tooltip('Saran_Beli:Q', title='🟢 SARAN BELI (Anjlok >2%)', format=',.0f')
            ]
        )

        # D. Tanda Segitiga Merah (Saran Jual)
        points_sell = alt.Chart(df_chart.dropna(subset=['Saran_Jual'])).mark_point(
            shape='triangle-down', size=180, color='#ff1744', filled=True, opacity=1
        ).encode(
            x='Waktu:T',
            y='Saran_Jual:Q',
            tooltip=[
                alt.Tooltip('Waktu:T', title='Waktu Jual', format='%H:%M'),
                alt.Tooltip('Saran_Jual:Q', title='🔴 SARAN JUAL (Take Profit)', format=',.0f')
            ]
        )

        # Gabungkan semua garis dan titik segitiga menjadi 1 grafik interaktif
        chart_final = alt.layer(line_low, line_high, points_buy, points_sell).interactive()
        
        # Tampilkan grafik ke layar HP
        st.altair_chart(chart_final, use_container_width=True)
        
        # Panduan Eksekusi Visual
        st.markdown("""
        💡 **Cara Membaca Indikator di Grafik:**
        * 🟢 **Segitiga Hijau Menunjuk ke Atas:** Sinyal **BUY!** Ini menandakan pada jam tersebut harga barang terdeteksi anjlok tajam $\ge 2\%$ di bawah rata-rata. Pasang *Buy Offer* di kisaran harga ini.
        * 🔴 **Segitiga Merah Menunjuk ke Bawah:** Sinyal **SELL / TAKE PROFIT!** Harga sudah memantul naik ke titik puncaknya. Jika Anda sudah memegang barangnya, pasang *Sell Offer* di sekitar harga ini.
        * 👆 *Tips HP:* Anda bisa sentuh/klik tepat di tanda segitiga tersebut untuk melihat nominal harga persisnya!
        """)
    else:
        st.warning(f"Belum ada data grafik historis yang cukup untuk barang **{pilihan_nama}** pada interval waktu **{rentang_waktu}**.")

    st.divider()
    st.info(f"💡 Info: Perhitungan menggunakan total modal **{total_modal:,} GP** yang dibagi ke 3 slot GE (**{modal_per_slot:,.0f} GP per slot**).")

else:
    st.error("Gagal memuat data master pasar. Silakan klik tombol perbarui.")
