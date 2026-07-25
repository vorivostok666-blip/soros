import streamlit as st
import pandas as pd
import requests
import time
import altair as alt
import numpy as np

# Konfigurasi Tampilan Halaman Web (Responsif untuk HP)
st.set_page_config(page_title="OSRS F2P Global Flipping Radar", layout="centered")

st.title("⭐ OSRS Global F2P Flipping Radar")
st.write("Sinyal *trading* otomatis untuk **SEMUA ITEM F2P OSRS** dengan 3 Radar Terpisah & Dual Chart (Modal 8 Juta GP).")

# ==========================================
# FUNGSI MENGAMBIL SEMUA ITEM F2P DARI API WIKI
# ==========================================
@st.cache_data(ttl=60)
def fetch_market_data():
    headers = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
    try:
        # 1. Ambil Mapping dan filter HANYA F2P (members == False)
        req_map = requests.get('https://prices.runescape.wiki/api/v1/osrs/mapping', headers=headers)
        df_map = pd.DataFrame(req_map.json())[['id', 'name', 'limit', 'members']]
        df_map = df_map[df_map['members'] == False]
        df_map.rename(columns={'name': 'mappingname', 'limit': 'mappinglimit'}, inplace=True)

        # 2. Ambil Data Harga 1h, 24h, Latest
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

        # Gabungkan semua data berdasarkan ID F2P
        master = df_1h.merge(df_24h, on='id').merge(df_latest, on='id').merge(df_map, on='id', how='inner')
        
        for col in ['Hourly_Low', 'Live_Low', 'Daily_Low', 'Daily_High', 'D_VolLow', 'H_VolLow', 'mappinglimit']:
            if col in master.columns:
                master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)

        # Hitung Pajak GE (2% untuk item di atas 100 GP)
        master['Tax'] = master['Hourly_Low'].apply(lambda x: 0 if x < 100 else round((x * 0.02) - 0.5))
        return master
    except Exception as e:
        st.error(f"Gagal mengambil data API: {e}")
        return pd.DataFrame()

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
total_modal = st.sidebar.number_input(
    "Masukkan Total Modal Anda (GP):", 
    min_value=50000, 
    value=8000000, 
    step=500000,
    format="%d",
    help="Modal ini akan dibagi rata ke 3 slot aktif Grand Exchange."
)

modal_per_slot = total_modal / 3
st.sidebar.info(f"💰 Modal per Slot (3 Slot): **{modal_per_slot:,.0f} GP**")

if st.sidebar.button(btn_label):
    fetch_market_data.clear()
    st.session_state['last_update'] = time.time()
    st.rerun()

