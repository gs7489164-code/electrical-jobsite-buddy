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

# Web/manual search (best-effort)
import requests
from bs4 import BeautifulSoup

# Optional OCR (best-effort)
OCR_AVAILABLE = False
try:
    from PIL import Image
    import pytesseract  # may not be installed
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

import streamlit.components.v1 as components


# ----------------------------
# App meta
# ----------------------------
APP_VERSION = "v0.7.0 (Planned Pack)"
APP_TITLE = "⚡ Electrical Jobsite Buddy"


# ----------------------------
# Basic setup
# ----------------------------
st.set_page_config(
    page_title=APP_TITLE,
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
# Styling
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

        /* Priority badges */
        .prio-high { background: rgba(255, 84, 84, 0.14); border: 1px solid rgba(255, 84, 84, 0.30); }
        .prio-med  { background: rgba(255,214,10,0.12); border: 1px solid rgba(255,214,10,0.25); }
        .prio-low  { background: rgba(0, 255, 240, 0.10); border: 1px solid rgba(0, 255, 240, 0.22); }

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

        /* Top Nav pill */
        div[role="radiogroup"] {
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,214,10,0.14);
            padding: 10px 12px;
            border-radius: 999px;
            width: fit-content;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ----------------------------
# DB helpers + migration
# ----------------------------
def now_iso():
    return datetime.now().isoformat()


def new_item(text: str, priority="Medium", link: str = ""):
    return {
        "id": uuid.uuid4().hex[:10],
        "text": text.strip(),
        "done": False,
        "priority": priority,
        "link": link.strip(),
        "created_at": now_iso(),
    }


def default_db():
    return {
        "version": 2,
        "created_at": now_iso(),
        "app_version": APP_VERSION,
        "job_sites": {},
    }


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def load_db():
    if not DB_FILE.exists():
        db = default_db()
        save_db(db)
        return db
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            db = json.load(f)
    except Exception:
        db = default_db()
        save_db(db)
        return db

    # migrate to latest shape
    db = migrate_db(db)
    return db


def ensure_site(db, site_name: str):
    if site_name not in db["job_sites"]:
        db["job_sites"][site_name] = {
            "created_at": now_iso(),
            "what_to_do": [],        # list[dict]
            "materials_need": [],    # list[dict]
            "materials_have": [],    # list[dict]
            "to_buy": [],            # list[dict]
            "notes": "",
            "photos": [],            # legacy general photos
            "section_photos": {      # NEW: per section photos
                "what_to_do": [],
                "materials": [],
                "to_buy": [],
                "notes": [],
                "general": [],
            },
        }


def clean_name(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def migrate_list_to_items(maybe_list):
    # old = ["task1", "task2"] -> new = [{"id", "text", ...}]
    if not isinstance(maybe_list, list):
        return []
    if not maybe_list:
        return []
    if isinstance(maybe_list[0], dict) and "text" in maybe_list[0]:
        return maybe_list  # already migrated
    out = []
    for x in maybe_list:
        if isinstance(x, str) and x.strip():
            out.append(new_item(x.strip(), priority="Medium"))
    return out


def migrate_db(db: dict) -> dict:
    if not isinstance(db, dict):
        return default_db()

    if "job_sites" not in db or not isinstance(db["job_sites"], dict):
        db["job_sites"] = {}

    # set meta
    db.setdefault("version", 2)
    db["app_version"] = APP_VERSION

    for site_name, site in db["job_sites"].items():
        if not isinstance(site, dict):
            continue

        site.setdefault("created_at", now_iso())
        site.setdefault("notes", "")
        site.setdefault("photos", [])

        # migrate lists
        site["what_to_do"] = migrate_list_to_items(site.get("what_to_do", []))
        site["materials_need"] = migrate_list_to_items(site.get("materials_need", []))
        site["materials_have"] = migrate_list_to_items(site.get("materials_have", []))
        site["to_buy"] = migrate_list_to_items(site.get("to_buy", []))

        # ensure section photos
        if "section_photos" not in site or not isinstance(site["section_photos"], dict):
            site["section_photos"] = {
                "what_to_do": [],
                "materials": [],
                "to_buy": [],
                "notes": [],
                "general": [],
            }

        for k in ["what_to_do", "materials", "to_buy", "notes", "general"]:
            site["section_photos"].setdefault(k, [])

        # move legacy photos into general section if not already
        if site.get("photos"):
            # keep them but also mirror to general (dedupe)
            for p in site["photos"]:
                if p not in site["section_photos"]["general"]:
                    site["section_photos"]["general"].append(p)

    save_db(db)
    return db


# ----------------------------
# Manual search helpers
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


def duckduckgo_pdf_search(query: str, max_results: int = 10):
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

    # de-dupe
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


def sniff_price(url: str) -> str:
    """
    Best-effort price detector. Many sites block/obfuscate.
    If it can't find a price, returns "".
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (PriceSniffer/1.0; +streamlit)"}
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return ""
        txt = r.text
        # Simple common patterns: $12.34 or CAD 12.34
        m = re.search(r"\$\s?([0-9]{1,5}(?:\.[0-9]{2})?)", txt)
        if m:
            return f"${m.group(1)}"
        m2 = re.search(r"CAD\s?([0-9]{1,5}(?:\.[0-9]{2})?)", txt, flags=re.I)
        if m2:
            return f"CAD {m2.group(1)}"
        return ""
    except Exception:
        return ""


# ----------------------------
# UI blocks
# ----------------------------
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


def hero():
    st.markdown(
        f"""
        <div class="hero">
            <span class="badge">⚡ Electrical</span>
            <span class="badge">🧰 Jobsite</span>
            <span class="badge">📸 Photos</span>
            <span class="badge">📄 Manuals</span>
            <span class="badge">🔎 Search</span>
            <h1>Electrical Jobsite Buddy</h1>
            <p>Tasks • Materials • To-Buy • Photos • Manuals — <b>{APP_VERSION}</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")


def top_nav():
    options = ["🏗️ Jobsite", "📸 Photos", "📄 Manuals", "⚙️ Settings"]
    if "top_page" not in st.session_state:
        st.session_state["top_page"] = "🏗️ Jobsite"

    chosen = st.radio(
        label="",
        options=options,
        horizontal=True,
        key="top_page",
        label_visibility="collapsed",
    )

    if chosen == "🏗️ Jobsite":
        return "JOB_SITES"
    if chosen == "📸 Photos":
        return "PHOTOS"
    if chosen == "📄 Manuals":
        return "MANUALS"
    return "SETTINGS"


def priority_badge(priority: str) -> str:
    p = (priority or "Medium").lower()
    klass = "prio-med"
    icon = "🟡"
    if p == "high":
        klass = "prio-high"
        icon = "🔴"
    elif p == "low":
        klass = "prio-low"
        icon = "🔵"
    return f'<span class="badge {klass}">{icon} {priority}</span>'


def upload_photos_to_section(site: dict, section_key: str, label: str):
    up = st.file_uploader(
        f"📸 Add photos for {label}",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=f"uploader_{section_key}_{site.get('created_at','')}",
    )
    if up:
        for file in up:
            ext = Path(file.name).suffix.lower()
            fname = f"{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
            out_path = UPLOADS_DIR / fname
            with open(out_path, "wb") as f:
                f.write(file.getbuffer())
            site["section_photos"][section_key].append(str(out_path))
        st.success("Photos saved ✅")
        st.rerun()

    photos = site["section_photos"].get(section_key, [])
    if photos:
        st.write("**Saved photos:**")
        cols = st.columns(3)
        for idx, p in enumerate(list(photos)):
            with cols[idx % 3]:
                st.image(p, use_container_width=True)
                if st.button("Remove", key=f"rm_{section_key}_{idx}"):
                    site["section_photos"][section_key].pop(idx)
                    st.rerun()


def sort_items(items: list[dict]):
    prio_rank = {"High": 0, "Medium": 1, "Low": 2}
    def key_fn(x):
        done = bool(x.get("done", False))
        pr = x.get("priority", "Medium")
        return (done, prio_rank.get(pr, 1), x.get("created_at", ""))
    items.sort(key=key_fn)


def add_item_ui(items: list[dict], label: str, key_prefix: str, allow_link: bool = False):
    c1, c2, c3 = st.columns([0.62, 0.18, 0.20], gap="small")
    with c1:
        txt = st.text_input(f"➕ Add to {label}", key=f"{key_prefix}_text", placeholder="Type and press Enter…")
    with c2:
        pr = st.selectbox("Priority", ["High", "Medium", "Low"], index=1, key=f"{key_prefix}_prio")
    with c3:
        add = st.button("Add", key=f"{key_prefix}_add")

    link_val = ""
    if allow_link:
        link_val = st.text_input("Link (optional)", key=f"{key_prefix}_link", placeholder="Paste product link (HD/RONA/Amazon)…")

    if add or (txt and txt.endswith("\n")):
        pass

    if add:
        if txt.strip():
            items.append(new_item(txt.strip(), priority=pr, link=link_val))
            st.session_state[f"{key_prefix}_text"] = ""
            if allow_link:
                st.session_state[f"{key_prefix}_link"] = ""
            st.toast("Added", icon="✅")
            st.rerun()
        else:
            st.warning("Type something first.")


def items_table_ui(items: list[dict], key_prefix: str, show_link: bool = False, show_price: bool = False):
    if not items:
        st.info("Nothing here yet.")
        return

    sort_items(items)

    for i, it in enumerate(list(items)):
        it_id = it.get("id", f"{i}")
        cols = st.columns([0.06, 0.58, 0.16, 0.10, 0.10], gap="small")

        with cols[0]:
            it["done"] = st.checkbox("", value=bool(it.get("done", False)), key=f"{key_prefix}_done_{it_id}")

        with cols[1]:
            txt = it.get("text", "")
            if it.get("done"):
                st.markdown(f"~~{txt}~~")
            else:
                st.write(txt)

            if show_link and it.get("link"):
                st.markdown(f'<a href="{it["link"]}" target="_blank" style="color:#7fe7ff;">Open link</a>', unsafe_allow_html=True)

        with cols[2]:
            # show as badge
            st.markdown(priority_badge(it.get("priority", "Medium")), unsafe_allow_html=True)

        with cols[3]:
            # quick price sniff (optional)
            if show_price and it.get("link"):
                if st.button("💲 Price", key=f"{key_prefix}_price_{it_id}"):
                    with st.spinner("Checking…"):
                        p = sniff_price(it["link"])
                    if p:
                        st.success(p)
                    else:
                        st.info("Couldn’t detect price (site may block).")

        with cols[4]:
            if st.button("🗑️", key=f"{key_prefix}_del_{it_id}"):
                items.remove(it)
                st.toast("Removed", icon="🧽")
                st.rerun()


def text_contains(hay: str, needle: str) -> bool:
    if not needle:
        return True
    return needle.lower() in (hay or "").lower()


def site_search_filter(site: dict, query: str):
    q = query.strip().lower()
    if not q:
        return None  # no filter

    def match_item(it):
        return q in (it.get("text", "").lower()) or q in (it.get("link", "").lower())

    filtered = {
        "what_to_do": [it for it in site["what_to_do"] if match_item(it)],
        "materials_need": [it for it in site["materials_need"] if match_item(it)],
        "materials_have": [it for it in site["materials_have"] if match_item(it)],
        "to_buy": [it for it in site["to_buy"] if match_item(it)],
        "notes_hit": q in (site.get("notes", "").lower()),
    }
    return filtered


def pdf_preview_if_possible(local_pdf_path: Path):
    # Streamlit doesn't have a perfect native PDF viewer everywhere, so we do iframe.
    try:
        pdf_bytes = local_pdf_path.read_bytes()
        b64 = st.base64.b64encode(pdf_bytes).decode("utf-8")  # type: ignore
    except Exception:
        # fallback: show download only
        with open(local_pdf_path, "rb") as f:
            st.download_button("Download PDF", data=f, file_name=local_pdf_path.name, mime="application/pdf")
        return


# ----------------------------
# Manual Finder: OCR (optional)
# ----------------------------
def try_ocr_text(image_file) -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(image_file)
        text = pytesseract.image_to_string(img)
        # clean
        text = re.sub(r"[^\w\s\-\.:/#]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception:
        return ""


# ----------------------------
# MAIN
# ----------------------------
inject_css()
db = load_db()

page = top_nav()
st.write("")
hero()

with st.sidebar:
    st.markdown("### ⚡ Control Panel")
    st.caption("Use the top bar to switch pages.")
    st.divider()
    st.caption(f"App: {APP_VERSION}")
    st.caption("Tip: Your data is stored locally in data/app_db.json")


# ----------------------------
# JOBSITES PAGE
# ----------------------------
if page == "JOB_SITES":
    left, right = st.columns([0.58, 0.42], gap="large")

    with left:
        section_card("🏗️ Job Sites", "Create a site, then track tasks/materials/to-buy/photos + search.", electric=True)

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
                    st.rerun()
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

        # Search across everything
        search_q = st.text_input("🔎 Search this job site (tasks/materials/to-buy/notes)", placeholder="Try: 'GFCI', '14/2', 'Eaton', 'receptacle'…")
        hits = site_search_filter(site, search_q) if search_q.strip() else None

        tabs = st.tabs(["✅ What To Do", "🧰 Materials", "🛒 To Buy", "📸 Photos", "📝 Notes"])

        with tabs[0]:
            section_card("✅ What To Do", "Checkbox done + priority. Tap fast on your phone.", electric=False)

            add_item_ui(site["what_to_do"], "What To Do", key_prefix="todo_add", allow_link=False)

            show_items = site["what_to_do"] if not hits else hits["what_to_do"]
            items_table_ui(show_items, key_prefix="todo", show_link=False, show_price=False)

            st.markdown("---")
            upload_photos_to_section(site, "what_to_do", "What To Do")

        with tabs[1]:
            section_card("🧰 Materials", "Need vs Have + priority. Photos inside this tab.", electric=True)
            c1, c2 = st.columns(2, gap="large")

            with c1:
                st.subheader("Materials Needed")
                add_item_ui(site["materials_need"], "Materials Needed", key_prefix="need_add", allow_link=False)
                show_items = site["materials_need"] if not hits else hits["materials_need"]
                items_table_ui(show_items, key_prefix="need", show_link=False)

            with c2:
                st.subheader("Materials Have")
                add_item_ui(site["materials_have"], "Materials Have", key_prefix="have_add", allow_link=False)
                show_items = site["materials_have"] if not hits else hits["materials_have"]
                items_table_ui(show_items, key_prefix="have", show_link=False)

            st.markdown("---")
            upload_photos_to_section(site, "materials", "Materials")

        with tabs[2]:
            section_card("🛒 To Buy", "Done ✅ + priority + optional link + price sniff (best-effort).", electric=False)

            add_item_ui(site["to_buy"], "To Buy", key_prefix="buy_add", allow_link=True)

            show_items = site["to_buy"] if not hits else hits["to_buy"]
            items_table_ui(show_items, key_prefix="buy", show_link=True, show_price=True)

            st.markdown("---")
            upload_photos_to_section(site, "to_buy", "To Buy")

        with tabs[3]:
            section_card("📸 Photos", "General photos for this job site.", electric=True)
            upload_photos_to_section(site, "general", "General Photos")

        with tabs[4]:
            section_card("📝 Notes", "Write anything. Search box also checks if your notes contain the keyword.", electric=False)
            site["notes"] = st.text_area("Notes", value=site.get("notes", ""), height=220)

            if hits and hits.get("notes_hit"):
                st.success("✅ Your Notes contain the search keyword.")

            st.markdown("---")
            upload_photos_to_section(site, "notes", "Notes")

        save_db(db)

    with right:
        section_card("⚡ Quick Dashboard", "Fast view (sorted by priority & done).", electric=True)

        todo_done = sum(1 for x in site["what_to_do"] if x.get("done"))
        buy_done = sum(1 for x in site["to_buy"] if x.get("done"))

        st.metric("What To Do", f"{todo_done}/{len(site['what_to_do'])} done")
        st.metric("Materials Needed", len(site["materials_need"]))
        st.metric("Materials Have", len(site["materials_have"]))
        st.metric("To Buy", f"{buy_done}/{len(site['to_buy'])} done")

        # Photo counts
        sp = site.get("section_photos", {})
        photo_total = sum(len(sp.get(k, [])) for k in sp.keys()) if isinstance(sp, dict) else 0
        st.metric("Photos (all sections)", photo_total)

        st.write("")
        section_card("🔥 Electric Vibes", "Little reminders like a foreman… but nicer.", electric=False)
        st.write("• Take a photo before you close walls 🔧")
        st.write("• Label neutrals/grounds properly ✅")
        st.write("• Keep receipts for materials 🧾")
        st.write("• If it’s near water… think GFCI ⚠️")


# ----------------------------
# PHOTOS PAGE
# ----------------------------
elif page == "PHOTOS":
    section_card("📸 Photos", "Browse photos by job site + by section.", electric=True)
    st.write("")

    sites = sorted(db["job_sites"].keys())
    if not sites:
        st.info("No job sites yet. Create one in Jobsite page first.")
        st.stop()

    active = st.selectbox("Select Job Site", sites, index=0)
    site = db["job_sites"][active]

    section = st.selectbox("Select section", ["general", "what_to_do", "materials", "to_buy", "notes"], index=0)
    photos = site.get("section_photos", {}).get(section, [])

    if not photos:
        st.info("No photos saved for this section yet.")
    else:
        cols = st.columns(3)
        for idx, p in enumerate(photos):
            with cols[idx % 3]:
                st.image(p, use_container_width=True)


# ----------------------------
# MANUALS PAGE
# ----------------------------
elif page == "MANUALS":
    section_card("📄 Manual Finder", "Search manuals + optional photo OCR → auto-fill.", electric=True)
    st.write("")

    st.info("Tip: Upload a photo of a label/model plate. If OCR is available, it will try to extract model text.")

    c1, c2 = st.columns([0.45, 0.55], gap="large")

    with c1:
        uploaded = st.file_uploader("📸 Upload device label photo (optional)", type=["png", "jpg", "jpeg", "webp"])
        extracted = ""
        if uploaded:
            st.image(uploaded, use_container_width=True)
            if OCR_AVAILABLE:
                if st.button("✨ Try OCR (extract model text)"):
                    with st.spinner("Reading text…"):
                        extracted = try_ocr_text(uploaded)
                    if extracted:
                        st.success("OCR extracted text (you can edit below):")
                        st.write(extracted)
                    else:
                        st.warning("OCR couldn’t read clearly. Try a sharper photo or better lighting.")
            else:
                st.warning("OCR not available on this install (pytesseract/Pillow not installed). You can still type model manually.")

        q_default = extracted if extracted else ""
        q = st.text_input("Search manual", value=q_default, placeholder="e.g., 'Schneider EV charger model XYZ manual'")

        do_search = st.button("🔎 Search")

    with c2:
        st.markdown("### Results")
        st.caption("Best-effort web search. Some sites block direct PDF downloads — if so, open link and download manually.")

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
                        title = r["title"]

                        st.markdown(
                            f"""
                            <div class="card2">
                                <div style="font-weight:700;">{idx}. {title}</div>
                                <div style="opacity:0.85; font-size: 13px; word-break: break-word;">
                                    <a href="{url}" target="_blank" style="color:#7fe7ff; text-decoration:none;">
                                        {url}
                                    </a>
                                </div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        cA, cB, cC = st.columns([0.18, 0.40, 0.42], gap="small")
                        with cA:
                            st.link_button("Open", url)
                        with cB:
                            if st.button("⬇️ Download", key=f"dl_{idx}"):
                                try:
                                    tmp_name = f"manual_{uuid.uuid4().hex[:8]}.pdf"
                                    tmp_path = DATA_DIR / tmp_name
                                    with st.spinner("Downloading…"):
                                        download_file(url, tmp_path)
                                    with open(tmp_path, "rb") as f:
                                        st.download_button(
                                            label="✅ Click to save",
                                            data=f,
                                            file_name=tmp_name,
                                            mime="application/pdf",
                                            key=f"dlbtn_{idx}",
                                        )
                                except Exception as e:
                                    st.warning(f"Download failed (site may block). Error: {e}")

                        with cC:
                            st.caption("If download fails, Open link and download from site.")


# ----------------------------
# SETTINGS PAGE
# ----------------------------
else:
    section_card("⚙️ Settings", "Backup / reset + app version.", electric=True)
    st.write("")

    st.markdown(f"### 🏷️ App Version: **{APP_VERSION}**")

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
