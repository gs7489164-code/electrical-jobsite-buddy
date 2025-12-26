# app.py
import re
import json
import time
import uuid
import hashlib
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse, parse_qs, unquote

import streamlit as st

# Optional (for manual search)
import requests
from bs4 import BeautifulSoup


# ----------------------------
# Basic setup
# ----------------------------
st.set_page_config(
    page_title="⚡ Electrical Jobsite Buddy",
    page_icon="⚡",
    layout="wide",
)

APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
UPLOADS_DIR = APP_DIR / "uploads"
DB_FILE = DATA_DIR / "app_db.json"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)


# ----------------------------
# Styling (construction / electrical vibe)
# ----------------------------
def inject_css():
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(1200px 600px at 10% 10%, rgba(255, 214, 10, 0.10), transparent 60%),
                        radial-gradient(900px 500px at 80% 20%, rgba(0, 255, 240, 0.08), transparent 55%),
                        linear-gradient(180deg, #0b0f17 0%, #070a10 100%);
            color: #e8eefc;
        }

        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        .hero {
            padding: 18px 18px 10px 18px;
            border-radius: 16px;
            background: linear-gradient(90deg, rgba(255,214,10,0.16), rgba(0,255,240,0.08));
            border: 1px solid rgba(255,214,10,0.25);
            box-shadow: 0 0 30px rgba(255,214,10,0.08);
        }
        .hero h1 {
            margin: 0;
            font-size: 34px;
            letter-spacing: 0.5px;
        }
        .hero p {
            margin: 6px 0 0 0;
            opacity: 0.85;
        }

        .card {
            border-radius: 16px;
            padding: 14px 14px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 214, 10, 0.15);
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }
        .card2 {
            border-radius: 16px;
            padding: 14px 14px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(0, 255, 240, 0.12);
            box-shadow: 0 10px 30px rgba(0,0,0,0.25);
        }

        .badge {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 12px;
            background: rgba(255,214,10,0.12);
            border: 1px solid rgba(255,214,10,0.22);
            margin-right: 8px;
        }

        .stButton > button {
            border-radius: 12px !important;
            border: 1px solid rgba(255,214,10,0.30) !important;
            background: rgba(255,214,10,0.10) !important;
        }
        .stButton > button:hover {
            border: 1px solid rgba(255,214,10,0.60) !important;
            background: rgba(255,214,10,0.18) !important;
            transform: translateY(-1px);
            transition: 0.15s ease;
        }

        .stTextInput input, .stTextArea textarea, .stSelectbox div, .stMultiSelect div {
            border-radius: 12px !important;
        }

        hr {
            border: none;
            border-top: 1px solid rgba(255,255,255,0.08);
            margin: 14px 0;
        }

        /* --- Top Nav "pill" look (Streamlit radio horizontal) --- */
        div[role="radiogroup"] {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,214,10,0.14);
            padding: 10px 12px;
            border-radius: 999px;
            width: fit-content;
        }
        div[role="radiogroup"] > label {
            margin-right: 10px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------
# Data helpers
# ----------------------------
def default_db():
    return {
        "version": 1,
        "created_at": datetime.now().isoformat(),
        "job_sites": {},
    }


def load_db():
    if not DB_FILE.exists():
        db = default_db()
        save_db(db)
        return db
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        db = default_db()
        save_db(db)
        return db


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def ensure_site(db, site_name: str):
    if site_name not in db["job_sites"]:
        db["job_sites"][site_name] = {
            "created_at": datetime.now().isoformat(),
            "what_to_do": [],
            "materials_need": [],
            "materials_have": [],
            "to_buy": [],
            "photos": [],
            "notes": "",
        }


def clean_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def add_unique(lst, item):
    item = item.strip()
    if not item:
        return
    if item not in lst:
        lst.append(item)


def remove_item(lst, item):
    try:
        lst.remove(item)
    except ValueError:
        pass


# ----------------------------
# Manual search
# ----------------------------
def _normalize_ddg_url(href: str) -> str:
    if not href:
        return ""
    absolute = urljoin("https://duckduckgo.com", href)
    try:
        parsed = urlparse(absolute)
        qs = parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            target = unquote(qs["uddg"][0])
            if target.startswith("http://") or target.startswith("https://"):
                return target
    except Exception:
        pass
    return absolute


def duckduckgo_pdf_search(query: str, max_results: int = 8):
    q = f"{query} manual filetype:pdf"
    url = "https://duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (ManualFinder/1.0; +streamlit)"}
    resp = requests.get(url, params={"q": q}, headers=headers, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for a in soup.select("a.result__a"):
        title = a.get_text(" ", strip=True)
        link = _normalize_ddg_url(a.get("href", ""))

        if not link:
            continue

        results.append({"title": title, "url": link})
        if len(results) >= max_results:
            break

    # De-dupe by url
    seen = set()
    deduped = []
    for r in results:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        deduped.append(r)

    return deduped[:max_results]


def download_file(url: str, dest_path: Path):
    headers = {"User-Agent": "Mozilla/5.0 (ManualFinder/1.0; +streamlit)"}
    r = requests.get(url, headers=headers, timeout=25, stream=True, allow_redirects=True)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)


