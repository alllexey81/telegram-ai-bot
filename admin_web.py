"""Админ-веб панель «Фото будущего»: подписчики, фото, цели, лог отправок с картинками,
ручная отправка, редактирование профиля (фото/таймзона/цели), выдача доступа."""
import asyncio
import datetime
import html
import pathlib
import secrets
import uuid

import pytz
from aiohttp import web
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.database.models import User, DeliveryLog, Photo, Goal
from bot.services.ai_services import generate_prompt_and_affirmation, generate_image_with_face
from bot.services.delivery_log import record_delivery
from bot.services.gen_store import save_generated

PHOTOS_DIR = pathlib.Path("/app/photos")
COOKIE = "admin_session"

TIMEZONES = [
    "Europe/Moscow", "Europe/Kaliningrad", "Europe/Samara", "Europe/Volgograd",
    "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Novosibirsk", "Asia/Novokuznetsk",
    "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Vladivostok", "Asia/Barnaul",
    "Asia/Yakutsk", "Asia/Kamchatka", "Europe/Simferopol",
]

routes = web.Application()


def check_login(request) -> bool:
    return request.cookies.get(COOKIE) == settings.ADMIN_WEB_PASSWORD


def redirect_login():
    raise web.HTTPFound("/login")


def fmt_dt(dt, tz_name=None):
    if not dt:
        return "—"
    if tz_name:
        try:
            local = dt.replace(tzinfo=pytz.utc).astimezone(pytz.timezone(tz_name))
            return local.strftime("%d.%m %H:%M")
        except Exception:
            pass
    return dt.strftime("%d.%m %H:%M UTC")


