import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
from common import fetch_mapping, fetch_latest, fetch_1h, calc_ge_tax

st.set_page_config(page_title="Low-Effort Processing", layout="centered")
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
    path = Path(__file__).resolve().parent.parent / "low_effort_recipes.csv"
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
