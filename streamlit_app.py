import time
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import os

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime

st.set_page_config(page_title="Gestionale Elenchi", layout="wide")

HIDE_DF_TOOLBAR_CSS = """
<style>
/* Toolbar “overlay” (download/search/fullscreen) in varie versioni Streamlit */
div[data-testid="stElementToolbar"],
div[data-testid="stToolbar"],
div[data-testid="stToolbarActions"],
div[data-testid="stElementToolbarButton"],
div[data-testid="stElementToolbarButton"] > button {
  display: none !important;
  visibility: hidden !important;
  opacity: 0 !important;
  height: 0 !important;
}

/* Variante: alcuni build usano classi diverse */
.stElementToolbar,
.stToolbar {
  display: none !important;
  visibility: hidden !important;
}
</style>
"""


API_BASE = os.getenv("API_BASE", "http://localhost:8000")
# =========================
# TOKEN HANDLING SICURO
# =========================

# 1) Se arriva da URL, salvalo in session_state
if "token" in st.query_params:
    incoming = (st.query_params.get("token", "") or "").strip()
    if incoming:
        st.session_state["auth_token"] = incoming

    # 2) Rimuovi subito il token dalla URL
    st.query_params.clear()

# 3) Usa sempre il token dalla sessione
token = st.session_state.get("auth_token", "")

if not token:
    st.error("Sessione non valida. Accedi dal portale.")
    st.stop()

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

scope_level = (who.get("scope_level") or "").lower().strip()
scope_values_csv = (who.get("scope_values") or "").strip()
scope_values = [v.strip().upper() for v in scope_values_csv.split(",") if v.strip()]

# =========================
# RUOLO / REGIONE (per UI e regole)
# =========================
is_admin = (role == "administrator")
user_region = (regione or "").upper()

st.info(f"Utente: {who.get('username')} — Ruolo: {role or 'n/a'} — Regione: {regione or 'n/a'}")

# =========================
# FACETS (cached) - con conteggi
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def get_province_with_counts(tok: str, region_filter: tuple[str, ...]):
    params = {}
    if region_filter:
        params["regione"] = list(region_filter)
    js = api_get("/auth/province", tok, params=params)

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
    # p.pop("limit", None)
    # p.pop("offset", None)
    return api_get("/auth/gg-fasce", tok, params=p)

@st.cache_data(ttl=30, show_spinner=False)
def get_eta_fasce(tok: str, params: dict):
    p = dict(params)
    return api_get("/auth/eta-fasce", tok, params=p)

@st.cache_data(ttl=30, show_spinner=False)
def get_stats_sex(tok: str, params: dict):
    p = dict(params)
    # p.pop("limit", None)
    # p.pop("offset", None)
    return api_get("/auth/stats-sex", tok, params=p)

@st.cache_data(ttl=30, show_spinner=False)
def get_stats_nat(tok: str, params: dict):
    p = dict(params)
    # p.pop("limit", None)
    # p.pop("offset", None)
    return api_get("/auth/stats-nat", tok, params=p)

# =========================
# COUNT totale (cached)
# =========================
@st.cache_data(ttl=30, show_spinner=False)
def cached_count(tok: str, params: dict):
    safe = {}
    for k, v in params.items():
        safe[k] = tuple(v) if isinstance(v, list) else v
    real = {k: (list(v) if isinstance(v, tuple) else v) for k, v in safe.items()}
    js = api_get("/auth/count", tok, params=real)
    return {
        "total": int(js.get("total", 0)),
        "total_gg": int(js.get("total_gg", 0)),
    }

# =========================
# FILTRI (sidebar)
# =========================
def on_region_change():
    # quando cambia regione: azzera provincia + comune
    st.session_state["provincia_sel"] = []
    st.session_state["comune_sel"] = []

    raw = st.session_state.get("regione_sel_items", [])  # lista di tuple: (regione, count)
    reg_list = []
    for item in raw:
        if isinstance(item, (tuple, list)) and item:
            reg_list.append(str(item[0]).upper())
        else:
            reg_list.append(str(item).upper())

    st.session_state["_last_region_key"] = tuple(sorted(reg_list))
    st.session_state["_last_province_key"] = tuple()

def on_province_change():
    # quando cambia provincia: azzera comune
    st.session_state["comune_sel"] = []

    raw = st.session_state.get("provincia_sel", [])  # lista di tuple: (provincia, count)
    prov_list = []
    for item in raw:
        # item può essere tuple (provincia,count) oppure string (in futuro)
        if isinstance(item, (tuple, list)) and item:
            prov_list.append(str(item[0]).upper())
        else:
            prov_list.append(str(item).upper())

    st.session_state["_last_province_key"] = tuple(sorted(prov_list))
    