def page(body: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Фото будущего — админ</title><meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{ color-scheme: dark; }}
body {{ background:#0f1115; color:#e6e6e6; font-family:'Segoe UI',Arial,sans-serif; margin:0; padding:24px; }}
h1 {{ font-size:22px; margin:0 0 6px; }} .sub {{ color:#8b93a7; margin-bottom:20px; font-size:13px; }}
.card {{ background:#171a21; border:1px solid #2a2f3a; border-radius:12px; padding:16px; margin-bottom:16px; }}
.uhead {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
.uhead b {{ font-size:16px; }} .uid {{ color:#8b93a7; font-size:12px; }}
.badge {{ background:#232838; border-radius:6px; padding:2px 8px; font-size:12px; }}
.badge.ok {{ color:#7dd97d; }} .badge.trial {{ color:#f2c94c; }} .badge.expired {{ color:#ff7d7d; }}
.meta {{ color:#aab2c5; font-size:13px; margin:8px 0; line-height:1.5; }}
.thumbs {{ display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; }}
.thumbwrap {{ position:relative; }}
.thumbwrap img {{ width:92px; height:92px; object-fit:cover; border-radius:8px; border:1px solid #2a2f3a; cursor:pointer; }}
.thumbwrap img:hover {{ border-color:#5b8cff; }}
.thumbwrap .del {{ position:absolute; top:-6px; right:-6px; background:#c0392b; color:#fff; border:0;
  border-radius:50%; width:20px; height:20px; font-size:11px; line-height:20px; padding:0; cursor:pointer; }}
.goals {{ font-size:13px; color:#c6cddb; margin:6px 0; }}
textarea, select, input[type=time], input[type=file] {{ background:#171a21; color:#e6e6e6; border:1px solid #2a2f3a;
  border-radius:8px; padding:8px; font-size:13px; font-family:inherit; }}
textarea {{ width:100%; min-height:70px; }}
.editrow {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:8px 0; }}
button {{ background:#3b6cf5; color:#fff; border:0; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; }}
button:hover {{ background:#2f57c9; }} button:disabled {{ background:#333; color:#777; cursor:wait; }}
button.grant {{ background:#2e8b57; }} button.grant:hover {{ background:#257044; }}
button.ghost {{ background:#232838; }} button.ghost:hover {{ background:#2e3448; }}
.bulk {{ position:sticky; top:0; background:#0f1115; padding:10px 0; display:flex; gap:10px; align-items:center; z-index:5; }}
.logtbl {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }}
.logtbl th, .logtbl td {{ border:1px solid #2a2f3a; padding:5px 8px; text-align:left; vertical-align:middle; }}
.logtbl th {{ background:#1d2230; color:#9aa4bd; }}
.logtbl img {{ width:70px; height:70px; object-fit:cover; border-radius:6px; }}
details summary {{ cursor:pointer; color:#8fa8ff; font-size:13px; margin-top:6px; }}
.status {{ font-size:13px; color:#7dd97d; min-height:18px; margin-top:6px; }}
input[type=password] {{ background:#171a21; color:#e6e6e6; border:1px solid #2a2f3a; border-radius:8px; padding:10px; width:260px; }}
input[type=checkbox] {{ width:18px; height:18px; }}
#lightbox {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.92); z-index:100;
  cursor:zoom-out; align-items:center; justify-content:center; }}
#lightbox img {{ max-width:95vw; max-height:95vh; border-radius:8px; }}
</style></head><body>{body}</body></html>"""


async def login_handler(request):
    if request.method == "POST":
        form = await request.post()
        if form.get("password") == settings.ADMIN_WEB_PASSWORD:
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, settings.ADMIN_WEB_PASSWORD, max_age=30 * 24 * 3600)
            raise resp
    body = page("""<div class="card" style="max-width:360px"><h1>🔐 Админ-панель</h1>
<form method="post"><input type="password" name="password" placeholder="Пароль" autofocus>
<button style="margin-top:10px">Войти</button></form></div>""")
    return web.Response(text=body, content_type="text/html")


def user_card(u, logs) -> str:
    thumbs = "".join(
        f'<span class="thumbwrap"><img src="/photo/{html.escape(p.s3_url.split("/")[-1])}" title="фото">'
        f'<button class="del" title="Удалить фото" onclick="delPhoto({u.telegram_id}, {p.id}, this)">✕</button></span>'
        for p in u.photos)
    goals_text = "\n".join(g.goal_text for g in u.goals)
    tz_opts = "".join(
        f'<option value="{tz}"{" selected" if tz == u.timezone else ""}>{tz}</option>'
        for tz in TIMEZONES)
    delivery_val = u.delivery_time.strftime("%H:%M") if u.delivery_time else ""
    log_rows = ""
    for l in logs:
        img_cell = f'<img src="/genphoto/{html.escape(l.image_path)}">' if l.image_path else ""
        log_rows += (
            f"<tr><td>{fmt_dt(l.sent_at, u.timezone)}</td>"
            f"<td>{'✅' if l.success else '❌'}</td>"
            f"<td>{html.escape(l.source)}</td>"
            f"<td>{html.escape(l.goal_text or '')}</td>"
            f"<td>{img_cell}</td>"
            f"<td>{html.escape(l.error or '')}</td></tr>")
    if not log_rows:
        log_rows = '<tr><td colspan="6"><i>нет отправок</i></td></tr>'

    return f"""
<div class="card">
 <div class="uhead">
  <input type="checkbox" class="sel" data-id="{u.telegram_id}">
  <b>@{html.escape(u.username or '—')}</b><span class="uid">{u.telegram_id}</span>
  <span class="badge {u.subscription_status.value}">{u.subscription_status.value}</span>
  <span class="badge">{u.gender or 'пол не указан'}</span>
 </div>
 <div class="meta">
  ТЗ: {u.timezone or '—'} · доставка: <b>{u.delivery_time or '—'}</b> ·
  подписка до: {fmt_dt(u.subscription_end_date)} · последняя генерация: {fmt_dt(u.last_generation_at, u.timezone)}
 </div>
 <div class="thumbs">{thumbs or '<i>нет фото</i>'}</div>
 <div class="editrow"><input type="file" id="up{u.telegram_id}" multiple accept="image/*"
   onchange="uploadPhotos({u.telegram_id}, this)">
 <button class="ghost" onclick="grant({u.telegram_id}, 30, this)">🗓 +30 дней доступа</button>
 <button class="ghost" onclick="grant({u.telegram_id}, 90, this)">🗓 +90 дней доступа</button></div>

 <details><summary>✏️ Редактировать профиль (цели, таймзона, время)</summary>
  <div class="editrow">
   <select id="tz{u.telegram_id}">{tz_opts}</select>
   <input type="time" id="dt{u.telegram_id}" value="{delivery_val}">
   <button onclick="saveProfile({u.telegram_id}, this)">💾 Сохранить ТЗ/время</button>
  </div>
  <div class="editrow">
   <input type="text" id="ex{u.telegram_id}" value="{html.escape(u.prompt_extra or '')}"
     style="flex:1" placeholder="Особые пожелания и ограничения к каждому фото (напр.: надпись с именем Ваня, летают голуби, без детей, только мужская компания)">
   <button onclick="saveExtra({u.telegram_id}, this)">💾 Сохранить пожелания</button>
  </div>
  <textarea id="gl{u.telegram_id}" placeholder="По одной цели на строку">{html.escape(goals_text)}</textarea>
  <div class="editrow"><button onclick="saveGoals({u.telegram_id}, this)">💾 Сохранить цели</button></div>
 </details>

 <button onclick="sendNow({u.telegram_id}, this)">⚡ Отправить сейчас</button>
 <div class="status" id="st{u.telegram_id}"></div>
 <table class="logtbl"><tr><th>Время ({u.timezone or 'UTC'})</th><th></th><th>Источник</th><th>Цель</th><th>Картинка</th><th>Ошибка</th></tr>{log_rows}</table>
</div>"""


async def index(request):
    if not check_login(request):
        redirect_login()
    engine = create_async_engine(settings.DATABASE_URL)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with S() as session:
            users = (await session.execute(
                select(User).options(selectinload(User.goals), selectinload(User.photos))
            )).scalars().all()
            logs = (await session.execute(
                select(DeliveryLog).order_by(DeliveryLog.sent_at.desc())
            )).scalars().all()
    finally:
        await engine.dispose()

    logs_by_user = {}
    for lg in logs:
        logs_by_user.setdefault(lg.user_id, []).append(lg)

    cards = "".join(user_card(u, logs_by_user.get(u.telegram_id, [])) for u in users)
    body = f"""
<h1>Фото будущего — панель управления</h1>
<div class="sub">Подписчиков: {len(users)} · Обнови страницу (F5), чтобы увидеть новые отправки</div>
<div class="bulk">
 <label><input type="checkbox" id="all" onchange="toggleAll(this)"> выделить всех</label>
 <button onclick="sendSelected(this)">⚡ Отправить выбранным</button>
 <span class="status" id="bulkstatus"></span>
</div>
{cards}
<div id="lightbox" onclick="this.style.display='none'"><img id="lbimg"></div>
<script>
function lb(src) {{ document.getElementById('lbimg').src = src; document.getElementById('lightbox').style.display = 'flex'; }}
document.addEventListener('DOMContentLoaded', () => {{
  document.querySelectorAll('.logtbl td img').forEach(i => i.onclick = () => lb(i.src));
  document.querySelectorAll('.thumbwrap > img').forEach(i => i.onclick = () => lb(i.src));
}});
</script>
<script>
function toggleAll(cb) {{ document.querySelectorAll('.sel').forEach(c => c.checked = cb.checked); }}
function st(id) {{ return document.getElementById('st' + id); }}
async function sendNow(id, btn) {{
  if (!confirm('Сгенерировать и отправить картинку юзеру ' + id + '?')) return;
  btn.disabled = true; st(id).textContent = '⏳ генерация (~1-2 мин)...';
  const r = await fetch('/api/send?id=' + id);
  const j = await r.json();
  if (j.ok) {{ st(id).textContent = '✅ отправлено!'; setTimeout(() => location.reload(), 1500); }}
  else st(id).textContent = '❌ ' + (j.error || 'ошибка');
  btn.disabled = false;
}}
async function sendSelected(btn) {{
  const ids = [...document.querySelectorAll('.sel')].filter(c => c.checked).map(c => c.dataset.id);
  if (!ids.length) {{ alert('Никого не выбрано'); return; }}
  if (!confirm('Отправить ' + ids.length + ' юзерам?')) return;
  btn.disabled = true; document.getElementById('bulkstatus').textContent = '⏳ генерация...';
  const r = await fetch('/api/send?ids=' + ids.join(','));
  const j = await r.json();
  document.getElementById('bulkstatus').textContent = j.ok ? '✅ запущено, обнови страницу через пару минут' : '❌ ' + j.error;
  btn.disabled = false;
}}
async function grant(id, days, btn) {{
  if (!confirm('Продлить доступ юзеру ' + id + ' на ' + days + ' дней?')) return;
  btn.disabled = true;
  const r = await fetch('/api/grant?id=' + id + '&days=' + days);
  const j = await r.json();
  if (j.ok) {{ st(id).textContent = '✅ доступ продлён на ' + days + ' дн. (до ' + j.until + ')'; setTimeout(() => location.reload(), 1500); }}
  else st(id).textContent = '❌ ' + (j.error || 'ошибка');
  btn.disabled = false;
}}
async function delPhoto(id, photoId, btn) {{
  if (!confirm('Удалить это фото-референс?')) return;
  btn.disabled = true;
  const r = await fetch('/api/del_photo?id=' + id + '&photo=' + photoId);
  const j = await r.json();
  if (j.ok) btn.closest('.thumbwrap').remove();
  else alert('Ошибка: ' + (j.error || ''));
}}
async function uploadPhotos(id, input) {{
  if (!input.files.length) return;
  const fd = new FormData();
  for (const f of input.files) fd.append('files', f);
  st(id).textContent = '⏳ загрузка фото...';
  const r = await fetch('/api/upload?id=' + id, {{ method: 'POST', body: fd }});
  const j = await r.json();
  if (j.ok) {{ st(id).textContent = '✅ фото загружены (' + j.added + ')'; setTimeout(() => location.reload(), 1200); }}
  else st(id).textContent = '❌ ' + (j.error || 'ошибка');
  input.value = '';
}}
async function saveProfile(id, btn) {{
  btn.disabled = true;
  const tz = document.getElementById('tz' + id).value;
  const dt = document.getElementById('dt' + id).value;
  const r = await fetch('/api/profile', {{ method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ id, timezone: tz, delivery_time: dt }}) }});
  const j = await r.json();
  st(id).textContent = j.ok ? '✅ сохранено' : '❌ ' + (j.error || 'ошибка');
  if (j.ok) setTimeout(() => location.reload(), 1200);
  btn.disabled = false;
}}
async function saveExtra(id, btn) {{
  btn.disabled = true;
  const r = await fetch('/api/extra', {{ method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ id, extra: document.getElementById('ex' + id).value }}) }});
  const j = await r.json();
  st(id).textContent = j.ok ? '✅ пожелания сохранены' : '❌ ' + (j.error || 'ошибка');
  btn.disabled = false;
}}
async function saveGoals(id, btn) {{
  btn.disabled = true;
  const goals = document.getElementById('gl' + id).value;
  const r = await fetch('/api/goals', {{ method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ id, goals }}) }});
  const j = await r.json();
  st(id).textContent = j.ok ? '✅ цели сохранены (' + j.count + ')' : '❌ ' + (j.error || 'ошибка');
  if (j.ok) setTimeout(() => location.reload(), 1200);
  btn.disabled = false;
}}
</script>"""
    return web.Response(text=page(body), content_type="text/html")


_send_locks: set = set()


async def api_send(request):
    if not check_login(request):
        return web.json_response({"ok": False, "error": "unauthorized"})
    q = request.rel_url.query
    if q.get("ids"):
        ids = [int(x) for x in q["ids"].split(",") if x.isdigit()]
    elif q.get("id"):
        ids = [int(q["id"])]
    else:
        return web.json_response({"ok": False, "error": "no id"})

    for uid in ids:
        if uid in _send_locks:
            return web.json_response({"ok": False, "error": f"задача для {uid} уже выполняется"})
    _send_locks.update(ids)
    asyncio.get_event_loop().create_task(_send_to_users(ids))
    return web.json_response({"ok": True, "queued": ids})


def task_engine():
    engine = create_async_engine(settings.DATABASE_URL)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _send_to_users(ids):
    engine, S = task_engine()
    from aiogram import Bot
    from aiogram.types import BufferedInputFile
    bot = Bot(token=settings.BOT_TOKEN)
    try:
        async with S() as session:
            users = (await session.execute(
                select(User).where(User.telegram_id.in_(ids))
                .options(selectinload(User.goals), selectinload(User.photos)))).scalars().all()
        for u in users:
            try:
                goal = secrets.choice(list(u.goals))
                photos = [p.s3_url for p in u.photos]
                gender = u.gender or "male"
                ai = await generate_prompt_and_affirmation(goal.goal_text, gender, u.prompt_extra)
                result = await generate_image_with_face(ai['prompt'], ai['affirmation'], photos, gender, u.prompt_extra)
                if isinstance(result, str):
                    import aiohttp as ah
                    async with ah.ClientSession() as hs:
                        async with hs.get(result) as resp:
                            image_bytes = await resp.read()
                else:
                    image_bytes = result.image_bytes
                img_path = save_generated(u.telegram_id, image_bytes)
                await bot.send_photo(chat_id=u.telegram_id,
                                     photo=BufferedInputFile(image_bytes, filename="affirmation.png"),
                                     caption="")
                async with S() as s2:
                    uu = await s2.get(User, u.telegram_id)
                    uu.last_generation_at = datetime.datetime.utcnow()
                    await s2.commit()
                await record_delivery(u.telegram_id, "manual", goal.goal_text, image_path=img_path)
            except Exception as e:
                try:
                    await record_delivery(u.telegram_id, "manual", None, success=False, error=e)
                except Exception:
                    pass
    finally:
        _send_locks.difference_update(ids)
        await engine.dispose()
        try:
            await bot.session.close()
        except Exception:
            pass


async def api_grant(request):
    if not check_login(request):
        return web.json_response({"ok": False, "error": "unauthorized"})
    q = request.rel_url.query
    if not (q.get("id", "").isdigit() and q.get("days", "").isdigit()):
        return web.json_response({"ok": False, "error": "bad params"})
    uid, days = int(q["id"]), int(q["days"])
    engine, S = task_engine()
    try:
        async with S() as session:
            u = await session.get(User, uid)
            if not u:
                return web.json_response({"ok": False, "error": "user not found"})
            base = u.subscription_end_date or datetime.datetime.utcnow()
            if base < datetime.datetime.utcnow():
                base = datetime.datetime.utcnow()
            u.subscription_end_date = base + datetime.timedelta(days=days)
            from bot.database.models import SubStatus
            u.subscription_status = SubStatus.active
            await session.commit()
            until = u.subscription_end_date.strftime("%d.%m.%Y")
        return web.json_response({"ok": True, "until": until})
    finally:
        await engine.dispose()


async def api_profile(request):
    if not check_login(request):
        return web.json_response({"ok": False, "error": "unauthorized"})
    data = await request.json()
    uid = int(data["id"])
    engine, S = task_engine()
    try:
        async with S() as session:
            u = await session.get(User, uid)
            if not u:
                return web.json_response({"ok": False, "error": "user not found"})
            u.timezone = data.get("timezone") or u.timezone
            dt = data.get("delivery_time")
            if dt:
                u.delivery_time = datetime.datetime.strptime(dt, "%H:%M").time()
            await session.commit()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})
    finally:
        await engine.dispose()


async def api_goals(request):
    if not check_login(request):
        return web.json_response({"ok": False, "error": "unauthorized"})
    data = await request.json()
    uid = int(data["id"])
    goals = [g.strip() for g in (data.get("goals") or "").splitlines()
             if g.strip() and len(g.strip()) > 2][:10]
    engine, S = task_engine()
    try:
        async with S() as session:
            await session.execute(delete(Goal).where(Goal.user_id == uid))
            for g in goals:
                session.add(Goal(user_id=uid, goal_text=g))
            await session.commit()
        return web.json_response({"ok": True, "count": len(goals)})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})
    finally:
        await engine.dispose()


async def api_upload(request):
    if not check_login(request):
        return web.json_response({"ok": False, "error": "unauthorized"})
    uid = int(request.rel_url.query["id"])
    reader = await request.multipart()
    added = 0
    engine, S = task_engine()
    try:
        while part := await reader.next():
            if part.name != "files":
                continue
            data = await part.read()
            if not data:
                continue
            name = f"{uuid.uuid4().hex}.jpg"
            (PHOTOS_DIR / name).write_bytes(data)
            async with S() as session:
                session.add(Photo(user_id=uid, s3_url=f"http://host.docker.internal:8000/{name}"))
                await session.commit()
            added += 1
        return web.json_response({"ok": True, "added": added})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})
    finally:
        await engine.dispose()


async def api_del_photo(request):
    if not check_login(request):
        return web.json_response({"ok": False, "error": "unauthorized"})
    uid = int(request.rel_url.query["id"])
    pid = int(request.rel_url.query["photo"])
    engine, S = task_engine()
    try:
        async with S() as session:
            p = await session.get(Photo, pid)
            if not p or p.user_id != uid:
                return web.json_response({"ok": False, "error": "not found"})
            fname = p.s3_url.split("/")[-1]
            await session.delete(p)
            await session.commit()
        f = PHOTOS_DIR / pathlib.Path(fname).name
        if f.exists():
            f.unlink()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})
    finally:
        await engine.dispose()


async def api_extra(request):
    if not check_login(request):
        return web.json_response({"ok": False, "error": "unauthorized"})
    data = await request.json()
    uid = int(data["id"])
    engine, S = task_engine()
    try:
        async with S() as session:
            u = await session.get(User, uid)
            if not u:
                return web.json_response({"ok": False, "error": "user not found"})
            u.prompt_extra = (data.get("extra") or "").strip() or None
            await session.commit()
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})
    finally:
        await engine.dispose()


async def photo_handler(request):
    if not check_login(request):
        return web.HTTPForbidden()
    f = PHOTOS_DIR / pathlib.Path(request.match_info["name"]).name
    if not f.exists():
        return web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "no-cache"})


async def genphoto_handler(request):
    if not check_login(request):
        return web.HTTPForbidden()
    f = PHOTOS_DIR / pathlib.Path(request.match_info["path"])
    if not f.exists():
        return web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "no-cache"})


routes.router.add_get("/", index)
routes.router.add_get("/login", login_handler)
routes.router.add_post("/login", login_handler)
routes.router.add_get("/api/send", api_send)
routes.router.add_get("/api/grant", api_grant)
routes.router.add_post("/api/profile", api_profile)
routes.router.add_post("/api/goals", api_goals)
routes.router.add_post("/api/extra", api_extra)
routes.router.add_post("/api/upload", api_upload)
routes.router.add_get("/api/del_photo", api_del_photo)
routes.router.add_get("/photo/{name}", photo_handler)
routes.router.add_get("/genphoto/{path:.*}", genphoto_handler)

if __name__ == "__main__":
    web.run_app(routes, host="0.0.0.0", port=8080, print=None)
