import time
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

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

def api_get_raw(path: str, tok: str, params=None) -> bytes:
    s = get_session()
    try:
        r = s.get(
            f"{API_BASE}{path}",
            headers=auth_headers(tok),
            params=params,
            timeout=(10, 300),
        )
    except requests.exceptions.ConnectTimeout:
        st.error("API non raggiungibile (connect timeout).")
        st.stop()
    except requests.exceptions.ReadTimeout:
        st.error("Timeout durante il download (read timeout).")
        st.stop()
    except requests.RequestException as e:
        st.error(f"Errore rete durante download: {e}")
        st.stop()

    if r.status_code == 401:
        st.error("Token non valido o scaduto.")
        st.stop()
    if r.status_code >= 400:
        st.error(f"Errore API {r.status_code}: {r.text[:800]}")
        st.stop()

    return r.content

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

@st.cache_data(ttl=600, show_spinner=False)
def get_anni_inserimento(tok: str):
    js = api_get("/auth/anni-inserimento", tok)
    return [(x["anno"], x["count"]) for x in js.get("items", []) if x.get("anno") is not None]

@st.cache_data(ttl=600, show_spinner=False)
def get_regioni(tok: str):
    js = api_get("/auth/regioni", tok)
    out = []
    for x in js.get("items", []):
        r = x.get("regione")
        c = x.get("count", 0)
        if r:
            out.append((r, int(c) if c is not None else 0))
    return out

# =========================
# SIDEBAR (auth)
# =========================
with st.sidebar:

    if not token:
        st.header("Autenticazione")
        st.warning("Accesso solo tramite WordPress.")
        st.caption("In locale puoi incollare manualmente un token.")
        token = st.text_area("Token (Bearer)", height=120)
        token = (token or "").strip()
    #else:
        #st.success("Sessione autenticata via WordPress")

    st.divider()

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
# FACETS (cached) - con conteggi
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def get_province_with_counts(tok: str):
    js = api_get("/auth/province", tok)
    out = []
    for x in js.get("items", []):
        p = x.get("provincia")
        c = x.get("count", 0)
        if p:
            out.append((p, int(c) if c is not None else 0))
    return out

@st.cache_data(ttl=600, show_spinner=False)
def get_comuni_for_prov_with_counts(tok: str, prov: str):
    js = api_get("/auth/comuni", tok, params={"provincia": prov})
    out = []
    for x in js.get("items", []):
        c = x.get("comune")
        n = x.get("count", 0)
        if c:
            out.append((c, int(n) if n is not None else 0))
    return out

@st.cache_data(ttl=600, show_spinner=False)
def get_province_nascita_with_counts(tok: str):
    js = api_get("/auth/province-nascita", tok)
    out = []
    for x in js.get("items", []):
        p = x.get("prov_nascita")
        c = x.get("count", 0)
        if p:
            out.append((p, int(c) if c is not None else 0))
    return out

@st.cache_data(ttl=600, show_spinner=False)
def get_comuni_nascita_for_prov_with_counts(tok: str, prov_n: str):
    js = api_get("/auth/comuni-nascita", tok, params={"prov_nascita": prov_n})
    out = []
    for x in js.get("items", []):
        c = x.get("comune_nascita")
        n = x.get("count", 0)
        if c:
            out.append((c, int(n) if n is not None else 0))
    return out
    
@st.cache_data(ttl=30, show_spinner=False)
def get_gg_fasce(tok: str, params: dict):
    p = dict(params)
    p.pop("limit", None)
    p.pop("offset", None)
    p.pop("gg_fascia", None)  # vogliamo il totale complessivo
    return api_get("/auth/gg-fasce", tok, params=p)

# =========================
# COUNT totale (cached)
# =========================
@st.cache_data(ttl=30, show_spinner=False)
def cached_count(tok: str, params: dict):
    # rende hashabile per la cache
    safe = {}
    for k, v in params.items():
        safe[k] = tuple(v) if isinstance(v, list) else v
    real = {k: (list(v) if isinstance(v, tuple) else v) for k, v in safe.items()}
    js = api_get("/auth/count", tok, params=real)
    return int(js.get("total", 0))

