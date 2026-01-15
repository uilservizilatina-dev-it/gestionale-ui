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

role = (who.get("role") or "").lower()

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
