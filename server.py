import os, re, json, uuid, sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "Z.E AI Business Builder")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
UPLOADS = BASE / "uploads"
GENERATED = BASE / "generated_sites"
DB = BASE / "sites.db"

STATIC.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)
GENERATED.mkdir(exist_ok=True)

app = FastAPI(title=APP_NAME)

app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# DB
# =========================

def db():
    return sqlite3.connect(DB)

def init_db():
    c = db()
    cur = c.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS account(
        id INTEGER PRIMARY KEY,
        plan TEXT DEFAULT 'free',
        generated_count INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    INSERT OR IGNORE INTO account(id, plan, generated_count)
    VALUES(1, 'free', 0)
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sites(
        id TEXT PRIMARY KEY,
        title TEXT,
        html TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS leads(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_id TEXT,
        name TEXT,
        phone TEXT,
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.commit()
    c.close()

init_db()

def account():
    c = db()
    cur = c.cursor()
    cur.execute("SELECT plan, generated_count FROM account WHERE id=1")
    row = cur.fetchone()
    c.close()
    return {"plan": row[0], "generated_count": row[1]}

def set_premium():
    c = db()
    cur = c.cursor()
    cur.execute("UPDATE account SET plan='pro' WHERE id=1")
    c.commit()
    c.close()

def inc_generation():
    c = db()
    cur = c.cursor()
    cur.execute("UPDATE account SET generated_count = generated_count + 1 WHERE id=1")
    c.commit()
    c.close()

# =========================
# MODELS
# =========================

class GenerateRequest(BaseModel):
    message: str

class LeadRequest(BaseModel):
    site_id: str
    name: str = ""
    phone: str = ""
    message: str = ""

# =========================
# ROUTES
# =========================

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

# 🔥 ВОТ ЭТО ВАЖНО (лендинг)
@app.get("/landing", response_class=HTMLResponse)
def landing():
    return HTMLResponse((STATIC / "landing.html").read_text(encoding="utf-8"))

@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME, "model": OPENAI_MODEL}

@app.get("/api/me")
def me():
    return account()

@app.post("/api/checkout/demo")
def demo_checkout():
    set_premium()
    return {"status": "ok", "message": "Premium activated"}

# =========================
# GENERATE SITE
# =========================

def fallback_html():
    return """<!DOCTYPE html>
<html><body><h1>Сайт создан</h1></body></html>"""

@app.post("/generate")
def generate(req: GenerateRequest):

    acc = account()

    if acc["plan"] == "free" and acc["generated_count"] >= 1:
        return JSONResponse(status_code=402, content={
            "error": "free_limit",
            "reply": "Доступен только 1 сайт бесплатно"
        })

    if not client:
        return {"reply": "Нет API ключа"}

    r = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "Создай HTML сайт полностью"},
            {"role": "user", "content": req.message}
        ]
    )

    html = r.choices[0].message.content or fallback_html()

    site_id = uuid.uuid4().hex[:8]

    c = db()
    cur = c.cursor()
    cur.execute("INSERT INTO sites(id,title,html) VALUES(?,?,?)",
                (site_id, req.message, html))
    c.commit()
    c.close()

    inc_generation()

    return {
        "site_id": site_id,
        "site_html": html,
        "public_url": f"/s/{site_id}"
    }

# =========================
# PUBLIC SITE
# =========================

@app.get("/s/{site_id}", response_class=HTMLResponse)
def site(site_id: str):
    c = db()
    cur = c.cursor()
    cur.execute("SELECT html FROM sites WHERE id=?", (site_id,))
    row = cur.fetchone()
    c.close()

    if not row:
        return HTMLResponse("Not found", status_code=404)

    html = row[0]

    script = f"""
<script>
function sendLead(e){{
e.preventDefault();
let f=e.target;
fetch('/api/lead',{{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{
site_id:'{site_id}',
name:f.name.value,
phone:f.phone.value,
message:f.message.value
}})
}});
alert('Заявка отправлена');
}}
</script>
"""

    return HTMLResponse(html + script)

# =========================
# LEADS
# =========================

@app.post("/api/lead")
def lead(req: LeadRequest):
    c = db()
    cur = c.cursor()
    cur.execute("INSERT INTO leads(site_id,name,phone,message) VALUES(?,?,?,?)",
                (req.site_id, req.name, req.phone, req.message))
    c.commit()
    c.close()
    return {"status": "ok"}
