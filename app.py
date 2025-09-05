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
    Baixa séries diárias: BTC-USD e USDBRL=X (Yahoo Finance) e converte para BTC-BRL = (BTC-USD) * (USDBRL).
    Retorna DataFrame com colunas ['btc_usd', 'usd_brl', 'btc_brl'] indexado por data.
    É robusta a MultiIndex de colunas e à ausência de 'Adj Close'.
    """

    def _download_single(ticker: str) -> pd.Series:
        df = yf.download(
            ticker,
            start=start_date,
            end=end_date,
            progress=False,
            auto_adjust=False,   # mantemos 'Adj Close' se existir
            group_by="column"    # evita multiindex na maioria dos casos, mas tratamos se vier
        )

        if df is None or len(df) == 0:
            raise RuntimeError(f"Nenhum dado retornado para {ticker}. Tente outro intervalo ou verifique a rede.")

        # Se vier MultiIndex (nível 0: OHLCV / nível 1: ticker)
        if isinstance(df.columns, pd.MultiIndex):
            # tenta 'Adj Close' e depois 'Close'
            for field in ("Adj Close", "Close"):
                if (field, ticker) in df.columns:
                    s = df[(field, ticker)].rename(ticker)
                    break
            else:
                raise KeyError(f"Nem 'Adj Close' nem 'Close' encontrados para {ticker}. Colunas: {list(df.columns)}")
        else:
            # colunas simples
            for field in ("Adj Close", "Close"):
                if field in df.columns:
                    s = df[field].rename(ticker)
                    break
            else:
                raise KeyError(f"Nem 'Adj Close' nem 'Close' encontrados para {ticker}. Colunas: {list(df.columns)}")

        # Remove NaN extremos e ordena
        s = s.sort_index().dropna()
        return s

    btc_usd = _download_single("BTC-USD")
    usd_brl = _download_single("USDBRL=X")

    df = pd.concat([btc_usd.rename("btc_usd"), usd_brl.rename("usd_brl")], axis=1).sort_index()

    # Preenche lacunas típicas do câmbio (fim de semana/feriados)
    df["usd_brl"] = df["usd_brl"].ffill()
    # Preenche eventual buraco do BTC (raro)
    df["btc_usd"] = df["btc_usd"].ffill()

    # Calcula BTC em BRL
    df["btc_brl"] = df["btc_usd"] * df["usd_brl"]

    # Garante que não ficou tudo NaN
    df = df.dropna(subset=["btc_brl"])
    if df.empty:
        raise RuntimeError("Série BTC-BRL ficou vazia após tratamento. Verifique o período escolhido.")

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
                         end=pd.Timestamp(end_dt).to_period("M"), freq="M")

exec_dates = []
for m in months:
    # data alvo = ano-mês com dia D
    target = pd.Timestamp(year=m.year, month=m.month, day=min(dia_d, 28))
    # janela do mês
    month_start = pd.Timestamp(year=m.year, month=m.month, day=1)
    month_end   = (month_start + pd.offsets.MonthEnd(0)).normalize()
    # candidatos: dia D ou próximo dia disponível dentro do mês
    # 1) se existe exatamente o dia D na série
    if target in px.index:
        exec_dt = target
    else:
        # 2) próximo dia disponível >= target dentro do mês
        after = px.loc[(px.index >= target) & (px.index <= month_end)]
        if len(after) > 0:
            exec_dt = after.index[0]
        else:
            # 3) fallback: último dia disponível no mês (<= month_end)
            before = px.loc[(px.index >= month_start) & (px.index <= month_end)]
            if len(before) > 0:
                exec_dt = before.index[-1]
            else:
                # se não houver dados no mês, pula (raro)
                continue
    exec_dates.append(exec_dt)

exec_dates = sorted(pd.unique(exec_dates))

# ----------------------------
# Simulação DCA
# ----------------------------
records = []
btc_cum = 0.0
brl_investido = 0.0

for dt in exec_dates:
    price_brl = float(px.loc[dt, "btc_brl"])
    if aporte_mensal > 0 and price_brl > 0:
        qty_btc = aporte_mensal / price_brl
        btc_cum += qty_btc
        brl_investido += aporte_mensal
        pm = brl_investido / btc_cum  # preço médio BRL/BTC
    else:
        qty_btc = 0.0
        pm = brl_investido / btc_cum if btc_cum > 0 else np.nan

    # valor de mercado na data do aporte
    val_brl = btc_cum * price_brl
    pnl = val_brl - brl_investido
    roi = (pnl / brl_investido * 100.0) if brl_investido > 0 else 0.0

    records.append({
        "Data": dt.normalize(),
        "Preço BTC (BRL)": price_brl,
        "Aporte (R$)": aporte_mensal,
        "BTC comprado": qty_btc,
        "BTC acumulado": btc_cum,
        "Aportes acumulados (R$)": brl_investido,
        "Valor de mercado (R$)": val_brl,
        "P&L (R$)": pnl,
        "ROI (%)": roi,
        "Preço médio (BRL/BTC)": pm
    })

dca = pd.DataFrame(records)

# Se ainda não houve nenhum mês (ex.: aporte=0), cria linha final “marcada” com valor atual
if dca.empty:
    last_px = float(px["btc_brl"].iloc[-1])
    dca = pd.DataFrame([{
        "Data": px.index[-1].normalize(),
        "Preço BTC (BRL)": last_px,
        "Aporte (R$)": 0.0,
        "BTC comprado": 0.0,
        "BTC acumulado": 0.0,
        "Aportes acumulados (R$)": 0.0,
        "Valor de mercado (R$)": 0.0,
        "P&L (R$)": 0.0,
        "ROI (%)": 0.0,
        "Preço médio (BRL/BTC)": np.nan
    }])

# Valor “atual” com último preço
last_price = float(px["btc_brl"].iloc[-1])
btc_total = float(dca["BTC acumulado"].iloc[-1])
invest_total = float(dca["Aportes acumulados (R$)"].iloc[-1])
val_atual = btc_total * last_price
pnl_atual = val_atual - invest_total
roi_atual = (pnl_atual / invest_total * 100.0) if invest_total > 0 else 0.0
preco_medio = float(dca["Preço médio (BRL/BTC)"].iloc[-1]) if btc_total > 0 else np.nan

# ----------------------------
# Cabeçalho
# ----------------------------
st.title("🪙 DCA em Bitcoin (BRL)")
st.write("Configure **Y** (anos), **D** (dia do mês) e o **aporte mensal** para simular compras recorrentes de BTC em reais.")

# ----------------------------
# KPIs
# ----------------------------
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total aportado", brl(invest_total))
k2.metric("Valor atual", brl(val_atual))
k3.metric("P&L", brl(pnl_atual), f"{roi_atual:,.2f}%")
k4.metric("BTC acumulado", f"{btc_total:,.8f}")
k5.metric("Preço médio", brl(preco_medio) if np.isfinite(preco_medio) else "—")

st.caption(f"Último preço do BTC (BRL): **{brl(last_price)}** — dados Yahoo Finance (BTC-USD × USDBRL=X).")

# ----------------------------
# Gráfico 1: Preço do BTC em BRL (diário)
# ----------------------------
st.subheader("Preço do BTC em BRL (diário)")
chart_price = alt.Chart(px.reset_index().rename(columns={"index":"Data"})).mark_line().encode(
    x=alt.X("Date:T", title="Data"),
    y=alt.Y("btc_brl:Q", title="Preço (R$)"),
    tooltip=[alt.Tooltip("Date:T", title="Data"), alt.Tooltip("btc_brl:Q", title="Preço (R$)", format=",.2f")]
).properties(height=360)
st.altair_chart(chart_price, use_container_width=True)

# ----------------------------
# Gráfico 2: Evolução mensal da carteira (R$) e BTC
# ----------------------------
st.subheader("Evolução mensal: carteira (R$) e BTC acumulado")

# série em reais
val_chart = alt.Chart(dca).mark_line(point=True).encode(
    x=alt.X("Data:T", title="Data"),
    y=alt.Y("Valor de mercado (R$):Q", title="Valor de mercado (R$)"),
    tooltip=[
        alt.Tooltip("Data:T", title="Data"),
        alt.Tooltip("Valor de mercado (R$):Q", format=",.2f"),
        alt.Tooltip("Aportes acumulados (R$):Q", format=",.2f"),
        alt.Tooltip("BTC acumulado:Q", format=",.8f"),
        alt.Tooltip("Preço médio (BRL/BTC):Q", format=",.2f"),
        alt.Tooltip("ROI (%):Q", format=",.2f"),
    ]
).properties(height=340)

# série em BTC (escala separada)
btc_chart = alt.Chart(dca).mark_line(point=True).encode(
    x=alt.X("Data:T", title="Data"),
    y=alt.Y("BTC acumulado:Q", title="BTC acumulado"),
    tooltip=[alt.Tooltip("Data:T"), alt.Tooltip("BTC acumulado:Q", format=",.8f")]
).properties(height=220)

st.altair_chart(val_chart, use_container_width=True)
st.altair_chart(btc_chart, use_container_width=True)

# ----------------------------
# Tabela & Download
# ----------------------------
if mostrar_tabela:
    st.subheader("Tabela de aportes mensais")
    st.dataframe(
        dca.assign(**{
            "Preço BTC (BRL)": dca["Preço BTC (BRL)"].map(lambda x: f"{x:,.2f}"),
            "Aporte (R$)": dca["Aporte (R$)"].map(lambda x: f"{x:,.2f}"),
            "BTC comprado": dca["BTC comprado"].map(lambda x: f"{x:,.8f}"),
            "BTC acumulado": dca["BTC acumulado"].map(lambda x: f"{x:,.8f}"),
            "Aportes acumulados (R$)": dca["Aportes acumulados (R$)"].map(lambda x: f"{x:,.2f}"),
            "Valor de mercado (R$)": dca["Valor de mercado (R$)"].map(lambda x: f"{x:,.2f}"),
            "P&L (R$)": dca["P&L (R$)"].map(lambda x: f"{x:,.2f}"),
            "ROI (%)": dca["ROI (%)"].map(lambda x: f"{x:,.2f}")
        }),
        use_container_width=True,
        hide_index=True,
    )

csv = dca.to_csv(index=False).encode("utf-8-sig")
st.download_button("⬇️ Baixar CSV (aportes mensais)", data=csv, file_name="dca_btc_brl.csv", mime="text/csv")

with st.expander("⚙️ Metodologia"):
    st.markdown("""
- Preço **BTC-BRL** é calculado como `BTC-USD × USDBRL`.
- Aporte executado no **dia D** de cada mês; se não houver cotação nesse dia:
  1) usa o **próximo dia disponível** dentro do mês,  
  2) senão, usa o **último dia disponível** do mês.
- **Preço médio (PM)** = `Aportes acumulados / BTC acumulado`.  
- **Valor atual** usa o último preço disponível da série.
    """)

