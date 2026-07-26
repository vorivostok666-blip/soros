"""
common.py — Fungsi bersama yang dipakai oleh Home (shock-dip radar) dan
halaman Low-Effort Processing, supaya tidak duplikat kode pemanggilan API
wiki OSRS & perhitungan pajak GE di banyak tempat.
"""
import math
import requests
import pandas as pd
import streamlit as st

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