with st.spinner('Memindai seluruh pasar F2P OSRS...'):
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
        return df

    # ==========================================
    # TABEL 1: SEMUA ITEM F2P (ANJLOK > 2%)
    # ==========================================
    st.subheader("🔥 Tabel 1: Global F2P — Anjlok Tajam (> 2%)")
    st.write("Semua barang F2P di game yang sedang mengalami diskon besar dan menguntungkan:")

    df_f2p_2pct = master_data[
        (master_data['Live_Low'] > 0) & 
        (master_data['Hourly_Low'] > (master_data['Live_Low'] * 1.02)) & 
        (((master_data['Daily_Low'] + master_data['Daily_High']) / 2.0) > master_data['Live_Low']) & 
        ((master_data['Hourly_Low'] - master_data['Live_Low'] - master_data['Tax']) > 0)
    ].copy()

    if not df_f2p_2pct.empty:
        df_f2p_2pct['Untung_Per_Biji'] = df_f2p_2pct['Hourly_Low'] - df_f2p_2pct['Live_Low'] - df_f2p_2pct['Tax']
        res_f2p1 = apply_safety_lock(df_f2p_2pct).sort_values(by='Total_Untung_Slot', ascending=False)
        res_f2p1 = res_f2p1.rename(columns={'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Hourly_Low': 'Harga Jual', 'Beli_Berapa_Biji': 'Jml Beli', 'Total_Untung_Slot': 'Pr. Untung', 'ROI_Persen': 'ROI (%)', 'D_VolLow': 'Vol Harian'})
        st.dataframe(res_f2p1[['Nama Barang', 'Harga Beli', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']], use_container_width=True)
    else:
        st.warning("⏳ Tidak ada item F2P yang sedang anjlok > 2% saat ini.")

    st.divider()

    # ==========================================
    # TABEL 2: SEMUA ITEM F2P (TURUN TIPIS 0.5% - 2%)
    # ==========================================
    st.subheader("⚡ Tabel 2: Global F2P — Turun Tipis (0.5% - 2% / Main Cepat)")
    st.write("Semua barang F2P berliku cepat yang sedang turun tipis — cocok untuk *scalping* kilat:")

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
        res_f2p2 = res_f2p2.rename(columns={'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Hourly_Low': 'Harga Jual', 'Beli_Berapa_Biji': 'Jml Beli', 'Total_Untung_Slot': 'Pr. Untung', 'ROI_Persen': 'ROI (%)', 'D_VolLow': 'Vol Harian'})
        st.dataframe(res_f2p2[['Nama Barang', 'Harga Beli', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']], use_container_width=True)
    else:
        st.info("💡 Tidak ada item F2P yang sedang turun tipis (0.5%-2%) saat ini.")

    st.divider()

    # ==========================================
    # TABEL 3: RADAR SULTAN & HIGH-MARGIN F2P
    # ==========================================
    st.subheader("💎 Tabel 3: Global F2P — Radar SULTAN & High-Margin")
    st.write("Memindai seluruh item bernilai tinggi di F2P yang memberikan **Untung ≥ 15.000 GP/biji** ATAU **Anjlok Ekstrem (> 3%)**:")

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
        res_f2p_jack = res_f2p_jack.rename(columns={'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Hourly_Low': 'Harga Jual', 'Beli_Berapa_Biji': 'Jml Beli', 'Total_Untung_Slot': 'Pr. Untung', 'ROI_Persen': 'ROI (%)', 'D_VolLow': 'Vol Harian'})
        st.success("🚨 ADA PELUANG SULTAN F2P YANG WORTH-IT!")
        st.dataframe(res_f2p_jack[['Nama Barang', 'Harga Beli', 'Harga Jual', 'Jml Beli', 'Pr. Untung', 'ROI (%)', 'Vol Harian']], use_container_width=True)
    else:
        st.info("💡 Sedang tidak ada barang Sultan F2P ber-margin besar saat ini.")

    st.divider()

    # ==========================================
    # DUAL CHART (SEMUA ITEM F2P)
    # ==========================================
    st.header("📈 Dual Chart Analisis (Semua Item F2P)")
    st.write("Pilih barang apa saja dari seluruh item F2P OSRS untuk melihat grafik 5m & 1h secara bersamaan.")

    daftar_item = master_data.sort_values(by='mappingname')[['id', 'mappingname']].drop_duplicates()
    pilihan_nama = st.selectbox("Pilih Barang F2P:", daftar_item['mappingname'].tolist(), index=0)
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

            test_steps = min(6, int(len(df_c) * 0.2))
            train_end = len(df_c) - test_steps
            train_d = df_c.iloc[max(0, train_end-15):train_end].copy()
            test_d = df_c.iloc[train_end:].copy()
            
            df_eval = pd.DataFrame(columns=['Waktu', 'Proyeksi_Beli', 'Proyeksi_Jual'])
            acc_l, acc_h = 0.0, 0.0
            if len(train_d) > 2:
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

                c1, c2 = st.columns(2)
                c1.metric(f"🎯 Akurasi Beli ({timestep_label})", f"{acc_l:.1f}%")
                c2.metric(f"🎯 Akurasi Jual ({timestep_label})", f"{acc_h:.1f}%")

            l_low = alt.Chart(df_c).mark_line(color='#00a8ff', strokeWidth=2).encode(x=alt.X('Waktu:T', title='Waktu (WIB)'), y=alt.Y('avgLowPrice:Q', title='Harga (GP)', scale=alt.Scale(zero=False)))
            l_high = alt.Chart(df_c).mark_line(color='#e84118', strokeWidth=2).encode(x='Waktu:T', y='avgHighPrice:Q')
            l_f_low = alt.Chart(df_eval).mark_line(color='#00d2d3', strokeDash=[4, 4], strokeWidth=3).encode(x='Waktu:T', y='Proyeksi_Beli:Q')
            l_f_high = alt.Chart(df_eval).mark_line(color='#ff9f43', strokeDash=[4, 4], strokeWidth=3).encode(x='Waktu:T', y='Proyeksi_Jual:Q')
            pt_buy = alt.Chart(df_c.dropna(subset=['Saran_Beli'])).mark_point(shape='triangle-up', size=160, color='#00e676', filled=True).encode(x='Waktu:T', y='Saran_Beli:Q')
            pt_sell = alt.Chart(df_c.dropna(subset=['Saran_Jual'])).mark_point(shape='triangle-down', size=160, color='#ff1744', filled=True).encode(x='Waktu:T', y='Saran_Jual:Q')

            final_chart = alt.layer(l_low, l_high, l_f_low, l_f_high, pt_buy, pt_sell).interactive()
            st.altair_chart(final_chart, use_container_width=True)
        else:
            st.warning(f"Data historis tidak cukup untuk interval {timestep_label}.")

    # Tampilkan Dual Chart
    render_chart("5 Menit (Scalping / Jangka Pendek)", "5m")
    st.divider()
    render_chart("1 Jam (Macro / Tren Utama)", "1h")

    st.divider()
    st.info(f"💡 Info: Perhitungan menggunakan total modal **{total_modal:,} GP** yang dibagi ke 3 slot GE (**{modal_per_slot:,.0f} GP per slot**).")

else:
    st.error("Gagal memuat data master pasar. Silakan klik tombol perbarui.")
