import requests
import io
import time
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Gestionale Elenchi", layout="wide")

token = (st.query_params.get("token", "") or "").strip()
API_BASE = st.secrets.get("API_BASE", "http://localhost:8000")


st.title("Gestionale Elenchi")
st.caption("Consultazione elenchi – accesso riservato (WordPress)")

# =========================
# SIDEBAR (filtri + auth)
# =========================
with st.sidebar:
    st.header("Autenticazione")

    if not token:
        st.warning("Accesso solo tramite WordPress.")
        st.caption("Se stai sviluppando in locale, puoi incollare manualmente un token.")
        token = st.text_area("Token (Bearer)", height=120)
        token = (token or "").strip()
    else:
        st.success("Sessione autenticata via WordPress")

    # dentro with st.sidebar: ...
    st.divider()
    st.header("Filtri")

    # placeholder: verranno riempiti dopo che abbiamo caricato le opzioni
    selected_province = []
    selected_comuni = []
    selected_prov_nasc = []
    selected_com_nasc = []
    sex_choice = "Tutti"
    nat_choice = "Tutti"


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

role = (who.get("role") or "").lower()

opts = load_filter_options(token)

# UI filtri (sidebar) con opzioni reali
with st.sidebar:
    # Provincia/Comune (multi)
    selected_province = st.multiselect("Provincia", options=opts["province"], default=[])
    # Cascata Comune basata sulle province scelte (se non hai endpoint facets vero, lo fai "morbido"):
    # se selezioni province, restringo i comuni prendendoli dal campione e filtrandoli.
    # (Per avere cascata perfetta su tutto il DB serve endpoint backend.)
    if selected_province and opts["cols"]["prov"] and opts["cols"]["com"]:
        # ricostruisco un minimo dal campione (senza ricaricare: prendo dal dataframe campionato ricavato in load_filter_options)
        # workaround: riprendo il campione (costo basso: in cache)
        data0 = api_get("/auth/search", token, params={"limit": 5000, "offset": 0})
        d0 = pd.DataFrame(data0.get("items", []))
        d0p = d0[d0[opts["cols"]["prov"]].astype(str).str.strip().isin(selected_province)]
        comuni_casc = uniq_sorted(d0p[opts["cols"]["com"]]) if opts["cols"]["com"] in d0p.columns else opts["comuni"]
    else:
        comuni_casc = opts["comuni"]

    selected_comuni = st.multiselect("Comune", options=comuni_casc, default=[])

    st.divider()

    # Nascita (multi)
    selected_prov_nasc = st.multiselect("Provincia di nascita", options=opts["prov_nasc"], default=[])

    # cascata comune di nascita (stessa logica)
    if selected_prov_nasc and opts["cols"]["prov_n"] and opts["cols"]["com_n"]:
        data0 = api_get("/auth/search", token, params={"limit": 5000, "offset": 0})
        d0 = pd.DataFrame(data0.get("items", []))
        d0n = d0[d0[opts["cols"]["prov_n"]].astype(str).str.strip().isin(selected_prov_nasc)]
        comn_casc = uniq_sorted(d0n[opts["cols"]["com_n"]]) if opts["cols"]["com_n"] in d0n.columns else opts["com_nasc"]
    else:
        comn_casc = opts["com_nasc"]

    selected_com_nasc = st.multiselect("Comune di nascita", options=comn_casc, default=[])

    st.divider()

    sex_choice = st.selectbox("Sesso", ["Tutti", "Maschi", "Femmine"], index=0)
    nat_choice = st.selectbox("Italiano / Estero (da Provincia nascita = EE)", ["Tutti", "Italiano", "Estero"], index=0)


def clean_str(x):
    if x is None:
        return ""
    return str(x).strip()

def uniq_sorted(series):
    vals = [clean_str(x) for x in series if clean_str(x) != ""]
    return sorted(set(vals))

