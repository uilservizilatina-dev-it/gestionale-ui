import time
import io
import requests
import pandas as pd
import streamlit as st

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="Gestionale Elenchi", layout="wide")

API_BASE = st.secrets.get("API_BASE", "http://localhost:8000")
token = (st.query_params.get("token", "") or "").strip()

st.title("Gestionale Elenchi")
st.caption("Consultazione elenchi – accesso riservato (WordPress)")

# =========================
# HTTP session + API helpers
# =========================
@st.cache_resource
def get_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def auth_headers(tok: str):
    return {"Authorization": f"Bearer {tok.strip()}"}

def api_healthcheck():
    s = get_session()
    try:
        r = s.get(f"{API_BASE}/health", timeout=(3, 6))
        return r.status_code == 200
    except Exception:
        return False

def api_get(path: str, tok: str, params=None):
    s = get_session()
    try:
        r = s.get(
            f"{API_BASE}{path}",
            headers=auth_headers(tok),
            params=params,
            timeout=(5, 30),
        )
    except requests.exceptions.ConnectTimeout:
        st.error("API non raggiungibile (connect timeout). Controlla API_BASE / DNS / host.")
        st.stop()
    except requests.exceptions.ReadTimeout:
        st.error("API raggiunta ma non risponde in tempo (read timeout). Probabile cold-start o backend bloccato.")
        st.stop()
    except requests.RequestException as e:
        st.error(f"Errore rete chiamando l’API: {e}")
        st.stop()

    if r.status_code == 401:
        st.error("Token non valido o scaduto.")
        st.stop()
    if r.status_code >= 400:
        st.error(f"Errore API {r.status_code}: {r.text[:800]}")
        st.stop()
    return r.json()

def api_post_multipart(path: str, tok: str, files=None, data=None):
    s = get_session()
    try:
        r = s.post(
            f"{API_BASE}{path}",
            headers=auth_headers(tok),
            files=files,
            data=data,
            timeout=(10, 60),
        )
    except requests.exceptions.ConnectTimeout:
        st.error("API non raggiungibile (connect timeout).")
        st.stop()
    except requests.exceptions.ReadTimeout:
        st.error("Timeout durante la POST (read timeout). Import potrebbe essere partito o backend bloccato.")
        st.stop()
    except requests.RequestException as e:
        st.error(f"Errore rete durante POST: {e}")
        st.stop()

    if r.status_code == 401:
        st.error("Token non valido o scaduto.")
        st.stop()
    if r.status_code >= 400:
        st.error(f"Errore API {r.status_code}: {r.text[:800]}")
        st.stop()
    return r.json()

# =========================
# SIDEBAR (auth + paginazione)
# =========================
with st.sidebar:
    st.header("Autenticazione")

    if not token:
        st.warning("Accesso solo tramite WordPress.")
        st.caption("In locale puoi incollare manualmente un token.")
        token = st.text_area("Token (Bearer)", height=120)
        token = (token or "").strip()
    else:
        st.success("Sessione autenticata via WordPress")

    st.divider()
    st.header("Paginazione")

    page_size = st.selectbox(
        "Righe per pagina",
        options=[50, 100, 200, 500, 1000],
        index=1,
    )
    page_number = st.number_input("Pagina", min_value=0, value=0, step=1)

if not token:
    st.warning("Inserisci un token valido per iniziare.")
    st.stop()

if not api_healthcheck():
    st.error("Backend API non raggiungibile o non pronto. (health fallita)")
    st.stop()

# =========================
# WHOAMI (cached)
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def cached_whoami(tok: str):
    return api_get("/auth/whoami", tok)

who = cached_whoami(token)
role = (who.get("role") or "").lower()
regione = who.get("regione")

st.info(f"Utente: {who.get('username')} — Ruolo: {role or 'n/a'} — Regione: {regione or 'n/a'}")

# =========================
# FACETS (cached)
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def get_province(tok: str):
    js = api_get("/auth/province", tok)
    return [x["provincia"] for x in js.get("items", []) if x.get("provincia")]

@st.cache_data(ttl=600, show_spinner=False)
def get_comuni_for_prov(tok: str, prov: str):
    js = api_get("/auth/comuni", tok, params={"provincia": prov})
    return [x["comune"] for x in js.get("items", []) if x.get("comune")]