# ----------------------------
# UI blocks
# ----------------------------
def top_nav():
    # This is the "bar" that will WORK (switch pages)
    # Using horizontal radio makes it easy + reliable.
    options = ["⚡ Electrical", "🏗️ Jobsite", "📸 Photos", "📄 Manuals", "⚙️ Settings"]

    if "top_page" not in st.session_state:
        st.session_state["top_page"] = "🏗️ Jobsite"

    chosen = st.radio(
        label="",
        options=options,
        horizontal=True,
        key="top_page",
        label_visibility="collapsed",
    )

    # Map top nav to internal pages
    if chosen == "🏗️ Jobsite":
        return "JOB_SITES"
    if chosen == "📄 Manuals":
        return "MANUALS"
    if chosen == "⚙️ Settings":
        return "SETTINGS"
    if chosen == "📸 Photos":
        return "PHOTOS"
    return "JOB_SITES"


def hero():
    st.markdown(
        """
        <div class="hero">
            <h1>Electrical Jobsite Buddy</h1>
            <p>Track tasks, materials, photos, and find manuals fast — your personal “one-trial” app.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


def section_card(title: str, subtitle: str = "", electric: bool = True):
    klass = "card" if electric else "card2"
    st.markdown(
        f"""
        <div class="{klass}">
            <h3 style="margin:0 0 4px 0;">{title}</h3>
            <div style="opacity:0.82;">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _list_add_callback(items, input_key: str, label: str):
    val = st.session_state.get(input_key, "").strip()
    if not val:
        return
    add_unique(items, val)
    st.session_state[input_key] = ""  # safe to clear here
    st.toast(f"Added to {label}", icon="✅")


def list_editor(label, items, add_key, remove_prefix):
    st.write("")

    # Use on_change instead of setting session_state right after widget renders
    st.text_input(
        f"➕ Add to {label}",
        key=add_key,
        placeholder="Type and press Enter…",
        on_change=_list_add_callback,
        args=(items, add_key, label),
    )

    if items:
        st.write(f"**{label} list:**")
        for i, it in enumerate(items):
            cols = st.columns([0.86, 0.14])
            with cols[0]:
                st.write(f"- {it}")
            with cols[1]:
                if st.button("🗑️", key=f"{remove_prefix}_{hashlib.md5((it+str(i)).encode()).hexdigest()[:8]}"):
                    remove_item(items, it)
                    st.toast("Removed", icon="🧽")
                    st.rerun()
    else:
        st.info("Nothing here yet.")



def photos_uploader(site):
    st.write("")
    up = st.file_uploader(
        "📸 Add photos (panels, devices, rough-in, anything)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
    )
    if up:
        for file in up:
            ext = Path(file.name).suffix.lower()
            fname = f"{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
            out_path = UPLOADS_DIR / fname
            with open(out_path, "wb") as f:
                f.write(file.getbuffer())
            site["photos"].append(str(out_path))
        st.success("Photos saved ✅")
        st.rerun()

    if site["photos"]:
        st.write("**Saved photos:**")
        cols = st.columns(3)
        for idx, p in enumerate(site["photos"]):
            col = cols[idx % 3]
            with col:
                try:
                    st.image(p, use_container_width=True)
                    if st.button("Remove", key=f"rm_photo_{idx}"):
                        site["photos"].pop(idx)
                        st.rerun()
                except Exception:
                    st.write(p)


# ----------------------------
# Main app
# ----------------------------
inject_css()
db = load_db()

# ✅ WORKING top bar
page = top_nav()

# Nice spacing
st.write("")
hero()

# Sidebar still helpful (but not navigation anymore)
with st.sidebar:
    st.markdown("### ⚡ Control Panel")
    st.caption("Use the top bar to switch pages.")
    st.divider()
    st.caption("Tip: Everything saves locally in a JSON file on your laptop.")


# ----------------------------
# Pages
# ----------------------------
if page == "JOB_SITES":
    left, right = st.columns([0.55, 0.45], gap="large")

    with left:
        section_card("🏗️ Job Sites", "Create a site, then track tasks/materials/photos.", electric=True)

        site_name = st.text_input("Job Site Name", placeholder="e.g., Canco Gas Station, Condo Hwy 33, Gurudwara…")
        colA, colB = st.columns([0.6, 0.4])
        with colA:
            if st.button("➕ Create / Open Site"):
                name = clean_name(site_name)
                if not name:
                    st.warning("Type a site name first.")
                else:
                    ensure_site(db, name)
                    save_db(db)
                    st.session_state["active_site"] = name
                    st.toast("Site ready", icon="⚡")
        with colB:
            if st.button("💾 Save Now"):
                save_db(db)
                st.toast("Saved", icon="💾")

        st.write("")
        sites = sorted(db["job_sites"].keys())
        active = st.session_state.get("active_site", sites[0] if sites else "")
        if sites:
            active = st.selectbox("Select Job Site", sites, index=sites.index(active) if active in sites else 0)
            st.session_state["active_site"] = active
        else:
            st.info("Create your first job site above.")
            st.stop()

        site = db["job_sites"][active]

        st.markdown("---")
        st.markdown(f"## ⚡ {active}")

        tabs = st.tabs(["✅ What To Do", "🧰 Materials", "🛒 To Buy", "📸 Photos", "📝 Notes"])

        with tabs[0]:
            section_card("✅ What To Do", "Daily tasks, punch list, troubleshooting steps.", electric=False)
            list_editor("What To Do", site["what_to_do"], add_key="add_todo", remove_prefix="rm_todo")

        with tabs[1]:
            section_card("🧰 Materials", "Track what you NEED vs what you HAVE.", electric=True)
            c1, c2 = st.columns(2)
            with c1:
                list_editor("Materials Needed", site["materials_need"], add_key="add_need", remove_prefix="rm_need")
            with c2:
                list_editor("Materials Have", site["materials_have"], add_key="add_have", remove_prefix="rm_have")

        with tabs[2]:
            section_card("🛒 To Buy", "Anything you need to pick up (Home Depot / Rona / etc).", electric=False)
            list_editor("To Buy", site["to_buy"], add_key="add_buy", remove_prefix="rm_buy")

        with tabs[3]:
            section_card("📸 Photos", "Upload pics for quick reference.", electric=True)
            photos_uploader(site)

        with tabs[4]:
            section_card("📝 Notes", "Panel schedule notes, circuits, measurements, reminders.", electric=False)
            site["notes"] = st.text_area("Notes", value=site.get("notes", ""), height=200)

        save_db(db)

    with right:
        section_card("⚡ Quick Dashboard", "Fast view of your progress.", electric=True)
        st.metric("What To Do", len(site["what_to_do"]))
        st.metric("Materials Needed", len(site["materials_need"]))
        st.metric("Materials Have", len(site["materials_have"]))
        st.metric("To Buy", len(site["to_buy"]))
        st.metric("Photos", len(site["photos"]))

        st.write("")
        section_card("🔥 Electric Vibes", "Little reminders like a foreman… but nicer.", electric=False)
        st.write("• Take a photo before you close walls 🔧")
        st.write("• Label neutrals/grounds properly ✅")
        st.write("• Keep receipts for materials 🧾")
        st.write("• If it’s near water… think GFCI ⚠️")

elif page == "PHOTOS":
    section_card("📸 Photos", "Quickly view photos from a selected job site.", electric=True)
    st.write("")

    sites = sorted(db["job_sites"].keys())
    if not sites:
        st.info("No job sites yet. Create one in Jobsite page first.")
        st.stop()

    active = st.selectbox("Select Job Site", sites, index=0)
    site = db["job_sites"][active]

    if not site["photos"]:
        st.info("No photos saved for this site yet.")
    else:
        cols = st.columns(3)
        for idx, p in enumerate(site["photos"]):
            with cols[idx % 3]:
                st.image(p, use_container_width=True)

elif page == "MANUALS":
    section_card("📄 Manual Finder", "Search for manuals online (best-effort) and grab PDFs.", electric=True)
    st.write("")
    st.info("Type brand + model (example: “Leviton GFCI 7599” or “Siemens panel SN…”)")

    q = st.text_input("Search manual", placeholder="e.g., 'Schneider EV charger manual', 'Eaton breaker CH manual'")
    col1, col2 = st.columns([0.25, 0.75])
    with col1:
        do_search = st.button("🔎 Search")
    with col2:
        st.caption("Some sites block downloads—if a PDF won’t download, open the link and download manually.")

    if do_search:
        if not q.strip():
            st.warning("Enter something to search.")
        else:
            with st.spinner("Searching…"):
                try:
                    results = duckduckgo_pdf_search(q.strip(), max_results=10)
                except Exception as e:
                    st.error(f"Search failed: {e}")
                    results = []

            if not results:
                st.warning("No results found. Try exact model number.")
            else:
                st.success(f"Found {len(results)} results")
                st.write("")

                for idx, r in enumerate(results, start=1):
                    url = r["url"]
                    st.markdown(
                        f"""
                        <div class="card2">
                            <div style="font-weight:700;">{idx}. {r['title']}</div>
                            <div style="opacity:0.85; font-size: 13px; word-break: break-word;">
                                <a href="{url}" target="_blank" style="color:#7fe7ff; text-decoration:none;">
                                    {url}
                                </a>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    cA, cB = st.columns([0.2, 0.8])
                    with cA:
                        st.link_button("Open", url)
                    with cB:
                        if st.button("⬇️ Try Download PDF", key=f"dl_{idx}"):
                            try:
                                tmp_name = f"manual_{uuid.uuid4().hex[:8]}.pdf"
                                tmp_path = DATA_DIR / tmp_name
                                with st.spinner("Downloading…"):
                                    download_file(url, tmp_path)
                                with open(tmp_path, "rb") as f:
                                    st.download_button(
                                        label="✅ Download ready (click)",
                                        data=f,
                                        file_name=tmp_name,
                                        mime="application/pdf",
                                        key=f"dlbtn_{idx}",
                                    )
                            except Exception as e:
                                st.warning(f"Download didn’t work from that link. Error: {e}")
                    st.write("")

elif page == "SETTINGS":
    section_card("⚙️ Settings", "Backup / reset your data.", electric=True)
    st.write("")

    st.markdown("### 💾 Backup")
    if DB_FILE.exists():
        with open(DB_FILE, "rb") as f:
            st.download_button(
                "Download your database (JSON)",
                data=f,
                file_name="electrical_jobsite_buddy_db.json",
                mime="application/json",
            )

    st.markdown("---")
    st.markdown("### 🧹 Reset (danger)")
    st.warning("This clears all job sites and lists. (Photos stay on disk unless you delete the uploads folder.)")
    if st.button("Reset ALL app data"):
        db = default_db()
        save_db(db)
        st.success("Reset complete.")
        st.rerun()
