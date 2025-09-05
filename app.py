# app.py
import numpy as np
import pandas as pd
import altair as alt
import yfinance as yf
import streamlit as st
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

# ----------------------------
# Config
# ----------------------------
st.set_page_config(page_title="DCA em Bitcoin (BRL)", page_icon="🪙", layout="wide")

@st.cache_data(show_spinner=False)
def load_series(start_date: date, end_date: date) -> pd.DataFrame:
    """
    Baixa séries diárias: BTC-USD e USDBRL=X (Yahoo Finance).
    Converte para BTC-BRL = (BTC-USD) * (USDBRL).
    Retorna DataFrame com colunas: ['btc_usd', 'usd_brl', 'btc_brl'] indexado por data.
    """
    # yfinance aceita strings de data
    btc = yf.download("BTC-USD", start=start_date, end=end_date, progress=False)[["Adj Close"]].rename(columns={"Adj Close":"btc_usd"})
    fx  = yf.download("USDBRL=X", start=start_date, end=end_date, progress=False)[["Adj Close"]].rename(columns={"Adj Close":"usd_brl"})

    df = btc.join(fx, how="outer").sort_index()
    # Preenche feriados/fins de semana: BTC negocia 7d, FX não; ffill resolve lacunas do câmbio
    df["usd_brl"] = df["usd_brl"].ffill()
    # Se BTC tiver buraco raro, ffill também
    df["btc_usd"] = df["btc_usd"].ffill()
    df["btc_brl"] = df["btc_usd"] * df["usd_brl"]
    # remove linhas totalmente vazias
    df = df.dropna(subset=["btc_brl"])
    return df

def brl(x: float) -> str:
    s = f"{x:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")

# ----------------------------
# Sidebar - Parâmetros
# ----------------------------
with st.sidebar:
    st.header("Parâmetros")
    anos = st.slider("Y: anos de histórico", min_value=1, max_value=12, value=5, step=1)
    dia_d = st.number_input("D: dia do aporte (1–28)", min_value=1, max_value=28, value=5, step=1,
                            help="Use até 28 para evitar meses menores.")
    aporte_mensal = st.number_input("Aporte mensal (R$)", min_value=0.0, value=1000.0, step=100.0, format="%.2f")
    st.caption("O app comprará BTC todo mês no dia D. Se não houver cotação naquele dia, usa o próximo dia disponível no mês; se não houver, usa o último dia disponível do mês.")
    mostrar_tabela = st.checkbox("Mostrar tabela de aportes", value=False)

# datas
end_dt = date.today() + timedelta(days=1)  # até amanhã para garantir dia atual incluso
start_dt = date.today() - relativedelta(years=anos)

# ----------------------------
# Dados
# ----------------------------
with st.spinner("Carregando séries de preços..."):
    px = load_series(start_dt, end_dt)  # ['btc_usd','usd_brl','btc_brl']

# ----------------------------
# Agenda de compras mensais
# ----------------------------
# Gera meses do intervalo
months = pd.period_range(start=pd.Timestamp(start_dt).to_period("M"),
                         end=pd.Timestamp(e