with st.sidebar:
    st.header("Filtri")

    # 6) Regione: filtro regione
    reg_items = get_regioni(token)

    if is_admin:
        selected_region_items = st.multiselect(
            "Regione",
            options=reg_items,
            default=[],
            key="regione_sel_items",
            on_change=on_region_change,
            format_func=lambda t: f"{t[0]} ({t[1]:,})" if t[1] else f"{t[0]}",
        )
        selected_region = [r for (r, _) in selected_region_items]

    else:
        if scope_level == "regione":
            # multi-regione fissa (da WordPress)
            selected_region = scope_values
            labels = {r: c for (r, c) in reg_items}
            fixed = [f"{r} ({labels.get(r, 0):,})" for r in selected_region]
            st.multiselect("Regione", options=fixed, default=fixed, disabled=True)
        elif scope_level == "provincia" or scope_level == "comune":
            # Regione derivata dallo scope (province/comuni) -> mostrala fissa
            inferred_regions = [r for (r, _) in reg_items]  # già filtrate dal backend in base allo scope
            reg_label = ", ".join(inferred_regions) if inferred_regions else (user_region or "N/A")
            st.caption(f"Regione {reg_label} - Vincolata dal tuo profilo.")
            #st.selectbox("Regione", options=[f"{reg_label} - Vincolata dal tuo profilo."], index=0, disabled=True)

            # come filtro NON serve (scope già restringe)
            selected_region = []
        else:
            # fallback legacy
            selected_region = [user_region]
            count_map = {r: c for (r, c) in reg_items}
            label = f"{user_region} ({count_map.get(user_region, 0):,})" if user_region else "N/A"
            st.selectbox("Regione", options=[label], index=0, disabled=True)

    # 1) Residenza: Province (con count) - DIPENDE dalla Regione selezionata
    region_key = tuple(sorted([r.upper() for r in (selected_region or [])]))
    prov_items = get_province_with_counts(token, region_key)

    if (not is_admin) and scope_level == "comune":
        # Provincia derivata dai comuni consentiti -> mostrala fissa, niente filtro
        prov_names = [p for (p, _) in prov_items]
        prov_label = ", ".join(prov_names) if prov_names else "N/A"
        st.caption(f"Provincia {prov_label} - Vincolata dal tuo profilo.")
        #st.selectbox("Provincia", options=[f"{prov_label} - Vincolata dal tuo profilo."], index=0, disabled=True)

        # NON applicare filtro provincia lato UI (lo scope comune già restringe)
        selected_province = []

    elif (not is_admin) and scope_level == "provincia":
        # province fisse da WordPress
        fixed_items = [(p, 0) for p in scope_values]
        st.multiselect(
            "Provincia",
            options=fixed_items,
            default=fixed_items,
            disabled=True,
            format_func=lambda t: t[0]
        )
        selected_province = scope_values

    else:
        selected_province_items = st.multiselect(
            "Provincia",
            options=prov_items,
            key="provincia_sel",
            on_change=on_province_change,
            format_func=lambda t: f"{t[0]} ({t[1]:,})",
        )
        selected_province = [p for (p, _) in selected_province_items]

    comuni_items = []

    if (not is_admin) and scope_level == "comune":
        # lista fissa
        comuni_items = [(c, 0) for c in scope_values]  # count opzionale
        selected_comuni = scope_values
        st.multiselect("Comune", options=comuni_items, default=comuni_items, disabled=True,
                       format_func=lambda t: f"{t[0]}")
    else:
        # logica attuale (dipende da selected_province)
        if selected_province:
            seen = {}
            for p in selected_province:
                for c, n in get_comuni_for_prov_with_counts(token, p):
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
        "≤ 20": "≤20",
        "21–40": "21-40",
        "41–60": "41-60",
        "> 60": ">60",
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
        "10 o meno": "≤10",
        "11–50": "11-50",
        "51–100": "51-100",
        "101–150": "101-150",
        "151–180": "151-180",
        "Più di 180": ">180",
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

    # st.divider()
    #
    # st.header("Paginazione")
    #
    # page_size = st.selectbox(
    #    "Righe per pagina",
    #    options=[50, 100, 200, 500, 1000],
    #    index=1,
    # )
    # page_number = st.number_input("Pagina", min_value=0, value=0, step=1)

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

            # 1) colonne attese dal backend (COPY elenchi(...))
            REQUIRED_COLS = [
                "prov_nascita",
                "comune_nascita",
                "fascia_eta",
                "sesso",
                "fascia_gg",
                "gg_tot",
                "regione",
                "provincia",
                "comune",
            ]

            # 2) check colonne (fallisce subito se manca qualcosa)
            missing = [c for c in REQUIRED_COLS if c not in df_x.columns]
            if missing:
                st.error(f"Excel non valido. Colonne mancanti: {missing}")
                st.stop()

            # 3) tieni solo colonne attese + ordine garantito
            df_x = df_x[REQUIRED_COLS].copy()


            # 4) normalizzazione: vuoti/nan/NULL -> None
            def norm_cell(v):
                if v is None:
                    return None
                s = str(v).strip()
                if s == "" or s.lower() in ("nan", "none", "null"):
                    return None
                return s


            for c in REQUIRED_COLS:
                df_x[c] = df_x[c].map(norm_cell)

            # 5) anno inserimento impostato da script: anno corrente - 1
            current_year = datetime.now().year
            #df_x["anno_inserimento"] = current_year - 1
            df_x["anno_inserimento"] = 2024


            # 6) sesso normalizzato a M/F
            def norm_sex(v):
                if not v:
                    return None
                s = str(v).strip().upper()
                if s in ("M", "MASCHIO", "MALE"):
                    return "M"
                if s in ("F", "FEMMINA", "FEMALE"):
                    return "F"
                return None


            # 7) fascia età normalizzata ai soli valori ammessi dal DB
            def norm_fascia_eta(v):
                if not v:
                    return None
                s = str(v).strip().replace(" ", "")
                mapping = {
                    "≤20": "≤20",
                    "21-40": "21-40",
                    "41-60": "41-60",
                    ">60": ">60",
                }
                return mapping.get(s)


            # 8) fascia giornate normalizzata ai soli valori ammessi dal DB
            def norm_fascia_gg(v):
                if not v:
                    return None
                s = str(v).strip().replace(" ", "")
                mapping = {
                    "≤10": "≤10",
                    "11-50": "11-50",
                    "51-100": "51-100",
                    "101-150": "101-150",
                    "151-180": "151-180",
                    ">180": ">180",
                }
                return mapping.get(s)


            df_x["sesso"] = df_x["sesso"].map(norm_sex)
            df_x["fascia_eta"] = df_x["fascia_eta"].map(norm_fascia_eta)
            df_x["fascia_gg"] = df_x["fascia_gg"].map(norm_fascia_gg)

            invalid_eta = df_x["fascia_eta"].isna().sum()
            invalid_gg = df_x["fascia_gg"].isna().sum()
            invalid_sex = df_x["sesso"].isna().sum()

            if invalid_eta > 0:
                st.error(f"Excel non valido: trovati {invalid_eta} valori non riconosciuti in 'fascia_eta'.")
                st.stop()

            if invalid_gg > 0:
                st.error(f"Excel non valido: trovati {invalid_gg} valori non riconosciuti in 'fascia_gg'.")
                st.stop()

            if invalid_sex > 0:
                st.error(f"Excel non valido: trovati {invalid_sex} valori non riconosciuti in 'sesso'.")
                st.stop()

            # 9) campi numerici
            df_x["gg_tot"] = pd.to_numeric(df_x["gg_tot"], errors="coerce")

            # 10) uppercasing su campi territoriali
            for c in ["prov_nascita", "regione", "provincia", "comune", "comune_nascita"]:
                df_x[c] = df_x[c].map(lambda v: v.strip().upper() if isinstance(v, str) and v.strip() else None)

            # 11) validazione finale minima
            invalid_eta = df_x["fascia_eta"].isna().sum()
            invalid_gg = df_x["fascia_gg"].isna().sum()
            invalid_sex = df_x["sesso"].isna().sum()

            if invalid_eta > 0:
                st.error(f"Excel non valido: trovati {invalid_eta} valori non riconosciuti in 'fascia_eta'.")
                st.stop()

            if invalid_gg > 0:
                st.error(f"Excel non valido: trovati {invalid_gg} valori non riconosciuti in 'fascia_gg'.")
                st.stop()

            if invalid_sex > 0:
                st.error(f"Excel non valido: trovati {invalid_sex} valori non riconosciuti in 'sesso'.")
                st.stop()

            # 12) CSV: None -> stringa vuota
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_csv:
                tmp_csv_path = tmp_csv.name

            df_x.to_csv(tmp_csv_path, index=False, encoding="utf-8")

        with st.spinner("Invio CSV al backend (job async)"):
            file_size_mb = os.path.getsize(tmp_csv_path) / (1024 * 1024)
            st.write(f"Dimensione CSV generato: {file_size_mb:.2f} MB")

            with open(tmp_csv_path, "rb") as f:
                files = {"file": ("elenchi.csv", f, "text/csv")}
                res = api_post_multipart("/admin/import", token, files=files, data={"mode": mode})

        try:
            if os.path.exists(tmp_csv_path):
                os.remove(tmp_csv_path)
        except Exception:
            pass
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
# offset = int(page_number) * int(page_size)
# 
# params = {
#     "limit": int(page_size),
#     "offset": int(offset),
# }

