import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import time
import altair as alt
import numpy as np
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from streamlit_autorefresh import st_autorefresh

# Konfigurasi Tampilan Halaman Web (Responsif untuk HP)
st.set_page_config(page_title="OSRS Global Flipping Radar", layout="wide")

# ==========================================
# FUNGSI BERSAMA
# ==========================================
# Wiki OSRS minta User-Agent yang deskriptif. Tambahkan kontakmu kalau mau, mis:
# 'OSRS-Flipping-Radar (personal use; kontak: emailmu@contoh.com)'
HEADERS = {'User-Agent': 'OSRS-Flipping-Radar (personal use)'}
BASE_URL = 'https://prices.runescape.wiki/api/v1/osrs'
TZ_WIB = ZoneInfo("Asia/Jakarta")


def _get_json(url):
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=3600)
def fetch_mapping():
    """Mapping SEMUA item OSRS: id, nama, limit beli per 4 jam, status member, nilai high alch."""
    df = pd.DataFrame(_get_json(f'{BASE_URL}/mapping'))
    for col in ['id', 'name', 'limit', 'members', 'highalch']:
        if col not in df.columns:
            df[col] = None
    df = df[['id', 'name', 'limit', 'members', 'highalch']]
    df.rename(columns={'name': 'mappingname', 'limit': 'mappinglimit'}, inplace=True)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    df['mappinglimit'] = pd.to_numeric(df['mappinglimit'], errors='coerce').fillna(0)
    df['highalch'] = pd.to_numeric(df['highalch'], errors='coerce').fillna(0)
    df['Tipe'] = df['members'].apply(lambda m: '👑 Member' if m else '🆓 F2P')
    return df


@st.cache_data(ttl=10)
def fetch_latest():
    """Harga transaksi terakhir (REAL-TIME): Live_Low & Live_High. Cache pendek = update cepat."""
    data = _get_json(f'{BASE_URL}/latest')['data']
    df = pd.DataFrame.from_dict(data, orient='index').reset_index()
    df.rename(columns={'index': 'id', 'low': 'Live_Low', 'high': 'Live_High'}, inplace=True)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    for c in ['Live_Low', 'Live_High']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


@st.cache_data(ttl=120)
def fetch_1h():
    """Rata-rata harga & volume transaksi 1 jam terakhir untuk semua item."""
    data = _get_json(f'{BASE_URL}/1h')['data']
    df = pd.DataFrame.from_dict(data, orient='index').reset_index()
    df.rename(columns={
        'index': 'id', 'avgLowPrice': 'Hourly_Low', 'avgHighPrice': 'Hourly_High',
        'lowPriceVolume': 'H_VolLow', 'highPriceVolume': 'H_VolHigh'
    }, inplace=True)
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    for c in ['Hourly_Low', 'Hourly_High', 'H_VolLow', 'H_VolHigh']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
    return df


