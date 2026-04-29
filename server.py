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

APP_NAME = os.getenv("APP_NAME", "Z.E Family AI Business Builder")
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
history: List[Dict[str, str]] = []

class GenerateRequest(BaseModel):
    message: str
    mode: Optional[str] = "site"
    style: Optional[str] = "premium"
    primary_color: Optional[str] = "#2ea7ff"
    secondary_color: Optional[str] = "#42f5c8"
    logo_url: Optional[str] = ""
    photo_url: Optional[str] = ""

class UpdateSiteRequest(BaseModel):
    title: str
    html: str

class AiEditRequest(BaseModel):
    site_id: Optional[str] = ""
    title: Optional[str] = ""
    html: str
    instruction: str

class LeadRequest(BaseModel):
    site_id: str
    name: str = ""
    phone: str = ""
    message: str = ""

class ProductPackRequest(BaseModel):
    site_id: str

class AdPackRequest(BaseModel):
    site_id: str

class BusinessPackRequest(BaseModel):
    idea: str

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
        product_pack TEXT DEFAULT '',
        ad_pack TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS views(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        site_id TEXT,
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

def safe_id(x: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", x or "")

def fallback_html():
    return """<!DOCTYPE html><html lang="ru"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Z.E Site</title><style>body{margin:0;font-family:Arial;background:#07111f;color:white}.hero{min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;padding:30px}.card{max-width:760px;padding:36px;border-radius:28px;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12)}h1{font-size:42px}input,textarea{display:block;width:100%;padding:14px;margin:10px 0;border-radius:12px;border:0}button,a{display:inline-block;padding:14px 20px;border-radius:999px;background:#2ea7ff;color:white;text-decoration:none;border:0}</style></head><body><section class="hero"><div class="card"><h1>Сайт готов</h1><p>Ваш сайт создан AI.</p><form onsubmit="sendLead(event)"><input name="name" placeholder="Имя"><input name="phone" placeholder="Телефон"><textarea name="message" placeholder="Сообщение"></textarea><button>Отправить заявку</button></form></div></section><script>function sendLead(e){e.preventDefault();const f=e.target;fetch('/api/lead',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({site_id:location.pathname.split('/').pop(),name:f.name.value,phone:f.phone.value,message:f.message.value})}).then(()=>{alert('Заявка отправлена');f.reset()})}</script></body></html>"""

def extract_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {"reply": "Собрал резервную версию.", "site_title": "Готовый сайт", "site_html": fallback_html()}

SITE_PROMPT = """
Ты AI Business Builder уровня Tilda/Webflow + маркетолог + продакт-менеджер.

Создавай не код ради кода, а готовый коммерческий продукт: сайт, который собирает заявки.

Всегда возвращай строго JSON:
{
 "reply": "короткий ответ",
 "site_title": "название сайта",
 "site_html": "полный HTML сайта"
}

Требования:
- полный HTML с <!DOCTYPE html>
- весь CSS внутри <style>
- весь JS внутри <script>
- адаптив под телефон
- премиальный дизайн Apple/Telegram
- без внешних библиотек
- много продающего текста
- Hero, оффер, услуги, преимущества, цены, как работает, отзывы, FAQ, контакты, форма заявки, финальный CTA
- обязательно форма заявки с onsubmit="sendLead(event)"
- поля формы: name, phone, message
- JS sendLead отправляет POST /api/lead с site_id из pathname
- если есть телефон: tel: и sms:
- если есть адрес: добавь адрес
- если данных мало — додумывай сам
"""

EDIT_PROMPT = """
Ты AI-редактор сайта. Верни полный обновлённый HTML.
Всегда строго JSON:
{"reply":"что изменено","site_title":"название","site_html":"полный HTML"}
Сохраняй рабочую форму заявок sendLead(event).
Не объясняй код.
"""

PACK_PROMPT = """
Ты AI-продюсер продукта. Создай Product Pack для клиента.
Верни строго JSON:
{
 "reply":"коротко",
 "pack":"подробный текстовый пакет"
}
В pack включи:
1. Что это за продукт
2. Для кого
3. Как пользоваться сайтом
4. Как принимать заявки
5. Как купить домен
6. Как подключить домен
7. Как выложить на хостинг
8. Как запустить первые продажи
9. Что улучшить дальше
10. Чеклист запуска
Пиши понятно для новичка.
"""

AD_PROMPT = """
Ты маркетолог. Создай рекламный пакет.
Верни строго JSON:
{"reply":"коротко","pack":"текст"}
В pack включи:
- объявление Авито
- пост Telegram
- пост Instagram
- 5 заголовков
- 5 офферов
- скрипт ответа клиенту
- план первых 7 дней продвижения
"""

BUSINESS_PROMPT = """
Ты AI-стартап-архитектор. По идее создай готовый бизнес-пакет.
Верни строго JSON:
{"reply":"коротко","business_pack":"текст"}
Включи:
- идея
- целевая аудитория
- MVP
- сайт
- воронка
- цены
- реклама
- первые клиенты
- план на 7 дней
- план на 30 дней
"""

def save_site(title, html):
    sid = uuid.uuid4().hex[:10]
    (GENERATED / f"{sid}.html").write_text(html, encoding="utf-8")
    c = db()
    cur = c.cursor()
    cur.execute("INSERT INTO sites(id,title,html) VALUES(?,?,?)", (sid, title, html))
    c.commit()
    c.close()
    return sid

def get_site(sid):
    sid = safe_id(sid)
    c = db()
    cur = c.cursor()
    cur.execute("SELECT id,title,html,product_pack,ad_pack,created_at,updated_at FROM sites WHERE id=?", (sid,))
    row = cur.fetchone()
    c.close()
    return row

def update_site(sid, title, html):
    sid = safe_id(sid)
    c = db()
    cur = c.cursor()
    cur.execute("UPDATE sites SET title=?, html=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (title, html, sid))
    c.commit()
    ok = cur.rowcount > 0
    c.close()
    if ok:
        (GENERATED / f"{sid}.html").write_text(html, encoding="utf-8")
    return ok

def ai_json(prompt, payload, max_tokens=7000, temperature=0.25):
    if not client:
        raise RuntimeError("OPENAI_API_KEY не найден")
    r = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
        ],
        temperature=temperature,
        max_tokens=max_tokens
    )
    return extract_json(r.choices[0].message.content or "")

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

@app.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME, "model": OPENAI_MODEL}