# Parametri base (solo filtri, niente paginazione)
params = {}

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
# count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
count_params = dict(params)
count_info = cached_count(token, count_params)
total_rows = count_info["total"]
total_gg = count_info["total_gg"]

st.write(
    f"Totale braccianti (con questi filtri attivi): {total_rows:,} "
    f"— Totale giornate lavorate: {total_gg:,}"
)

if total_rows == 0:
    st.warning("Nessun bracciante trovato con i filtri correnti.")
    st.stop()

# =========================
# PALETTE UILA
# =========================
UILA_BLUE = "#123B7A"        # blu istituzionale
UILA_AZURE = "#7DB7E5"       # azzurro chiaro coerente col logo
UILA_GREEN = "#2F8F46"       # verde UILA
UILA_GREEN_LIGHT = "#7BCB8C" # verde chiaro
UILA_RED = "#C62828"         # rosso UILA, da usare come accento
UILA_RED_LIGHT = "#E57373"   # rosso chiaro

# =========================
# COLORI FISSI GRAFICI
# =========================
SEX_COLOR_MAP = {
    "Maschi": UILA_AZURE,
    "Femmine": UILA_BLUE,
}

NAT_COLOR_MAP = {
    "Italiani": UILA_GREEN,
    "Esteri": UILA_BLUE,
}