# =========================
# FILTRI (sidebar)
# =========================
with st.sidebar:
    st.header("Filtri")
    
    # 6) Regione: filtro regione
    reg_items = get_regioni(token)

    selected_region_items = st.multiselect(
        "Regione",
        options=reg_items,
        default=[],
        format_func=lambda t: f"{t[0]} ({t[1]:,})" if t[1] else f"{t[0]}",
    )
    selected_region = [r for (r, _) in selected_region_items]

    # 1) Residenza: Province (con count)
    prov_items = get_province_with_counts(token)
    selected_province_items = st.multiselect(
        "Provincia",
        options=prov_items,
        default=[],
        format_func=lambda t: f"{t[0]} ({t[1]:,})",
    )
    selected_province = [p for (p, _) in selected_province_items]

    # 2) Residenza: Comuni (dipende dalle province selezionate) + count
    comuni_items = []
    if selected_province:
        seen = {}
        for p in selected_province:
            for c, n in get_comuni_for_prov_with_counts(token, p):
                # se un comune appare in più province (raro), sommo i count per presentazione
                seen[c] = seen.get(c, 0) + int(n)
        comuni_items = sorted(seen.items(), key=lambda x: x[0])

    selected_comuni_items = st.multiselect(
        "Comune",
        options=comuni_items,
        default=[],
        format_func=lambda t: f"{t[0]} ({t[1]:,})",
    )
    selected_comuni = [c for (c, _) in selected_comuni_items]

    st.divider()

    # 3) Prima definisco sesso/nazionalità (così posso usarli subito dopo senza NameError)
    sex_choice = st.selectbox("Sesso", ["Tutti", "Maschi", "Femmine"], index=0)
    nat_choice = st.selectbox("Italiano / Estero (Prov. nascita = EE)", ["Tutti", "Italiano", "Estero"], index=0)
    
    st.divider()

    eta_options = [
        "≤ 20",
        "21–40",
        "41–60",
        "> 60",
    ]
    selected_eta_labels = st.multiselect(
        "Fascia di età",
        options=eta_options,
        default=[],
    )

    eta_map = {
        "≤ 20": "LE20",
        "21–40": "21_40",
        "41–60": "41_60",
        "> 60": "GT60",
    }
    selected_eta_codes = [eta_map[x] for x in selected_eta_labels]
    
    gg_options = [
        "10 o meno",
        "11–50",
        "51–100",
        "101–150",
        "151–180",
        "Più di 180",
    ]
    selected_gg_labels = st.multiselect(
        "Giornate lavorate (GG TOT)",
        options=gg_options,
        default=[],
    )

    gg_map = {
        "10 o meno": "LE10",
        "11–50": "11_50",
        "51–100": "51_100",
        "101–150": "101_150",
        "151–180": "151_180",
        "Più di 180": "GT180",
    }
    selected_gg_codes = [gg_map[x] for x in selected_gg_labels]

    st.divider()

    # 4) Nascita: la mostro SOLO se nat_choice == "Tutti" (macro-gruppo)
    selected_prov_nasc = []
    selected_com_nasc = []

    prov_n_items = []
    com_n_items = []

    if nat_choice == "Estero":
        st.caption("Estero: Provincia di nascita forzata a EE. Puoi filtrare per Comune di nascita (se presente).")
        # provincia nascita forzata
        selected_prov_nasc = ["EE"]

        # carico i comuni per EE
        seen = {}
        for c, n in get_comuni_nascita_for_prov_with_counts(token, "EE"):
            seen[c] = seen.get(c, 0) + int(n)
        com_n_items = sorted(seen.items(), key=lambda x: x[0])

        selected_com_nasc_items = st.multiselect(
            "Comune di nascita",
            options=com_n_items,
            default=[],
            format_func=lambda t: f"{t[0]} ({t[1]:,})",
        )
        selected_com_nasc = [c for (c, _) in selected_com_nasc_items]

    else:
        # Tutti o Italiano: filtri nascita normali (provincia -> comuni)
        prov_n_items = get_province_nascita_with_counts(token)
        # Se Italiano, rimuovi EE dalle opzioni selezionabili
        if nat_choice == "Italiano":
            prov_n_items = [t for t in prov_n_items if (t[0] or "").upper() != "EE"]
            selected_prov_nasc = [p for p in selected_prov_nasc if p.upper() != "EE"]

        selected_prov_nasc_items = st.multiselect(
            "Provincia di nascita",
            options=prov_n_items,
            default=[],
            format_func=lambda t: f"{t[0]} ({t[1]:,})",
        )
        selected_prov_nasc = [p for (p, _) in selected_prov_nasc_items]

        if selected_prov_nasc:
            seen = {}
            for p in selected_prov_nasc:
                for c, n in get_comuni_nascita_for_prov_with_counts(token, p):
                    seen[c] = seen.get(c, 0) + int(n)
            com_n_items = sorted(seen.items(), key=lambda x: x[0])

        selected_com_nasc_items = st.multiselect(
            "Comune di nascita",
            options=com_n_items,
            default=[],
            format_func=lambda t: f"{t[0]} ({t[1]:,})",
        )
        selected_com_nasc = [c for (c, _) in selected_com_nasc_items]

    st.divider()
    
    # 5) Anno inserimento: filtro per anno inserimento
    anni_items = get_anni_inserimento(token)
    selected_anni_items = st.multiselect(
        "Anno inserimento",
        options=anni_items,
        default=[],
        format_func=lambda t: f"{t[0]} ({t[1]:,})",
    )
    selected_anni = [a for (a, _) in selected_anni_items]
    