@app.get("/api/me")
def me():
    return account()

@app.post("/api/checkout/demo")
def demo_checkout():
    set_premium()
    return {"status": "ok", "plan": "pro", "message": "Demo Premium activated"}

@app.get("/s/{site_id}", response_class=HTMLResponse)
def public_site(site_id: str):
    row = get_site(site_id)
    if not row:
        return HTMLResponse("<h1>Сайт не найден</h1>", status_code=404)
    html = row[2]
    track = f"<script>fetch('/api/view',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{site_id:'{row[0]}'}})}}).catch(()=>{{}})</script>"
    return HTMLResponse(html.replace("</body>", track + "</body>") if "</body>" in html else html + track)

@app.get("/download/{site_id}")
def download(site_id: str):
    row = get_site(site_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    path = GENERATED / f"{row[0]}.html"
    path.write_text(row[2], encoding="utf-8")
    return FileResponse(path, media_type="text/html", filename="index.html")

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif"]:
        return JSONResponse(status_code=400, content={"error": "Только изображения"})
    name = uuid.uuid4().hex[:12] + ext
    path = UPLOADS / name
    path.write_bytes(await file.read())
    return {"url": f"/uploads/{name}"}

@app.post("/generate")
def generate(req: GenerateRequest):
    acc = account()
    if acc["plan"] == "free" and acc["generated_count"] >= 1:
        return JSONResponse(status_code=402, content={
            "error": "free_limit",
            "reply": "Бесплатно доступен 1 сайт. Включи Premium для продолжения."
        })

    data = ai_json(SITE_PROMPT, req.model_dump())
    title = data.get("site_title", "Готовый сайт")
    html = data.get("site_html", fallback_html())
    sid = save_site(title, html)
    inc_generation()
    return {
        "reply": data.get("reply", "Готово. Сайт создан."),
        "site_id": sid,
        "site_title": title,
        "site_html": html,
        "public_url": f"/s/{sid}",
        "download_url": f"/download/{sid}"
    }

@app.post("/ai-edit")
def ai_edit(req: AiEditRequest):
    acc = account()
    if acc["plan"] == "free":
        return JSONResponse(status_code=402, content={"error": "premium_required", "reply": "AI-редактор доступен в Premium."})
    data = ai_json(EDIT_PROMPT, req.model_dump())
    title = data.get("site_title", req.title or "Сайт")
    html = data.get("site_html", req.html)
    sid = safe_id(req.site_id)
    if sid:
        update_site(sid, title, html)
    return {
        "reply": data.get("reply", "Изменения внесены."),
        "site_id": sid,
        "site_title": title,
        "site_html": html,
        "public_url": f"/s/{sid}" if sid else None,
        "download_url": f"/download/{sid}" if sid else None
    }

@app.post("/product-pack")
def product_pack(req: ProductPackRequest):
    acc = account()
    if acc["plan"] == "free":
        return JSONResponse(status_code=402, content={"error": "premium_required", "reply": "Product Pack доступен в Premium."})
    row = get_site(req.site_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": "site not found"})
    data = ai_json(PACK_PROMPT, {"title": row[1], "html": row[2]}, max_tokens=5000)
    pack = data.get("pack", "")
    c = db()
    cur = c.cursor()
    cur.execute("UPDATE sites SET product_pack=? WHERE id=?", (pack, row[0]))
    c.commit()
    c.close()
    return {"reply": data.get("reply", "Product Pack готов."), "pack": pack}

@app.post("/ad-pack")
def ad_pack(req: AdPackRequest):
    acc = account()
    if acc["plan"] == "free":
        return JSONResponse(status_code=402, content={"error": "premium_required", "reply": "Рекламный пакет доступен в Premium."})
    row = get_site(req.site_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": "site not found"})
    data = ai_json(AD_PROMPT, {"title": row[1], "html": row[2]}, max_tokens=4500)
    pack = data.get("pack", "")
    c = db()
    cur = c.cursor()
    cur.execute("UPDATE sites SET ad_pack=? WHERE id=?", (pack, row[0]))
    c.commit()
    c.close()
    return {"reply": data.get("reply", "Рекламный пакет готов."), "pack": pack}

@app.post("/business-pack")
def business_pack(req: BusinessPackRequest):
    acc = account()
    if acc["plan"] == "free":
        return JSONResponse(status_code=402, content={"error": "premium_required", "reply": "Создание бизнеса доступно в Premium."})
    data = ai_json(BUSINESS_PROMPT, req.model_dump(), max_tokens=5000)
    return {"reply": data.get("reply", "Бизнес-пакет готов."), "pack": data.get("business_pack", "")}

@app.get("/api/sites")
def list_sites():
    c = db()
    cur = c.cursor()
    cur.execute("""
    SELECT s.id,s.title,s.created_at,s.updated_at,
    COUNT(DISTINCT l.id), COUNT(DISTINCT v.id)
    FROM sites s
    LEFT JOIN leads l ON l.site_id=s.id
    LEFT JOIN views v ON v.site_id=s.id
    GROUP BY s.id ORDER BY s.created_at DESC
    """)
    rows = cur.fetchall()
    c.close()
    return {"sites": [{
        "id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3],
        "leads_count": r[4], "views_count": r[5],
        "public_url": f"/s/{r[0]}", "download_url": f"/download/{r[0]}"
    } for r in rows]}

@app.get("/api/sites/{site_id}")
def api_site(site_id: str):
    row = get_site(site_id)
    if not row:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return {
        "id": row[0], "title": row[1], "html": row[2],
        "product_pack": row[3], "ad_pack": row[4],
        "created_at": row[5], "updated_at": row[6],
        "public_url": f"/s/{row[0]}", "download_url": f"/download/{row[0]}"
    }

@app.put("/api/sites/{site_id}")
def api_update(site_id: str, req: UpdateSiteRequest):
    ok = update_site(site_id, req.title, req.html)
    if not ok:
        return JSONResponse(status_code=404, content={"error": "not found"})
    sid = safe_id(site_id)
    return {"status": "ok", "public_url": f"/s/{sid}", "download_url": f"/download/{sid}"}

@app.delete("/api/sites/{site_id}")
def api_delete(site_id: str):
    sid = safe_id(site_id)
    c = db()
    cur = c.cursor()
    cur.execute("DELETE FROM sites WHERE id=?", (sid,))
    cur.execute("DELETE FROM leads WHERE site_id=?", (sid,))
    cur.execute("DELETE FROM views WHERE site_id=?", (sid,))
    c.commit()
    c.close()
    p = GENERATED / f"{sid}.html"
    if p.exists():
        p.unlink()
    return {"status": "deleted"}

@app.post("/api/lead")
def lead(req: LeadRequest):
    sid = safe_id(req.site_id)
    c = db()
    cur = c.cursor()
    cur.execute("INSERT INTO leads(site_id,name,phone,message) VALUES(?,?,?,?)", (sid, req.name, req.phone, req.message))
    c.commit()
    c.close()
    return {"status": "ok"}

@app.post("/api/view")
def view(req: LeadRequest):
    sid = safe_id(req.site_id)
    c = db()
    cur = c.cursor()
    cur.execute("INSERT INTO views(site_id) VALUES(?)", (sid,))
    c.commit()
    c.close()
    return {"status": "ok"}

@app.get("/api/leads/{site_id}")
def leads(site_id: str):
    sid = safe_id(site_id)
    c = db()
    cur = c.cursor()
    cur.execute("SELECT name,phone,message,created_at FROM leads WHERE site_id=? ORDER BY created_at DESC", (sid,))
    rows = cur.fetchall()
    c.close()
    return {"leads": [{"name": r[0], "phone": r[1], "message": r[2], "created_at": r[3]} for r in rows]}

@app.get("/api/analytics/{site_id}")
def analytics(site_id: str):
    sid = safe_id(site_id)
    c = db()
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM views WHERE site_id=?", (sid,))
    views = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE site_id=?", (sid,))
    leads_count = cur.fetchone()[0]
    c.close()
    conv = round((leads_count / views) * 100, 2) if views else 0
    return {"views": views, "leads": leads_count, "conversion": conv}