GG_COLOR_MAP = {
    "10 o meno": UILA_AZURE,
    "11–50": "#5FA6DD",
    "51–100": UILA_BLUE,
    "101–150": "#4F8F3A",
    "151–180": UILA_GREEN,
    "Più di 180": UILA_RED,
}

ETA_COLOR_MAP = {
    "≤ 20": UILA_AZURE,
    "21–40": UILA_GREEN_LIGHT,
    "41–60": UILA_GREEN,
    "> 60": UILA_RED,
}
# with st.spinner("Caricamento dati..."):
#    data = api_get("/auth/search", token, params=params)

# items = data.get("items", [])
# df = pd.DataFrame(items)
# 
# # Rimuovi solo dalla visualizzazione (resta nel backend per filtri/export)
# df_view = df.drop(columns=["anno_inserimento"], errors="ignore")
# 
# if df_view.empty:
#     st.warning("Nessun bracciante trovato con i filtri correnti.")
# else:
st.divider()
st.subheader("Statistiche")

sex_stats = get_stats_sex(token, params)
nat_stats = get_stats_nat(token, params)
gg_js = get_gg_fasce(token, params)
eta_js = get_eta_fasce(token, params)

# =========================
# RIGA 1: sesso
# =========================
c1, c2 = st.columns(2)

with c1:
    df1 = pd.DataFrame({
        "CategoriaBase": ["Maschi", "Femmine"],
        "Valore": [sex_stats["count"]["M"], sex_stats["count"]["F"]],
    })

    df1["CategoriaLabel"] = df1.apply(
        lambda r: f"{r['CategoriaBase']} ({int(r['Valore']):,})", axis=1
    )

    sex_color_map_labels = {
        row["CategoriaLabel"]: SEX_COLOR_MAP[row["CategoriaBase"]]
        for _, row in df1.iterrows()
    }

    fig1 = px.pie(
        df1,
        names="CategoriaLabel",
        values="Valore",
        color="CategoriaLabel",
        color_discrete_map=sex_color_map_labels,
        hole=0.4,
        title="Lavoratori per sesso",
        custom_data=["CategoriaBase"],
    )

    fig1.update_traces(
        texttemplate="%{customdata[0]}<br>%{percent}",
        textinfo="none"
    )

    st.plotly_chart(fig1, width="stretch")

