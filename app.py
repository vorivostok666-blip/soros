import streamlit as st
import pandas as pd
import requests

# Konfigurasi Tampilan Halaman Web (Responsif untuk HP)
st.set_page_config(page_title="OSRS F2P Dip Bot", layout="centered")

st.title("📊 OSRS F2P Dip Trading Bot")
st.write("Sinyal *trading* otomatis khusus F2P (Modal 58k GP, 3 Slot) berbasis analisis penurunan harga (*price dip*).")

# Tombol untuk memperbarui data secara manual dari HP
if st.button("🔄 Perbarui Data Pasar"):
    st.rerun()

@st.cache_data(ttl=60) # Menyimpan cache data selama 60 detik agar aman dari limit API Wiki
def load_trading_signals():
    headers = {'User-Agent': 'Belajar_Data_Analisis_Bot_Lokal'}
    
    try:
        # 1. Tarik Data MAPPING (Filter khusus F2P)
        req_map = requests.get('https://prices.runescape.wiki/api/v1/osrs/mapping', headers=headers)
        df_map = pd.DataFrame(req_map.json())[['id', 'name', 'limit', 'members']]
        df_map = df_map[df_map['members'] == False]
        df_map.rename(columns={'name': 'mappingname', 'limit': 'mappinglimit'}, inplace=True)

        # 2. Tarik Data 1 Jam (Basis Harga Jam Lalu / Recency)
        req_1h = requests.get('https://prices.runescape.wiki/api/v1/osrs/1h', headers=headers)
        df_1h = pd.DataFrame.from_dict(req_1h.json()['data'], orient='index').reset_index()
        df_1h.rename(columns={'index': 'id', 'avgLowPrice': 'Hourly_Low', 'lowPriceVolume': 'H_VolLow'}, inplace=True)

        # 3. Tarik Data 24 Jam (Basis Historis & Volume Harian)
        req_24h = requests.get('https://prices.runescape.wiki/api/v1/osrs/24h', headers=headers)
        df_24h = pd.DataFrame.from_dict(req_24h.json()['data'], orient='index').reset_index()
        df_24h.rename(columns={'index': 'id', 'avgLowPrice': 'Daily_Low', 'avgHighPrice': 'Daily_High', 'lowPriceVolume': 'D_VolLow'}, inplace=True)

        # 4. Tarik Data LATEST (Harga Real-Time Detik Ini)
        req_latest = requests.get('https://prices.runescape.wiki/api/v1/osrs/latest', headers=headers)
        df_latest = pd.DataFrame.from_dict(req_latest.json()['data'], orient='index').reset_index()
        df_latest.rename(columns={'index': 'id', 'low': 'Live_Low', 'high': 'Live_High'}, inplace=True)

        # Pastikan tipe data ID seragam
        for df in [df_1h, df_24h, df_latest]:
            df['id'] = df['id'].astype(int)

        # Gabungkan data
        master = df_1h.merge(df_24h, on='id').merge(df_latest, on='id').merge(df_map, on='id', how='inner')
        
        # Kalkulasi Pajak: Barang < 100 GP Bebas Pajak, di atasnya 2%
        master['Tax'] = master['Hourly_Low'].apply(lambda x: 0 if x < 100 else round((x * 0.02) - 0.5))
        
        # Filter Logika: Dip tipis (0.5%), Cek Historis, Anti Zombi, Volume Raksasa
        filtered = master[
            (master['Live_Low'] > 0) & 
            (master['Hourly_Low'] > (master['Live_Low'] * 1.005)) & 
            (((master['Daily_Low'] + master['Daily_High']) / 2.0) > master['Live_Low']) & 
            ((master['Hourly_Low'] - master['Live_Low'] - master['Tax']) > 0) & 
            (master['D_VolLow'] > 200) & 
            (master['Daily_High'] > master['Daily_Low'])
        ].copy()

        if filtered.empty:
            return pd.DataFrame()

        # Kalkulasi Modal 58k GP terbagi 3 slot (~19.333 GP per slot)
        filtered['Untung_Per_Biji'] = filtered['Hourly_Low'] - filtered['Live_Low'] - filtered['Tax']
        filtered['Beli_Berapa_Biji'] = filtered[['mappinglimit', 'Live_Low']].apply(
            lambda row: min(row['mappinglimit'], int(19333 / row['Live_Low'])) if row['Live_Low'] > 0 else 0, axis=1
        )
        filtered['Total_Untung_Slot'] = filtered['Untung_Per_Biji'] * filtered['Beli_Berapa_Biji']
        filtered['ROI_Persen'] = (filtered['Untung_Per_Biji'] / filtered['Live_Low']) * 100
        
        # Urutkan berdasarkan Skor Likuiditas (Untung x Volume Harian)
        filtered['Skor'] = filtered['Untung_Per_Biji'] * filtered['D_VolLow']
        result = filtered.sort_values(by='Skor', ascending=False).head(3)
        
        # Ubah nama kolom agar mudah dibaca di HP
        result = result.rename(columns={
            'mappingname': 'Nama Barang',
            'Live_Low': 'Harga Beli (Live)',
            'Hourly_Low': 'Harga Jual (Normal)',
            'Beli_Berapa_Biji': 'Jumlah Beli',
            'Total_Untung_Slot': 'Proyeksi Untung',
            'ROI_Persen': 'ROI (%)'
        })
        
        return result[['Nama Barang', 'Harga Beli (Live)', 'Harga Jual (Normal)', 'Jumlah Beli', 'Proyeksi Untung', 'ROI (%)']]
        
    except Exception as e:
        st.error(f"Gagal memuat data pasar: {e}")
        return pd.DataFrame()

# Eksekusi dan Tampilkan Laporan di Web
with st.spinner('Sedang memindai pasar OSRS...'):
    df_result = load_trading_signals()

if not df_result.empty:
    st.success("Sinyal Selesai Dimuat!")
    st.dataframe(df_result, use_container_width=True)
    st.info("💡 **Panduan Eksekusi di Grand Exchange:**\n- Pasang **Buy Offer** di harga kolom **Harga Beli (Live)**.\n- Setelah terbeli, pasang **Sell Offer** di harga kolom **Harga Jual (Normal)**.")
else:
    st.warning("Belum ada item yang memenuhi kriteria saat ini. Coba klik tombol perbarui beberapa saat lagi.")