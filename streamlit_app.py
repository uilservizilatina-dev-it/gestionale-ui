import requests
import pandas as pd
import streamlit as st

API_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Gestionale Elenchi",
    layout="wide"
)

token = st.query_params.get("token", "")
API_BASE = st.secrets["API_BASE"]


st.title("Gestionale Elenchi")
st.caption("Consultazione elenchi – accesso riservato (WordPress)")

# =========================
# SIDEBAR (filtri + auth)
# =========================
with st.sidebar:
    st.header("Autenticazione")
    token = st.text_area(
        "Token (Bearer)",
        height=120,
        help="In produzione arriverà automaticamente da WordPress"
    )

    st.divider()
    st.header("Filtri")

    provincia = st.text_input("Provincia").strip().upper() or None
    comune = st.text_input("Comune").strip().upper() or None
    codice_fiscale = st.text_input("Codice Fiscale").strip().upper() or None

    st.divider()
    st.header("Paginazione")

    page_size = st.selectbox(
        "Righe per pagina",
        options=[50, 100, 200, 500, 1000],
        index=1
    )

    page_number = st.number_input(
        "Pagina",
        min_value=0,
        value=0,
        step=1
    )

def auth_headers(tok: str):
    return {"Authorization": f"Bearer {tok.strip()}"}

def api_get(path: str, tok: str, params=None):
    r = requests.get(
        f"{API_BASE}{path}",
        headers=auth_headers(tok),
        params=params,
        timeout=60
    )
    if r.status_code == 401:
        st.error("Token non valido o scaduto.")
        st.stop()
    if r.status_code >= 400:
        st.error(f"Errore {r.status_code}: {r.text}")
        st.stop()
    return r.json()

if not token.strip():
    st.warning("Inserisci un token valido per iniziare.")
    st.stop()

# =========================
# WHOAMI
# =========================
who = api_get("/auth/whoami", token)

st.success(
    f"Utente: **{who['username']}** | "
    f"Ruolo: **{who['role']}** | "
    f"Regione applicata: **{who['regione']}**"
)

# =========================
# QUERY
# =========================
offset = page_number * page_size

params = {
    "provincia": provincia,
    "comune": comune,
    "codice_fiscale": codice_fiscale,
    "limit": page_size,
    "offset": offset,
}
params = {k: v for k, v in params.items() if v is not None}

data = api_get("/auth/search", token, params=params)
items = data.get("items", [])

st.subheader("Risultati")

if not items:
    st.info("Nessun risultato per i filtri selezionati.")
    st.stop()

df = pd.DataFrame(items)

st.write(
    f"Pagina **{page_number}** – "
    f"Righe mostrate: **{len(df)}** – "
    f"Regione (backend): **{data['regione']}**"
)

# =========================
# TABELLA (FULL WIDTH)
# =========================
st.dataframe(
    df,
    use_container_width=True,
    height=600
)

# =========================
# GRAFICO
# =========================
st.subheader("Distribuzione GG TOT (pagina corrente)")

if "gg_tot" in df.columns:
    gg = df["gg_tot"].dropna()
    if not gg.empty:
        st.bar_chart(gg.value_counts().sort_index())
    else:
        st.caption("Nessun valore GG TOT disponibile.")
