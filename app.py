import streamlit as st
import pandas as pd
import requests

# Konfigurasi Tampilan Halaman Web (Responsif untuk HP)
st.set_page_config(page_title="OSRS F2P Dip Bot", layout="centered")

st.title("📊 OSRS F2P Dip Trading Bot")
st.write("Sinyal *trading* otomatis khusus F2P berbasis analisis penurunan harga (*price dip*) dengan variasi likuiditas.")

# ==========================================
# FITUR INPUT MODAL BEBAS OLEH PENGGUNA
# ==========================================
st.sidebar.header("⚙️ Pengaturan Modal GE")
total_modal = st.sidebar.number_input(
    "Masukkan Total Modal Anda (GP):", 
    min_value=1000, 
    value=100000,  # Default modal baru Anda
    step=5000,
    format="%d",
    help="Modal ini akan dibagi rata ke 3 slot aktif Grand Exchange."
)

# Hitung modal per slot (dibagi 3 slot GE)
modal_per_slot = total_modal / 3
st.sidebar.info(f"💰 Modal per Slot (3 Slot): **{modal_per_slot:,.0f} GP**")

if st.sidebar.button("🔄 Perbarui & Pindai Pasar"):
    st.rerun()

# Fungsi untuk mengambil data pasar dari API Wiki
@st.cache_data(ttl=60)
def fetch_market_data():
    headers = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
    try:
        # 1. MAPPING
        req_map = requests.get('https://prices.runescape.wiki/api/v1/osrs/mapping', headers=headers)
        df_map = pd.DataFrame(req_map.json())[['id', 'name', 'limit', 'members']]
        df_map = df_map[df_map['members'] == False]
        df_map.rename(columns={'name': 'mappingname', 'limit': 'mappinglimit'}, inplace=True)

        # 2. 1 HOUR DATA
        req_1h = requests.get('https://prices.runescape.wiki/api/v1/osrs/1h', headers=headers)
        df_1h = pd.DataFrame.from_dict(req_1h.json()['data'], orient='index').reset_index()
        df_1h.rename(columns={'index': 'id', 'avgLowPrice': 'Hourly_Low', 'lowPriceVolume': 'H_VolLow'}, inplace=True)

        # 3. 24 HOUR DATA
        req_24h = requests.get('https://prices.runescape.wiki/api/v1/osrs/24h', headers=headers)
        df_24h = pd.DataFrame.from_dict(req_24h.json()['data'], orient='index').reset_index()
        df_24h.rename(columns={'index': 'id', 'avgLowPrice': 'Daily_Low', 'avgHighPrice': 'Daily_High', 'lowPriceVolume': 'D_VolLow'}, inplace=True)

        # 4. LATEST DATA
        req_latest = requests.get('https://prices.runescape.wiki/api/v1/osrs/latest', headers=headers)
        df_latest = pd.DataFrame.from_dict(req_latest.json()['data'], orient='index').reset_index()
        df_latest.rename(columns={'index': 'id', 'low': 'Live_Low', 'high': 'Live_High'}, inplace=True)

        # Ubah ID menjadi integer yang aman
        for df in [df_1h, df_24h, df_latest, df_map]:
            df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)

        # Gabungkan semua data
        master = df_1h.merge(df_24h, on='id').merge(df_latest, on='id').merge(df_map, on='id', how='inner')
        
        # Bersihkan data NaN
        for col in ['Hourly_Low', 'Live_Low', 'Daily_Low', 'Daily_High', 'D_VolLow', 'H_VolLow', 'mappinglimit']:
            if col in master.columns:
                master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)

        # Hitung Pajak
        master['Tax'] = master['Hourly_Low'].apply(lambda x: 0 if x < 100 else round((x * 0.02) - 0.5))
        return master
    except Exception as e:
        st.error(f"Gagal mengambil data API: {e}")
        return pd.DataFrame()

# Ambil data pasar
with st.spinner('Memindai pasar untuk mencari barang laku...'):
    master_data = fetch_market_data()

if not master_data.empty:
    
    # Tambahan parameter min_h_vol agar volume jam-jaman bisa disesuaikan
    def process_signals(df, threshold_multiplier, min_d_vol, min_h_vol, sort_by_volume_score=False):
        filtered = df[
            (df['Live_Low'] > 0) & 
            (df['Hourly_Low'] > (df['Live_Low'] * threshold_multiplier)) & 
            (((df['Daily_Low'] + df['Daily_High']) / 2.0) > df['Live_Low']) & 
            ((df['Hourly_Low'] - df['Live_Low'] - df['Tax']) > 0) & 
            (df['D_VolLow'] >= min_d_vol) & 
            (df['H_VolLow'] >= min_h_vol) & 
            (df['Daily_High'] > df['Daily_Low'])
        ].copy()

        if filtered.empty:
            return pd.DataFrame()

        filtered['Untung_Per_Biji'] = filtered['Hourly_Low'] - filtered['Live_Low'] - filtered['Tax']
        
        # Kalkulator jumlah beli aman berdasarkan limit GE dan modal per slot
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
        
        # Pengurutan (Sorting)
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
    # TAMPILAN 1: KETAT (> 2% Anjlok, Vol Harian > 500)
    # ==========================================
    st.subheader("📌 Top 3: Anjlok Tajam (> 2%)")
    df_sebelum = process_signals(master_data, threshold_multiplier=1.02, min_d_vol=500, min_h_vol=5, sort_by_volume_score=False)
    if not df_sebelum.empty:
        st.dataframe(df_sebelum, use_container_width=True)
    else:
        st.warning("Tidak ada item laku yang anjlok di atas 2% saat ini. (Lebih baik menahan uang daripada membeli barang sepi).")

    st.divider()

    # ==========================================
    # TAMPILAN 2: LONGGAR (> 0.5% Anjlok, Vol Harian > 1500)
    # ==========================================
    st.subheader("📌 Top 3: Turun Tipis tapi Super Laris (> 0.5%)")
    df_sesudah = process_signals(master_data, threshold_multiplier=1.005, min_d_vol=1500, min_h_vol=15, sort_by_volume_score=True)
    if not df_sesudah.empty:
        st.dataframe(df_sesudah, use_container_width=True)
    else:
        st.warning("Tidak ada item super laris yang memenuhi kriteria saat ini.")

    st.info(f"💡 Kalkulasi ini menggunakan total modal **{total_modal:,} GP** yang otomatis dibagi ke 3 slot GE (**{modal_per_slot:,.0f} GP per slot**).")

else:
    st.error("Gagal memuat data master pasar. Silakan klik tombol perbarui.")