@st.cache_data(ttl=600, show_spinner=False)
def get_province_nascita(tok: str):
    js = api_get("/auth/province-nascita", tok)
    return [x["prov_nascita"] for x in js.get("items", []) if x.get("prov_nascita")]

@st.cache_data(ttl=600, show_spinner=False)
def get_comuni_nascita_for_prov(tok: str, prov_n: str):
    js = api_get("/auth/comuni-nascita", tok, params={"prov_nascita": prov_n})
    return [x["comune_nascita"] for x in js.get("items", []) if x.get("comune_nascita")]

# =========================
# FILTRI (sidebar)
# =========================
with st.sidebar:
    st.divider()
    st.header("Filtri")

    province_opts = get_province(token)
    selected_province = st.multiselect("Provincia", options=province_opts, default=[])

    comuni_opts = []
    if selected_province:
        s = set()
        for p in selected_province:
            for c in get_comuni_for_prov(token, p):
                s.add(c)
        comuni_opts = sorted(s)
    selected_comuni = st.multiselect("Comune", options=comuni_opts, default=[])

    st.divider()

    prov_n_opts = get_province_nascita(token)
    selected_prov_nasc = st.multiselect("Provincia di nascita", options=prov_n_opts, default=[])

    com_n_opts = []
    if selected_prov_nasc:
        s = set()
        for p in selected_prov_nasc:
            for c in get_comuni_nascita_for_prov(token, p):
                s.add(c)
        com_n_opts = sorted(s)
    selected_com_nasc = st.multiselect("Comune di nascita", options=com_n_opts, default=[])

    st.divider()
    sex_choice = st.selectbox("Sesso", ["Tutti", "Maschi", "Femmine"], index=0)
    nat_choice = st.selectbox("Italiano / Estero (Prov. nascita = EE)", ["Tutti", "Italiano", "Estero"], index=0)

# =========================
# ADMIN: Upload Excel -> Import
# =========================
if role == "administrator":
    st.divider()
    st.subheader("Upload Excel (solo Admin)")

    up = st.file_uploader("Carica file Excel (.xlsx)", type=["xlsx"])
    mode = st.selectbox("Modalità import", ["replace"], index=0)

    if up is not None and st.button("Importa nel database"):
        with st.spinner("Conversione Excel → CSV"):
            df_x = pd.read_excel(up, dtype=str)
            csv_bytes = df_x.to_csv(index=False).encode("utf-8")

        with st.spinner("Invio CSV al backend (job async)"):
            files = {"file": ("elenchi.csv", csv_bytes, "text/csv")}
            res = api_post_multipart("/admin/import", token, files=files, data={"mode": mode})

        job_id = res.get("job_id")
        st.success(f"Import avviato. job_id = {job_id}")

        if job_id:
            st.write("Stato import (polling):")
            status_box = st.empty()

            for _ in range(120):  # ~2 minuti (con sleep 1s)
                js = api_get("/admin/import/status", token, params={"job_id": job_id})
                status = js.get("status")
                inserted = js.get("inserted_rows")
                err = js.get("error")

                status_box.info(f"status={status} — inserted_rows={inserted} — error={err}")

                if status in ("done", "error"):
                    break
                time.sleep(1)

# =========================
# QUERY /auth/search
# =========================
offset = int(page_number) * int(page_size)

params = {
    "limit": int(page_size),
    "offset": int(offset),
}

if selected_province:
    params["provincia"] = selected_province
if selected_comuni:
    params["comune"] = selected_comuni

if selected_prov_nasc:
    params["prov_nascita"] = selected_prov_nasc
if selected_com_nasc:
    params["com_nascita"] = selected_com_nasc

if sex_choice == "Maschi":
    params["sesso"] = "M"
elif sex_choice == "Femmine":
    params["sesso"] = "F"

if nat_choice == "Estero":
    params["nato_estero"] = True
elif nat_choice == "Italiano":
    params["nato_estero"] = False

with st.spinner("Caricamento dati..."):
    data = api_get("/auth/search", token, params=params)

items = data.get("items", [])
df = pd.DataFrame(items)

st.divider()
st.subheader("Risultati")

st.write(f"Record in pagina: {len(df):,} (page_size={page_size}, page={page_number})")

if df.empty:
    st.warning("Nessun record trovato con i filtri correnti.")
else:
    st.dataframe(df, use_container_width=True)