@st.cache_data(ttl=300, show_spinner=False)
def load_filter_options(tok: str, sample_limit: int = 5000):
    """
    Fallback DEMO: carica un campione di righe e ricava i valori distinti.
    Per produzione: sostituire con endpoint backend /auth/facets o /auth/distinct.
    """
    data0 = api_get("/auth/search", tok, params={"limit": sample_limit, "offset": 0})
    items0 = data0.get("items", [])
    if not items0:
        return {
            "province": [], "comuni": [],
            "prov_nasc": [], "com_nasc": [],
            "sesso": []
        }

    d0 = pd.DataFrame(items0)

    # nomi colonna: prova sia snake_case che titoli "umani"
    col_prov = "provincia" if "provincia" in d0.columns else ("Provincia" if "Provincia" in d0.columns else None)
    col_com = "comune" if "comune" in d0.columns else ("Comune" if "Comune" in d0.columns else None)

    col_prov_n = (
        "provincia_nascita" if "provincia_nascita" in d0.columns else
        ("Provincia di nascita" if "Provincia di nascita" in d0.columns else
         ("provincia_di_nascita" if "provincia_di_nascita" in d0.columns else None))
    )
    col_com_n = (
        "comune_nascita" if "comune_nascita" in d0.columns else
        ("Comune di nascita" if "Comune di nascita" in d0.columns else
         ("comune_di_nascita" if "comune_di_nascita" in d0.columns else None))
    )

    col_sesso = "sesso" if "sesso" in d0.columns else ("Sesso" if "Sesso" in d0.columns else None)

    out = {
        "province": uniq_sorted(d0[col_prov]) if col_prov else [],
        "comuni": uniq_sorted(d0[col_com]) if col_com else [],
        "prov_nasc": uniq_sorted(d0[col_prov_n]) if col_prov_n else [],
        "com_nasc": uniq_sorted(d0[col_com_n]) if col_com_n else [],
        "sesso": uniq_sorted(d0[col_sesso]) if col_sesso else [],
        "cols": {
            "prov": col_prov, "com": col_com,
            "prov_n": col_prov_n, "com_n": col_com_n,
            "sesso": col_sesso
        }
    }
    return out


if role == "administrator":
    st.divider()
    st.subheader("Upload Excel (solo Admin)")

    up = st.file_uploader("Carica file Excel (.xlsx)", type=["xlsx"])
    mode = st.selectbox("Modalità import", ["replace"], index=0)

    if up is not None and st.button("Importa nel database"):
        # 1) Conversione Excel -> CSV (CLIENT SIDE)
        with st.spinner("Conversione Excel → CSV..."):
            df = pd.read_excel(up, dtype=str)
            csv_bytes = df.to_csv(index=False).encode("utf-8")

        # 2) Invio CSV al backend (job async)
        with st.spinner("Invio CSV al backend..."):
            files = {
                "file": ("elenchi.csv", csv_bytes, "text/csv")
            }
            r = requests.post(
                f"{API_BASE}/admin/import",
                headers=auth_headers(token),
                files=files,
                data={"mode": mode},
                timeout=120
            )

        if r.status_code != 202:
            st.error(f"Errore import ({r.status_code}): {r.text}")
            st.stop()

        job_id = r.json()["job_id"]
        st.success(f"Import avviato. Job ID: {job_id}")

        # 3) Polling stato job
        with st.spinner("Import in corso..."):
            for _ in range(600):  # ~10 minuti
                s = requests.get(
                    f"{API_BASE}/admin/import/status",
                    headers=auth_headers(token),
                    params={"job_id": job_id},
                    timeout=30
                )

                if s.status_code != 200:
                    st.error(f"Errore stato ({s.status_code}): {s.text}")
                    st.stop()

                js = s.json()
                st.info(f"Stato: {js['status']} | Righe: {js.get('inserted_rows')}")

                if js["status"] == "done":
                    st.success(f"Import completato! Righe inserite: {js.get('inserted_rows')}")
                    break

                if js["status"] == "error":
                    st.error(f"Import fallito: {js.get('error')}")
                    break

                time.sleep(1)
        if r.status_code == 401:
            st.error("Sessione scaduta: torna alla pagina WordPress e riapri il gestionale.")
            st.stop()
        if r.status_code == 200:
            st.success(f"Import completato: {r.json()}")
        else:
            st.error(f"Errore import ({r.status_code}): {r.text}")

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
    "limit": page_size,
    "offset": offset,
}

# Multi-select: requests serializza liste come provincia=RM&provincia=LT...
if selected_province:
    params["provincia"] = selected_province
if selected_comuni:
    params["comune"] = selected_comuni

# Nascita (qui dipende dal backend: metto nomi "ragionevoli")
# Se il backend non li supporta ancora, non succede niente finché non li implementi server-side.
if selected_prov_nasc:
    params["provincia_nascita"] = selected_prov_nasc
if selected_com_nasc:
    params["comune_nascita"] = selected_com_nasc

# Sesso (mapping semplice)
if sex_choice == "Maschi":
    params["sesso"] = "M"
elif sex_choice == "Femmine":
    params["sesso"] = "F"

# Italiano / Estero (da provincia nascita == EE)
# Anche qui: se non c'è supporto backend, va implementato.
if nat_choice == "Estero":
    params["nato_estero"] = "true"
elif nat_choice == "Italiano":
    params["nato_estero"] = "false"

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