with c2:
    df2 = pd.DataFrame({
        "CategoriaBase": ["Maschi", "Femmine"],
        "Valore": [sex_stats["gg_tot"]["M"], sex_stats["gg_tot"]["F"]],
    })

    df2["CategoriaLabel"] = df2.apply(
        lambda r: f"{r['CategoriaBase']} ({int(r['Valore']):,})", axis=1
    )

    sex_color_map_labels_2 = {
        row["CategoriaLabel"]: SEX_COLOR_MAP[row["CategoriaBase"]]
        for _, row in df2.iterrows()
    }

    fig2 = px.pie(
        df2,
        names="CategoriaLabel",
        values="Valore",
        color="CategoriaLabel",
        color_discrete_map=sex_color_map_labels_2,
        hole=0.4,
        title="Giornate lavorate per sesso (GG TOT)",
        custom_data=["CategoriaBase"],
    )

    fig2.update_traces(
        texttemplate="%{customdata[0]}<br>%{percent}",
        textinfo="none"
    )

    st.plotly_chart(fig2, width="stretch")

# =========================
# RIGA 2: italiani / esteri
# =========================
c3, c4 = st.columns(2)

with c3:
    df3 = pd.DataFrame({
        "CategoriaBase": ["Italiani", "Esteri"],
        "Valore": [nat_stats["count"]["ITALIANI"], nat_stats["count"]["ESTERI"]],
    })

    df3["CategoriaLabel"] = df3.apply(
        lambda r: f"{r['CategoriaBase']} ({int(r['Valore']):,})", axis=1
    )

    nat_color_map_labels = {
        row["CategoriaLabel"]: NAT_COLOR_MAP[row["CategoriaBase"]]
        for _, row in df3.iterrows()
    }

    fig3 = px.pie(
        df3,
        names="CategoriaLabel",
        values="Valore",
        color="CategoriaLabel",
        color_discrete_map=nat_color_map_labels,
        hole=0.4,
        title="Lavoratori italiani vs esteri",
        custom_data=["CategoriaBase"],
    )

    fig3.update_traces(
        texttemplate="%{customdata[0]}<br>%{percent}",
        textinfo="none"
    )

    st.plotly_chart(fig3, width="stretch")

with c4:
    df4 = pd.DataFrame({
        "CategoriaBase": ["Italiani", "Esteri"],
        "Valore": [nat_stats["gg_tot"]["ITALIANI"], nat_stats["gg_tot"]["ESTERI"]],
    })

    df4["CategoriaLabel"] = df4.apply(
        lambda r: f"{r['CategoriaBase']} ({int(r['Valore']):,})", axis=1
    )

    nat_color_map_labels_2 = {
        row["CategoriaLabel"]: NAT_COLOR_MAP[row["CategoriaBase"]]
        for _, row in df4.iterrows()
    }

    fig4 = px.pie(
        df4,
        names="CategoriaLabel",
        values="Valore",
        color="CategoriaLabel",
        color_discrete_map=nat_color_map_labels_2,
        hole=0.4,
        title="Giornate lavorate italiani vs esteri (GG TOT)",
        custom_data=["CategoriaBase"],
    )

    fig4.update_traces(
        texttemplate="%{customdata[0]}<br>%{percent}",
        textinfo="none"
    )

    st.plotly_chart(fig4, width="stretch")

# =========================
# RIGA 3: distribuzioni
# =========================
c5, c6 = st.columns(2)

with c5:
    gg_total = gg_js.get("total", 0)
    gg_counts = gg_js.get("counts", {}) or {}

    gg_order = ["10 o meno", "11–50", "51–100", "101–150", "151–180", "Più di 180"]

    gg_labels = {
        "LE10": "10 o meno",
        "11_50": "11–50",
        "51_100": "51–100",
        "101_150": "101–150",
        "151_180": "151–180",
        "GT180": "Più di 180",
    }

    gg_data_map = {gg_labels[k]: int(v) for k, v in gg_counts.items() if int(v or 0) > 0}

    ordered_gg_labels = [label for label in gg_order if label in gg_data_map]
    ordered_gg_values = [gg_data_map[label] for label in ordered_gg_labels]

    if gg_total == 0 or not ordered_gg_labels:
        st.caption("Nessun dato disponibile con i filtri correnti.")
    else:
        df_gg = pd.DataFrame({
            "CategoriaBase": ordered_gg_labels,
            "Valore": ordered_gg_values
        })

        df_gg["CategoriaLabel"] = df_gg.apply(
            lambda r: f"{r['CategoriaBase']} ({int(r['Valore']):,})", axis=1
        )

        gg_color_map_labels = {
            row["CategoriaLabel"]: GG_COLOR_MAP[row["CategoriaBase"]]
            for _, row in df_gg.iterrows()
        }

        ordered_gg_labels_full = df_gg["CategoriaLabel"].tolist()

        fig_gg = px.pie(
            df_gg,
            names="CategoriaLabel",
            values="Valore",
            color="CategoriaLabel",
            color_discrete_map=gg_color_map_labels,
            category_orders={"CategoriaLabel": ordered_gg_labels_full},
            hole=0.4,
            title="Distribuzione giornate lavorate (GG TOT)",
            custom_data=["CategoriaBase"],
        )

        fig_gg.update_traces(
            texttemplate="%{customdata[0]}<br>%{percent}",
            textinfo="none"
        )

        st.plotly_chart(fig_gg, width="stretch")