@st.cache_data(ttl=300)
def fetch_24h():
    """Rata-rata harga & volume transaksi 24 jam terakhir untuk semua item."""
    data = _get_json(f'{BASE_URL}/24h')['data']
    df = pd.DataFrame.from_dict(data, orient='index').reset_index()
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
    Pajak resmi Grand Exchange OSRS: 2% dari harga jual, dibulatkan ke bawah,
    maksimal 5.000.000 GP per item. Item di bawah 50 GP tidak kena pajak.
    """
    if sell_price is None or sell_price < 50:
        return 0
    return min(math.floor(sell_price * 0.02), 5_000_000)


@st.cache_data(ttl=10)
def fetch_market_data():
    """Gabungan semua data pasar. TTL 10 detik, jadi harga live selalu segar."""
    df_map = fetch_mapping()
    df_1h = fetch_1h()
    df_24h = fetch_24h()
    df_latest = fetch_latest()

    master = df_1h.merge(df_24h, on='id').merge(df_latest, on='id').merge(df_map, on='id', how='inner')
    for col in ['Hourly_Low', 'Live_Low', 'Daily_Low', 'Daily_High', 'D_VolLow', 'H_VolLow', 'mappinglimit']:
        if col in master.columns:
            master[col] = pd.to_numeric(master[col], errors='coerce').fillna(0)
    master['Tax'] = master['Daily_Low'].apply(calc_ge_tax)
    return master


def ambil_master():
    """Pembungkus aman: kalau API gagal, tampilkan error & kembalikan DataFrame kosong."""
    try:
        return fetch_market_data()
    except Exception as e:
        st.error(f"Gagal mengambil data API: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=600)
def _fetch_stats_cached(item_id):
    """
    Statistik historis per item (floor 14/30 hari, volume bulanan, dll).
    Kalau KEDUA panggilan API gagal, raise error supaya hasil gagal TIDAK ikut ke-cache
    (jadi dicoba lagi di refresh berikutnya, bukan nyangkut 10 menit).
    """
    hasil = {
        'biweekly_floor': None, 'monthly_floor': None,
        'monthly_mean_vol_low': 0, 'monthly_mean_vol_high': 0,
        'monthly_median_vol_low': 0, 'monthly_median_vol_high': 0,
        'monthly_max_high': None, 'monthly_max_low': None,
        'granular_daily_median_vol_low': 0, 'granular_daily_median_vol_high': 0,
        'error': None
    }
    errors = []
    num_cols = ['avgHighPrice', 'avgLowPrice', 'highPriceVolume', 'lowPriceVolume']

    # --- Histori per jam, ~14 hari (biweekly floor + median volume 24 jam) ---
    try:
        data = _get_json(f"{BASE_URL}/timeseries?timestep=1h&id={item_id}").get('data', [])
        if data:
            df1h = pd.DataFrame(data).tail(14 * 24)
            for c in num_cols:
                if c in df1h.columns:
                    df1h[c] = pd.to_numeric(df1h[c], errors='coerce')
            min_high = df1h['avgHighPrice'].min(skipna=True) if 'avgHighPrice' in df1h else None
            min_low = df1h['avgLowPrice'].min(skipna=True) if 'avgLowPrice' in df1h else None
            if pd.notna(min_high) and pd.notna(min_low):
                hasil['biweekly_floor'] = (min_high + min_low) / 2.0
            df_24h_slice = df1h.tail(24)
            hasil['granular_daily_median_vol_low'] = float(df_24h_slice['lowPriceVolume'].median(skipna=True) or 0) if 'lowPriceVolume' in df_24h_slice else 0
            hasil['granular_daily_median_vol_high'] = float(df_24h_slice['highPriceVolume'].median(skipna=True) or 0) if 'highPriceVolume' in df_24h_slice else 0
        else:
            errors.append("1h: respons API kosong")
    except Exception as e:
        errors.append(f"1h: {type(e).__name__}")

    # --- Histori per hari, 30 hari (monthly floor + mean/median/max) ---
    try:
        data = _get_json(f"{BASE_URL}/timeseries?timestep=24h&id={item_id}").get('data', [])
        if data:
            df30 = pd.DataFrame(data).tail(30)
            for c in num_cols:
                if c in df30.columns:
                    df30[c] = pd.to_numeric(df30[c], errors='coerce')
            min_high = df30['avgHighPrice'].min(skipna=True) if 'avgHighPrice' in df30 else None
            min_low = df30['avgLowPrice'].min(skipna=True) if 'avgLowPrice' in df30 else None
            if pd.notna(min_high) and pd.notna(min_low):
                hasil['monthly_floor'] = (min_high + min_low) / 2.0
            hasil['monthly_mean_vol_low'] = float(df30['lowPriceVolume'].mean(skipna=True) or 0) if 'lowPriceVolume' in df30 else 0
            hasil['monthly_mean_vol_high'] = float(df30['highPriceVolume'].mean(skipna=True) or 0) if 'highPriceVolume' in df30 else 0
            hasil['monthly_median_vol_low'] = float(df30['lowPriceVolume'].median(skipna=True) or 0) if 'lowPriceVolume' in df30 else 0
            hasil['monthly_median_vol_high'] = float(df30['highPriceVolume'].median(skipna=True) or 0) if 'highPriceVolume' in df30 else 0
            if 'avgHighPrice' in df30 and df30['avgHighPrice'].notna().any():
                hasil['monthly_max_high'] = float(df30['avgHighPrice'].max(skipna=True))
            if 'avgLowPrice' in df30 and df30['avgLowPrice'].notna().any():
                hasil['monthly_max_low'] = float(df30['avgLowPrice'].max(skipna=True))
        else:
            errors.append("24h: respons API kosong")
    except Exception as e:
        errors.append(f"24h: {type(e).__name__}")

    if len(errors) >= 2:
        raise RuntimeError("; ".join(errors))  # jangan di-cache
    hasil['error'] = "; ".join(errors) if errors else None
    return hasil


def fetch_full_verification_stats(item_id):
    try:
        return _fetch_stats_cached(int(item_id))
    except Exception as e:
        return {
            'biweekly_floor': None, 'monthly_floor': None,
            'monthly_mean_vol_low': 0, 'monthly_mean_vol_high': 0,
            'monthly_median_vol_low': 0, 'monthly_median_vol_high': 0,
            'monthly_max_high': None, 'monthly_max_low': None,
            'granular_daily_median_vol_low': 0, 'granular_daily_median_vol_high': 0,
            'error': str(e)
        }


def bunyikan_alert():
    """Bunyi 'ting-ting-ting' lewat browser. Kalau tidak bunyi, klik sekali di halaman dulu
    (browser baru mengizinkan suara setelah ada interaksi)."""
    components.html(f"""
    <script>
    (function() {{
      try {{
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        [880, 1175, 1480].forEach(function(f, i) {{
          const o = ctx.createOscillator(); const g = ctx.createGain();
          o.type = 'sine'; o.frequency.value = f;
          o.connect(g); g.connect(ctx.destination);
          const t = ctx.currentTime + i * 0.18;
          g.gain.setValueAtTime(0.0001, t);
          g.gain.exponentialRampToValueAtTime(0.4, t + 0.02);
          g.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
          o.start(t); o.stop(t + 0.17);
        }});
      }} catch (e) {{}}
    }})();
    // {time.time()}
    </script>
    """, height=0)


# ==========================================
# LIVE SHOCK DIP RADAR (fragment: hanya bagian ini yang auto-refresh,
# jadi cepat & halaman lain/chart tidak ikut ter-reset)
# ==========================================
def _panel_shock_dip(min_profit_total, max_kandidat_dip, bunyi):
    master = ambil_master()
    if master.empty:
        st.warning("Data pasar belum tersedia, mencoba lagi di siklus berikutnya...")
        return

    sekarang = time.time()
    waktu_label = datetime.now(TZ_WIB).strftime("%H:%M:%S")

    # ---------- Stage 1: filter cepat (tanpa API tambahan) ----------
    df_k = master[
        (master['Live_Low'] > 0) &
        (master['Daily_Low'] > 0) &
        (master['Hourly_Low'] > (master['Live_Low'] * 1.02))
    ].copy()

    if not df_k.empty:
        df_k['Tax'] = df_k['Daily_Low'].apply(calc_ge_tax)
        df_k['ProfitPerUnit'] = df_k['Daily_Low'] - df_k['Live_Low'] - df_k['Tax']
        df_k['pctROI'] = (df_k['ProfitPerUnit'] / df_k['Live_Low']) * 100
        df_k['Tax_Live'] = df_k['Live_High'].apply(calc_ge_tax)
        df_k = df_k[(df_k['Live_High'] - df_k['Live_Low'] - df_k['Tax_Live']) > 0]
        df_k['NoBuyLimitProfit'] = df_k['ProfitPerUnit'] * 24 * df_k[['H_VolLow', 'H_VolHigh']].min(axis=1)
        df_k['WithBuyLimitProfit'] = df_k.apply(
            lambda r: r['ProfitPerUnit'] * r['mappinglimit'] if r['mappinglimit'] > 0 else np.inf, axis=1
        )
        df_k['AdjustedPotentialDailyProfit'] = df_k[['NoBuyLimitProfit', 'WithBuyLimitProfit']].min(axis=1)
        df_k = df_k[
            (df_k['pctROI'] > 0) &
            (df_k['AdjustedPotentialDailyProfit'] > min_profit_total)
        ].sort_values(by='AdjustedPotentialDailyProfit', ascending=False).head(int(max_kandidat_dip))

    st.caption(f"🕒 Update terakhir: **{waktu_label} WIB**")

    if df_k.empty:
        st.session_state['dip_seen'] = set()
        st.info("💡 Belum ada kandidat yang lolos filter awal (kesegaran/ROI/profit) saat ini. Radar tetap memantau...")
        return

    # ---------- Stage 2: verifikasi floor 14/30 hari (paralel; item lama diambil dari cache) ----------
    lolos = []
    log_diag = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futs = {executor.submit(fetch_full_verification_stats, int(r['id'])): r for _, r in df_k.iterrows()}
        for fut in as_completed(futs):
            row = futs[fut]
            v = fut.result()
            l14 = (v['biweekly_floor'] is not None) and (row['Live_Low'] < v['biweekly_floor'])
            l30 = (v['monthly_floor'] is not None) and (row['Live_Low'] < v['monthly_floor'])
            anti_inv = (
                v['monthly_max_high'] is not None and v['monthly_max_low'] is not None and
                v['monthly_max_high'] > v['monthly_max_low']
            )
            likuid = (
                v['monthly_median_vol_low'] > 0 and v['monthly_median_vol_high'] > 0 and
                v['granular_daily_median_vol_low'] > 0 and v['granular_daily_median_vol_high'] > 0
            )
            ok = l14 and l30 and anti_inv and likuid
            log_diag.append({
                'Nama Barang': row['mappingname'], 'Harga Skrg': row['Live_Low'],
                'Floor 14 Hari': round(v['biweekly_floor']) if v['biweekly_floor'] is not None else None,
                'Floor 30 Hari': round(v['monthly_floor']) if v['monthly_floor'] is not None else None,
                '14 Hari?': '✅' if l14 else '❌', '30 Hari?': '✅' if l30 else '❌',
                'Anti-Inversi?': '✅' if anti_inv else '❌', 'Likuid?': '✅' if likuid else '❌',
                'Status': '🟢 LOLOS' if ok else '⛔ Gagal',
                'Error API': v['error'] if v['error'] else '-'
            })
            if ok:
                lolos.append(row)

    if not lolos:
        st.session_state['dip_seen'] = set()
        st.info("💡 Belum ada yang lolos verifikasi 14/30 hari & likuiditas. Radar tetap memantau...")
        with st.expander(f"🔍 Detail Diagnostik Tabel 1 ({len(log_diag)} kandidat diperiksa)"):
            st.dataframe(pd.DataFrame(log_diag), use_container_width=True)
        return

    df_v = pd.DataFrame(lolos)
    ids_sekarang = set(df_v['id'].tolist())

    # ---------- Deteksi item BARU + alert ----------
    seen = st.session_state.get('dip_seen')              # None = scan pertama di sesi ini
    last_alert = st.session_state.setdefault('dip_last_alert', {})
    if seen is None:
        baru = set()
    else:
        # cooldown 5 menit per item supaya item yang keluar-masuk tipis tidak bunyi berulang
        baru = {i for i in (ids_sekarang - seen) if sekarang - last_alert.get(i, 0) > 300}
    st.session_state['dip_seen'] = ids_sekarang

    if baru:
        df_baru = df_v[df_v['id'].isin(baru)]
        riwayat = st.session_state.setdefault('dip_riwayat', [])
        for _, r in df_baru.iterrows():
            last_alert[int(r['id'])] = sekarang
            riwayat.insert(0, f"{waktu_label} — {r['mappingname']} @ {int(r['Live_Low']):,} GP")
        st.toast(f"🚨 DIP BARU: {', '.join(df_baru['mappingname'].tolist())}", icon="🚨")
        if bunyi:
            bunyikan_alert()

    # ---------- Tampilan tabel ----------
    df_v['Baru?'] = df_v['id'].apply(lambda x: '🆕 Baru' if x in baru else '')
    df_v['Vol per Jam'] = df_v['H_VolLow'] + df_v['H_VolHigh']
    df_v['Vol Harian'] = df_v['D_VolLow'] + df_v['D_VolHigh']
    df_v['Target Jual'] = df_v['Daily_Low']
    df_v['Maks Beli (BEP)'] = df_v['Daily_Low'] - df_v['Tax']

    def status_harga(roi):
        if roi >= 2:
            return '🟢 Aman Dinaikkan'
        elif roi >= 0.5:
            return '🟡 Pas-pasan'
        return '🔴 Jangan Naikkan'

    df_v['Status Harga'] = df_v['pctROI'].apply(status_harga)
    df_v = df_v.sort_values(by=['Baru?', 'AdjustedPotentialDailyProfit'], ascending=[False, False])

    tampil = df_v.rename(columns={
        'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'mappinglimit': 'Limit Beli',
        'ProfitPerUnit': 'Untung/Biji', 'pctROI': 'ROI (%)',
        'AdjustedPotentialDailyProfit': 'Profit Harian Disesuaikan'
    })

    jumlah_baru = len(baru)
    pesan_baru = f" — 🚨 {jumlah_baru} item BARU muncul!" if jumlah_baru > 0 else ""
    st.success(f"✅ {len(tampil)} item lolos verifikasi shock dip 14 & 30 hari{pesan_baru}")
    st.dataframe(
        tampil[['Baru?', 'Nama Barang', 'Tipe', 'Harga Beli', 'Maks Beli (BEP)', 'Status Harga', 'Target Jual',
                'Vol per Jam', 'Vol Harian', 'Limit Beli', 'Untung/Biji', 'ROI (%)', 'Profit Harian Disesuaikan']],
        use_container_width=True
    )

    if st.session_state.get('dip_riwayat'):
        with st.expander("🔔 Riwayat alert sesi ini"):
            st.write("\n".join(f"- {x}" for x in st.session_state['dip_riwayat'][:30]))

    with st.expander(f"🔍 Detail Diagnostik Tabel 1 ({len(log_diag)} kandidat diperiksa)"):
        st.caption(
            "Kalau 'Error API' terisi, itu masalah koneksi. Kalau kosong tapi tetap ❌, item itu "
            "memang gagal syarat floor historis/likuiditas — bukan bug."
        )
        st.dataframe(pd.DataFrame(log_diag), use_container_width=True)


# ==========================================
# NAVIGASI HALAMAN
# ==========================================
st.sidebar.header("📍 Navigasi")
halaman = st.sidebar.radio(
    "Pilih Halaman:",
    ["🎯 Shock Dip Radar", "🏭 Low Effort Processing"]
)
st.sidebar.divider()

if halaman == "🎯 Shock Dip Radar":
    st.title("⭐ OSRS Global Flipping Radar")
    st.write("Sinyal *trading* otomatis untuk **SEMUA ITEM OSRS (F2P & Member)** dengan Radar Dipped Items Report & Dual Chart.")
    st.caption(
        "ℹ️ Kolom **Maks Beli (BEP)** = batas harga beli tertinggi sebelum kamu balik modal (breakeven), "
        "dihitung dari Harga Jual dikurangi Pajak GE. Kalau kamu naikkan harga beli untuk mempercepat fill, "
        "jangan sampai melewati angka ini. Kolom **Status Harga** menandai seberapa lega ruang kenaikannya: "
        "🟢 Aman Dinaikkan (≥2% dari Harga Beli) · 🟡 Pas-pasan (0.5%–2%) · 🔴 Jangan Naikkan (<0.5%, nyaris tidak ada ruang)."
    )
    st.caption("🏭 Mau lihat strategi lain? Buka halaman **Low-Effort Processing** di sidebar kiri.")

    st.markdown("""
    <style>
    div[data-testid="stSidebar"] .stButton > button {
        background-color: #28a745 !important;
        color: white !important;
        border: 1px solid #28a745 !important;
        font-weight: bold;
    }
    div[data-testid="stSidebar"] .stButton > button:hover {
        background-color: #218838 !important;
        border: 1px solid #218838 !important;
        color: white !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ---------- SIDEBAR: Live Radar ----------
    st.sidebar.header("🚨 Live Dip Radar (Tabel 1)")
    live_radar = st.sidebar.checkbox(
        "Aktifkan Live Radar", value=True, key="toggle_live_radar",
        help="Tabel 1 otomatis cek ulang tanpa me-reload halaman. Item dip BARU diberi tanda 🆕, notifikasi, dan bunyi."
    )
    interval_radar = st.sidebar.slider(
        "Cek ulang tiap (detik)", min_value=10, max_value=60, value=15, step=5, key="interval_live_radar",
        help="Harga live di-cache 10 detik. Di bawah itu tidak ada gunanya."
    )
    bunyi_alert = st.sidebar.checkbox(
        "🔊 Bunyi saat ada dip baru", value=True, key="toggle_bunyi",
        help="Kalau tidak bunyi, klik sekali di mana saja di halaman (aturan browser)."
    )

    st.sidebar.header("🛡️ Filter Shock Dip Detection (Tabel 1)")
    st.sidebar.caption("Metodologi lengkap dari poignanttech.com — Virtual Markets Part Four.")
    min_profit_total = st.sidebar.number_input(
        "Min. Profit Harian Disesuaikan — Tabel 1 (GP)", min_value=0, value=20000, step=5000,
        help="'AdjustedPotentialDailyProfit' — proyeksi profit HARIAN kalau kamu jual-beli sampai batas limit/volume.",
        key="min_profit_tabel1"
    )
    max_kandidat_dip = st.sidebar.number_input(
        "Maks. Kandidat Verifikasi 14/30 Hari", min_value=5, max_value=100, value=30, step=5,
        help="Kandidat teratas diverifikasi via API timeseries. Hasilnya di-cache, jadi refresh berikutnya cepat.",
        key="max_kandidat_tabel1"
    )

    st.sidebar.header("↔️ Filter High-Low Spread (Tabel 2)")
    st.sidebar.caption("Metodologi lengkap dari poignanttech.com — Virtual Markets Part Two.")
    min_roi_spread = st.sidebar.number_input(
        "Min. ROI (%)", min_value=0.0, value=4.0, step=0.5,
        help="ROI di bawah ini disaring, karena margin-nya terlalu tipis relatif ke modal.",
        key="min_roi_tabel2"
    )
    min_profit_spread = st.sidebar.number_input(
        "Min. Profit Harian Disesuaikan — Tabel 2 (GP)", min_value=0, value=20000, step=5000,
        help="'AdjustedPotentialDailyProfit' — proyeksi profit HARIAN. Item di bawah ini disaring.",
        key="min_profit_tabel2"
    )
    min_vol_spread = st.sidebar.number_input(
        "Min. Volume per Jam (kedua sisi)", min_value=0, value=4, step=1,
        help="Item dengan volume Low ATAU High di bawah ini per jam dianggap terlalu tipis.",
        key="min_vol_tabel2"
    )
    max_kandidat_spread = st.sidebar.number_input(
        "Maks. Kandidat Verifikasi Bulanan", min_value=5, max_value=100, value=30, step=5,
        help="Kandidat teratas diverifikasi terhadap data bulanan & harian via API timeseries.",
        key="max_kandidat_tabel2"
    )

    st.sidebar.header("📊 Filter Lonjakan Volume (Tabel 3)")
    min_rasio_lonjakan = st.sidebar.number_input(
        "Min. Rasio Lonjakan (x normal)", min_value=1.0, value=2.0, step=0.5,
        help="Item dengan volume 1 jam terakhir di bawah X kali rata-rata per jam akan disaring.",
        key="min_rasio_lonjakan"
    )
    min_vol_absolut = st.sidebar.number_input(
        "Min. Volume Absolut per Jam", min_value=0, value=5, step=5,
        help="Buang item yang volumenya emang selalu kecil.",
        key="min_vol_absolut_tabel3"
    )

    st.sidebar.header("🔄 Refresh Data")
    st.sidebar.caption("Live Radar hanya me-refresh Tabel 1. Tabel 2, 3 & chart ikut ter-update lewat opsi di bawah / tombol manual.")
    aktifkan_auto_refresh = st.sidebar.checkbox(
        "Auto-Refresh SELURUH halaman (Tabel 2, 3, chart)", value=False,
        help="Opsional. Me-reload semuanya, jadi lebih berat. Biarkan mati kalau cuma mantengin dip.",
        key="toggle_auto_refresh"
    )
    if aktifkan_auto_refresh:
        interval_refresh = st.sidebar.number_input(
            "Interval Auto-Refresh Halaman (detik)", min_value=30, max_value=300, value=60, step=10,
            key="interval_auto_refresh"
        )
        st_autorefresh(interval=int(interval_refresh) * 1000, key="dip_auto_refresh")

    if st.sidebar.button("🔄 Refresh Sekarang"):
        fetch_market_data.clear()
        fetch_latest.clear()
        st.rerun()

    # ==========================================
    # TABEL 1: SHOCK DIP DETECTION (LIVE)
    # ==========================================
    st.subheader("🛡️ Tabel 1: Shock Dip Detection (Live)")
    st.write(
        "Item yang mengalami shock dip beneran — bukan cuma turun harga biasa. Mengikuti metodologi "
        "[Virtual Markets Part Four](https://poignanttech.com/2024/03/18/virtual-markets-part-four-shocks-and-dip-detection/) "
        "dari poignanttech.com: kesegaran dip 1 jam, verifikasi rekor terendah 14 & 30 hari, "
        "anti-inversi, dan cek likuiditas."
    )
    panel_dip = st.fragment(_panel_shock_dip, run_every=(f"{int(interval_radar)}s" if live_radar else None))
    panel_dip(min_profit_total, max_kandidat_dip, bunyi_alert)

    st.divider()

    # ==========================================
    # Data untuk Tabel 2, 3 & chart (ter-update saat halaman di-refresh)
    # ==========================================
    with st.spinner('Memindai seluruh pasar OSRS (F2P & Member)...'):
        master_data = ambil_master()

    if not master_data.empty:

        # ==========================================
        # TABEL 2: HIGH-LOW SPREAD
        # ==========================================
        st.subheader("↔️ Tabel 2: High-Low Spread")
        st.write(
            "Item dengan celah Low-High yang konsisten menguntungkan — mengikuti metodologi lengkap "
            "[Virtual Markets Part Two](https://poignanttech.com/2024/03/01/virtual-markets-part-two-market-fundamentals-and-the-high-low-spread/) "
            "dari poignanttech.com, termasuk filter anti barang 'zombie' dan cek likuiditas bulanan."
        )

        df_spread = master_data[
            (master_data['Hourly_Low'] > 0) &
            (master_data['Hourly_High'] > 0) &
            (master_data['H_VolLow'] > min_vol_spread) &
            (master_data['H_VolHigh'] > min_vol_spread)
        ].copy()

        if not df_spread.empty:
            df_spread['Tax_Spread'] = df_spread['Hourly_High'].apply(calc_ge_tax)
            df_spread['Untung_Per_Biji'] = df_spread['Hourly_High'] - df_spread['Hourly_Low'] - df_spread['Tax_Spread']
            df_spread = df_spread[df_spread['Untung_Per_Biji'] > 0]

            df_spread['Tax_Live'] = df_spread['Live_High'].apply(calc_ge_tax)
            df_spread = df_spread[(df_spread['Live_High'] - df_spread['Live_Low'] - df_spread['Tax_Live']) > 0]

            df_spread['ROI_Persen'] = (df_spread['Untung_Per_Biji'] / df_spread['Hourly_Low']) * 100

            df_spread['NoBuyLimitProfit'] = df_spread['Untung_Per_Biji'] * 24 * df_spread[['H_VolLow', 'H_VolHigh']].min(axis=1)
            df_spread['WithBuyLimitProfit'] = df_spread.apply(
                lambda r: r['Untung_Per_Biji'] * r['mappinglimit'] if r['mappinglimit'] > 0 else np.inf, axis=1
            )
            df_spread['AdjustedPotentialDailyProfit'] = df_spread[['NoBuyLimitProfit', 'WithBuyLimitProfit']].min(axis=1)

            df_spread = df_spread[
                (df_spread['ROI_Persen'] > min_roi_spread) &
                (df_spread['AdjustedPotentialDailyProfit'] > min_profit_spread)
            ].sort_values(by='AdjustedPotentialDailyProfit', ascending=False)

            if df_spread.empty:
                st.info("💡 Tidak ada item yang lolos filter awal spread/ROI/profit di sidebar saat ini.")
            else:
                kandidat_spread = df_spread.head(int(max_kandidat_spread))
                hasil_final = []
                log_diagnostik_spread = []
                total_kandidat_spread = len(kandidat_spread)
                progress_spread = st.progress(0, text="Memverifikasi likuiditas bulanan Tabel 2...")
                selesai_spread = 0

                with ThreadPoolExecutor(max_workers=12) as executor:
                    future_ke_row = {executor.submit(fetch_full_verification_stats, int(row['id'])): row for _, row in kandidat_spread.iterrows()}
                    for future in as_completed(future_ke_row):
                        row = future_ke_row[future]
                        m = future.result()
                        selesai_spread += 1
                        progress_spread.progress(
                            selesai_spread / total_kandidat_spread,
                            text=f"Memverifikasi {row['mappingname']} ({selesai_spread}/{total_kandidat_spread})..."
                        )

                        lolos_anti_inversi = (
                            m['monthly_max_high'] is not None and m['monthly_max_low'] is not None and
                            m['monthly_max_high'] > m['monthly_max_low']
                        )
                        lolos_likuiditas_bulanan = (
                            m['monthly_median_vol_low'] > 0 and m['monthly_median_vol_high'] > 0 and
                            m['granular_daily_median_vol_low'] > 0 and m['granular_daily_median_vol_high'] > 0
                        )
                        total_bulanan = m['monthly_mean_vol_low'] + m['monthly_mean_vol_high']
                        total_granular = row['H_VolLow'] + row['H_VolHigh']
                        lolos_anti_shock = total_bulanan > (12 * total_granular)

                        lolos_semua = lolos_anti_inversi and lolos_likuiditas_bulanan and lolos_anti_shock

                        log_diagnostik_spread.append({
                            'Nama Barang': row['mappingname'],
                            'Max High Bulanan': round(m['monthly_max_high']) if m['monthly_max_high'] is not None else None,
                            'Max Low Bulanan': round(m['monthly_max_low']) if m['monthly_max_low'] is not None else None,
                            'Anti-Inversi?': '✅' if lolos_anti_inversi else '❌',
                            'Likuid Bulanan?': '✅' if lolos_likuiditas_bulanan else '❌',
                            'Anti-Shock?': '✅' if lolos_anti_shock else '❌',
                            'Status': '🟢 LOLOS' if lolos_semua else '⛔ Gagal',
                            'Error API': m['error'] if m['error'] else '-'
                        })

                        if lolos_semua:
                            hasil_final.append(row)

                progress_spread.empty()

                if hasil_final:
                    df_final_spread = pd.DataFrame(hasil_final).sort_values(by='AdjustedPotentialDailyProfit', ascending=False)
                    df_final_spread['Modal Dibutuhkan (Full Limit)'] = df_final_spread['Live_Low'] * df_final_spread['mappinglimit']

                    df_final_spread_display = df_final_spread.rename(columns={
                        'mappingname': 'Nama Barang', 'Hourly_Low': 'Harga Beli', 'Hourly_High': 'Harga Jual',
                        'mappinglimit': 'Limit Beli', 'ROI_Persen': 'ROI (%)',
                        'AdjustedPotentialDailyProfit': 'Profit Harian Disesuaikan'
                    })

                    st.success(f"✅ {len(df_final_spread_display)} item lolos verifikasi High-Low Spread lengkap!")
                    st.dataframe(
                        df_final_spread_display[['Nama Barang', 'Tipe', 'Harga Beli', 'Harga Jual', 'Limit Beli',
                                                 'Modal Dibutuhkan (Full Limit)', 'Profit Harian Disesuaikan', 'ROI (%)']],
                        use_container_width=True
                    )
                else:
                    st.info("💡 Tidak ada kandidat yang lolos verifikasi bulanan/harian saat ini. Coba turunkan ambang di sidebar, atau naikkan 'Maks. Kandidat Verifikasi Bulanan'.")

                with st.expander(f"🔍 Detail Diagnostik Tabel 2 ({total_kandidat_spread} kandidat diperiksa)"):
                    st.caption(
                        "Kalau 'Error API' terisi, tabel kosong karena masalah koneksi — coba lagi. Kalau kosong "
                        "tapi tetap ❌, item itu memang gagal syarat likuiditas/anti-manipulasi bulanan — bukan bug."
                    )
                    st.dataframe(pd.DataFrame(log_diagnostik_spread), use_container_width=True)

        st.divider()

        # ==========================================
        # TABEL 3: LONJAKAN VOLUME
        # ==========================================
        st.subheader("📊 Tabel 3: Lonjakan Volume")
        st.write(
            "Item yang volume transaksi 1 jam terakhirnya jauh di atas kebiasaan hariannya — "
            "sinyal ada sesuatu yang sedang terjadi (borongan beli, dump jual, atau cuma rame biasa). "
            "Cek kolom **Arah Harga** buat tau itu lagi dibeli borongan (naik) atau dijual borongan (turun)."
        )

        df_lonjakan = master_data[
            (master_data['D_VolLow'] + master_data['D_VolHigh'] > 0) &
            (master_data['Live_Low'] > 0)
        ].copy()

        if not df_lonjakan.empty:
            df_lonjakan['Vol_Perjam_Sekarang'] = df_lonjakan['H_VolLow'] + df_lonjakan['H_VolHigh']
            df_lonjakan['Vol_Baseline_Perjam'] = (df_lonjakan['D_VolLow'] + df_lonjakan['D_VolHigh']) / 24

            df_lonjakan = df_lonjakan[df_lonjakan['Vol_Perjam_Sekarang'] >= min_vol_absolut]

            df_lonjakan['Rasio_Lonjakan'] = df_lonjakan.apply(
                lambda r: (r['Vol_Perjam_Sekarang'] / r['Vol_Baseline_Perjam']) if r['Vol_Baseline_Perjam'] > 0 else None,
                axis=1
            )
            df_lonjakan = df_lonjakan[
                df_lonjakan['Rasio_Lonjakan'].notna() & (df_lonjakan['Rasio_Lonjakan'] >= min_rasio_lonjakan)
            ].sort_values(by='Rasio_Lonjakan', ascending=False)

            def arah_harga(row):
                if row['Hourly_Low'] <= 0:
                    return '❓ N/A'
                selisih_persen = ((row['Live_Low'] - row['Hourly_Low']) / row['Hourly_Low']) * 100
                if selisih_persen >= 1:
                    return '📈 Naik'
                elif selisih_persen <= -1:
                    return '📉 Turun'
                else:
                    return '➖ Stabil'

            if df_lonjakan.empty:
                st.info("💡 Tidak ada item dengan lonjakan volume signifikan saat ini (coba turunkan ambang di sidebar).")
            else:
                df_lonjakan['Arah Harga'] = df_lonjakan.apply(arah_harga, axis=1)
                df_lonjakan['Rasio_Lonjakan'] = df_lonjakan['Rasio_Lonjakan'].round(1)
                df_lonjakan['Vol_Perjam_Sekarang'] = df_lonjakan['Vol_Perjam_Sekarang'].round().astype(int)

                df_lonjakan_display = df_lonjakan.rename(columns={
                    'mappingname': 'Nama Barang', 'Live_Low': 'Harga Beli', 'Live_High': 'Harga Jual',
                    'Vol_Perjam_Sekarang': 'Vol/Jam Sekarang', 'Rasio_Lonjakan': 'Rasio Lonjakan'
                })
                st.dataframe(
                    df_lonjakan_display[['Nama Barang', 'Tipe', 'Harga Beli', 'Harga Jual', 'Vol/Jam Sekarang', 'Rasio Lonjakan', 'Arah Harga']],
                    use_container_width=True
                )

        st.divider()

        # ==========================================
        # DUAL CHART (SEMUA ITEM)
        # ==========================================
        st.header("📈 Dual Chart Analisis (Semua Item)")
        st.write("Pilih barang apa saja dari seluruh item OSRS (F2P & Member) untuk melihat grafik 5m & 1h secara bersamaan.")

        daftar_item = master_data.sort_values(by='mappingname')[['id', 'mappingname']].drop_duplicates()
        pilihan_nama = st.selectbox("Pilih Barang:", daftar_item['mappingname'].tolist(), index=0)
        id_terpilih = daftar_item[daftar_item['mappingname'] == pilihan_nama]['id'].values[0]

        @st.cache_data(ttl=60)
        def fetch_chart_data(item_id, timestep):
            url = f"{BASE_URL}/timeseries?timestep={timestep}&id={item_id}"
            try:
                res = _get_json(url)
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
                train_d = df_c.iloc[max(0, train_end - 15):train_end].copy()
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

                # --- Deteksi apakah dip SUDAH MULAI PULIH ---
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

                # --- Bar chart volume ---
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

        render_chart("5 Menit (Scalping / Jangka Pendek)", "5m")
        st.divider()
        render_chart("1 Jam (Macro / Tren Utama)", "1h")
        st.divider()

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
        df_24h = fetch_24h()
        price_ref = df_map.merge(df_latest, on='id', how='left').merge(df_1h, on='id', how='left').merge(df_24h, on='id', how='left').set_index('id')

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

        # --- Volume JUAL produk (beda dari volume BAHAN yang dipakai buat batas beli) ---
        vol_low_p = product_ref['H_VolLow'] if pd.notna(product_ref.get('H_VolLow')) else 0
        vol_high_p = product_ref['H_VolHigh'] if pd.notna(product_ref.get('H_VolHigh')) else 0
        vol_produk_1h = vol_low_p + vol_high_p

        vol_low_p_24h = product_ref['D_VolLow'] if pd.notna(product_ref.get('D_VolLow')) else 0
        vol_high_p_24h = product_ref['D_VolHigh'] if pd.notna(product_ref.get('D_VolHigh')) else 0
        vol_produk_24h = vol_low_p_24h + vol_high_p_24h

        if vol_produk_1h >= 100:
            status_vol_produk = '🟢 Tinggi'
        elif vol_produk_1h >= 10:
            status_vol_produk = '🟡 Sedang'
        elif vol_produk_1h >= 1:
            status_vol_produk = '🟠 Rendah'
        else:
            status_vol_produk = '🔴 Sangat Rendah/Tidak Ada'

        # Pajak dihitung terpisah untuk skenario jual di Low vs High
        tax_low = calc_ge_tax(live_low)
        tax_high = calc_ge_tax(live_high)

        modal_per_eksekusi = total_low_cost + processing_cost
        untung_low = (qty_produced * live_low) - modal_per_eksekusi - (qty_produced * tax_low)
        untung_high = (qty_produced * live_high) - modal_per_eksekusi - (qty_produced * tax_high)

        if (untung_low + untung_high) <= 0:
            continue  # kriteria artikel: buang resep yang totalnya negatif

        maks_eksekusi_likuiditas = min(limit_kandidat) if limit_kandidat else None
        roi_persen = (untung_low / modal_per_eksekusi * 100) if modal_per_eksekusi > 0 else 0

        # --- Rasio Volume/Untung: volume pasar per 1000 GP untung ---
        if untung_high > 0:
            rasio_vol_profit = round((vol_produk_1h / untung_high) * 1000, 3)
        else:
            rasio_vol_profit = None

        hasil_rows.append({
            'Produk': nama_produk,
            'Metode': tipe_resep,
            'Syarat': RECIPE_REQUIREMENTS.get(tipe_resep, 'Cek OSRS Wiki'),
            'Modal/Eksekusi': round(modal_per_eksekusi),