# =========================
# PAGINAZIONE
# =========================

    st.divider()
    
    st.header("Paginazione")

    page_size = st.selectbox(
        "Righe per pagina",
        options=[50, 100, 200, 500, 1000],
        index=1,
    )
    page_number = st.number_input("Pagina", min_value=0, value=0, step=1)

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
            anno = datetime.now().year - 1
            df_x["anno_inserimento"] = 2024
            csv_bytes = df_x.to_csv(index=False).encode("utf-8")

        with st.spinner("Invio CSV al backend (job async)"):
            files = {"file": ("elenchi.csv", csv_bytes, "text/csv")}
            res = api_post_multipart("/admin/import", token, files=files, data={"mode": mode})

        job_id = res.get("job_id")
        st.success(f"Import avviato. job_id = {job_id}")

        if job_id:
            st.write("Stato import (polling):")
            status_box = st.empty()

            for _ in range(120):
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

#regione
if selected_region:
    params["regione"] = selected_region

# residenza
if selected_province:
    params["provincia"] = selected_province
if selected_comuni:
    params["comune"] = selected_comuni

# nascita (solo se nat_choice == Tutti)
if selected_prov_nasc:
    params["prov_nascita"] = selected_prov_nasc
if selected_com_nasc:
    params["com_nascita"] = selected_com_nasc

# sesso
if sex_choice == "Maschi":
    params["sesso"] = "M"
elif sex_choice == "Femmine":
    params["sesso"] = "F"

# italiano/estero (macro)
if nat_choice == "Estero":
    params["nato_estero"] = True
elif nat_choice == "Italiano":
    params["nato_estero"] = False
    
#anno di inserimento
if selected_anni:
    params["anno_ins"] = selected_anni
    
# fascia età
if selected_eta_codes:
    params["eta_fascia"] = selected_eta_codes

if selected_gg_codes:
    params["gg_fascia"] = selected_gg_codes

# Totale righe aggiornato (senza limit/offset)
count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
total_rows = cached_count(token, count_params)
st.write(f"Totale righe trovate (con questi filtri): {total_rows:,}")

with st.spinner("Caricamento dati..."):
    data = api_get("/auth/search", token, params=params)

items = data.get("items", [])
df = pd.DataFrame(items)

# Rimuovi solo dalla visualizzazione (resta nel backend per filtri/export)
df_view = df.drop(columns=["anno_inserimento"], errors="ignore")

st.divider()
st.subheader("Risultati")

st.write(f"Record in pagina: {len(df_view):,} (righe per pagina={page_size}, pagina={page_number})")

if df_view.empty:
    st.warning("Nessun record trovato con i filtri correnti.")
else:
    # =========================
    # DOWNLOAD: regole
    # - admin: sempre (anche nazionale)
    # - non-admin: solo se filtro Regione attivo ed è la sua
    # =========================
    is_admin = (role == "administrator")

    can_download = False
    if is_admin:
        can_download = True
    else:
        can_download = (len(selected_region) == 1 and selected_region[0] == (regione or "").upper())

    if df_view.empty:
        st.warning("Nessun record trovato con i filtri correnti.")
    else:
        # =========================
        # DOWNLOAD: regole
        # - admin: sempre (anche nazionale)
        # - non-admin: solo se filtro Regione attivo ed è la sua
        # =========================
        is_admin = (role == "administrator")

        can_download = False
        if is_admin:
            can_download = True
        else:
            can_download = (len(selected_region) == 1 and selected_region[0] == (regione or "").upper())

        # 1) TABella: sempre visibile
        if is_admin or can_download:
            # toolbar ok (admin può scaricare anche nazionale)
            st.dataframe(df_view, width="stretch", height=600)
        else:
            # NO toolbar => NO download
            st.caption("Download disabilitato: per abilitarlo devi filtrare per Regione (la tua).")
            st.table(df_view)
        st.subheader("Distribuzione giornate lavorate (GG TOT)")

        gg_js = get_gg_fasce(token, params)
        total = gg_js["total"]
        counts = gg_js["counts"]

        labels = {
            "LE10": "10 o meno",
            "11_50": "11–50",
            "51_100": "51–100",
            "101_150": "101–150",
            "151_180": "151–180",
            "GT180": "Più di 180",
        }

        data = {labels[k]: v for k, v in counts.items() if v > 0}

        if total == 0:
            st.caption("Nessun dato disponibile con i filtri correnti.")
        else:

            df_pie = pd.DataFrame({
                "Fascia": list(data.keys()),
                "Conteggio": list(data.values())
            })

            fig = px.pie(
                df_pie,
                names="Fascia",
                values="Conteggio",
                hole=0.4
            )

            fig.update_traces(textinfo="percent+label")

            st.plotly_chart(fig, width="stretch")
            st.caption(f"Totale considerato: {total:,}")

        # 2) Download CSV completo (solo se consentito)
        if can_download:
            export_params = dict(params)
            export_params.pop("limit", None)
            export_params.pop("offset", None)

            csv_bytes = api_get_raw("/auth/export", token, params=export_params)

            st.download_button(
                "Scarica CSV (tutti i risultati filtrati)",
                data=csv_bytes,
                file_name="elenchi_export.csv",
                mime="text/csv",
            )
            