with c6:
    eta_total = eta_js.get("total", 0)
    eta_counts = eta_js.get("counts", {}) or {}

    eta_order = ["≤ 20", "21–40", "41–60", "> 60"]

    eta_labels = {
        "LE20": "≤ 20",
        "21_40": "21–40",
        "41_60": "41–60",
        "GT60": "> 60",
    }

    eta_data_map = {eta_labels[k]: int(v) for k, v in eta_counts.items() if int(v or 0) > 0}

    ordered_eta_labels = [label for label in eta_order if label in eta_data_map]
    ordered_eta_values = [eta_data_map[label] for label in ordered_eta_labels]

    if eta_total == 0 or not ordered_eta_labels:
        st.caption("Nessun dato disponibile con i filtri correnti.")
    else:
        df_eta = pd.DataFrame({
            "CategoriaBase": ordered_eta_labels,
            "Valore": ordered_eta_values
        })

        df_eta["CategoriaLabel"] = df_eta.apply(
            lambda r: f"{r['CategoriaBase']} ({int(r['Valore']):,})", axis=1
        )

        eta_color_map_labels = {
            row["CategoriaLabel"]: ETA_COLOR_MAP[row["CategoriaBase"]]
            for _, row in df_eta.iterrows()
        }

        ordered_eta_labels_full = df_eta["CategoriaLabel"].tolist()

        fig_eta = px.pie(
            df_eta,
            names="CategoriaLabel",
            values="Valore",
            color="CategoriaLabel",
            color_discrete_map=eta_color_map_labels,
            category_orders={"CategoriaLabel": ordered_eta_labels_full},
            hole=0.4,
            title="Distribuzione fasce d'età",
            custom_data=["CategoriaBase"],
        )

        fig_eta.update_traces(
            texttemplate="%{customdata[0]}<br>%{percent}",
            textinfo="none"
        )

        st.plotly_chart(fig_eta, width="stretch")
    
# st.divider()        
# st.subheader("Tabella")

# st.write(f"Righe in pagina: {len(df_view):,} (righe per pagina = {page_size}, pagina numero = {page_number})")

    # =========================
    # DOWNLOAD: regole
    # - admin: sempre (anche nazionale)
    # - non-admin: solo se filtro Regione attivo ed è la sua
    # =========================
    # is_admin = (role == "administrator")
    # 
    # if is_admin:
    #     can_download = True
    # else:
    #     can_download = (len(selected_region) == 1 and selected_region[0] == (regione or "").upper())
    # 
    # # 1) TABella: SEMPRE dataframe (scroll interno)
    # # Se non può scaricare → nascondo toolbar con CSS
    # if not (is_admin or can_download):
    #     st.markdown(HIDE_DF_TOOLBAR_CSS, unsafe_allow_html=True)
    #     st.caption("Download disabilitato: per abilitarlo devi filtrare per Regione (la tua).")
    # 
    # st.dataframe(
    #     df_view,
    #     width="stretch",
    #     height=600
    # )
    # 
    # # 3) Download CSV completo (solo se consentito)
    # if can_download:
    #     export_params = dict(params)
    #     export_params.pop("limit", None)
    #     export_params.pop("offset", None)
    # 
    #     csv_bytes = api_get_raw("/auth/export", token, params=export_params)
    # 
    #     st.download_button(
    #         "Scarica CSV (tutti i risultati filtrati)",
    #         data=csv_bytes,
    #         file_name="elenchi_export.csv",
    #         mime="text/csv",
    #     )