"""Админ-веб панель «Фото будущего»: подписчики, фото, цели, лог отправок, ручная отправка."""
import asyncio
import datetime
import html
import pathlib
import secrets

import pytz
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.database.models import User, DeliveryLog
from bot.services.ai_services import generate_prompt_and_affirmation, generate_image_with_face
from bot.services.delivery_log import record_delivery

PHOTOS_DIR = pathlib.Path("/app/photos")
COOKIE = "admin_session"

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
.thumbs img {{ width:92px; height:92px; object-fit:cover; border-radius:8px; border:1px solid #2a2f3a; cursor:pointer; }}
.thumbs img:hover {{ border-color:#5b8cff; }}
.goals {{ font-size:13px; color:#c6cddb; margin:6px 0; }} .goals div {{ margin:2px 0; }}
button {{ background:#3b6cf5; color:#fff; border:0; border-radius:8px; padding:8px 14px; font-size:13px; cursor:pointer; }}
button:hover {{ background:#2f57c9; }} button:disabled {{ background:#333; color:#777; cursor:wait; }}
.bulk {{ position:sticky; top:0; background:#0f1115; padding:10px 0; display:flex; gap:10px; align-items:center; z-index:5; }}
.logtbl {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }}
.logtbl th, .logtbl td {{ border:1px solid #2a2f3a; padding:5px 8px; text-align:left; }}
.logtbl th {{ background:#1d2230; color:#9aa4bd; }}
.status {{ font-size:13px; color:#7dd97d; min-height:18px; margin-top:6px; }}
input[type=password] {{ background:#171a21; color:#e6e6e6; border:1px solid #2a2f3a; border-radius:8px; padding:10px; width:260px; }}
input[type=checkbox] {{ width:18px; height:18px; }}
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

    cards = []
    for u in users:
        thumbs = "".join(
            f'<img src="/photo/{html.escape(p.s3_url.split("/")[-1])}" title="фото">'
            for p in u.photos)
        goals = "".join(f"<div>• {html.escape(g.goal_text)}</div>" for g in u.goals) or "<i>нет целей</i>"
        gender = u.gender or "не указан"
        log_rows = "".join(
            f"<tr><td>{fmt_dt(l.sent_at, u.timezone)}</td>"
            f"<td>{'✅' if l.success else '❌'}</td>"
            f"<td>{html.escape(l.source)}</td>"
            f"<td>{html.escape(l.goal_text or '')}</td>"
            f"<td>{html.escape(l.error or '')}</td></tr>"
            for l in logs_by_user.get(u.telegram_id, [])) or '<tr><td colspan="5"><i>нет отправок</i></td></tr>'
        cards.append(f"""
<div class="card">
 <div class="uhead">
  <input type="checkbox" class="sel" data-id="{u.telegram_id}">
  <b>@{html.escape(u.username or '—')}</b><span class="uid">{u.telegram_id}</span>
  <span class="badge {u.subscription_status.value}">{u.subscription_status.value}</span>
  <span class="badge">{gender}</span>
 </div>
 <div class="meta">
  ТЗ: {u.timezone or '—'} · доставка: <b>{u.delivery_time or '—'}</b> ·
  до подписки: {fmt_dt(u.subscription_end_date)} · последняя генерация: {fmt_dt(u.last_generation_at, u.timezone)}
 </div>
 <div class="thumbs">{thumbs or '<i>нет фото</i>'}</div>
 <div class="goals">{goals}</div>
 <button onclick="sendNow({u.telegram_id}, this)">⚡ Отправить сейчас</button>
 <div class="status" id="st{u.telegram_id}"></div>
 <table class="logtbl"><tr><th>Время ({u.timezone or 'UTC'})</th><th></th><th>Источник</th><th>Цель</th><th>Ошибка</th></tr>{log_rows}</table>
</div>""")

    body = f"""
<h1>Фото будущего — панель управления</h1>
<div class="sub">Подписчиков: {len(users)} · Обнови страницу (F5), чтобы увидеть новые отправки</div>
<div class="bulk">
 <label><input type="checkbox" id="all" onchange="toggleAll(this)"> выделить всех</label>
 <button onclick="sendSelected(this)">⚡ Отправить выбранным</button>
 <span class="status" id="bulkstatus"></span>
</div>
{"".join(cards)}
<script>
function toggleAll(cb) {{ document.querySelectorAll('.sel').forEach(c => c.checked = cb.checked); }}
async function sendNow(id, btn) {{
  if (!confirm('Сгенерировать и отправить картинку юзеру ' + id + '?')) return;
  btn.disabled = true; document.getElementById('st' + id).textContent = '⏳ генерация (~1-2 мин)...';
  const r = await fetch('/api/send?id=' + id);
  const j = await r.json();
  if (j.ok) {{ document.getElementById('st' + id).textContent = '✅ отправлено! Обнови страницу (F5) для лога'; setTimeout(() => location.reload(), 1500); }}
  else document.getElementById('st' + id).textContent = '❌ ' + (j.error || 'ошибка');
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


async def _send_to_users(ids):
    engine = create_async_engine(settings.DATABASE_URL)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    bot_token = settings.BOT_TOKEN
    from aiogram import Bot
    from aiogram.types import BufferedInputFile
    bot = Bot(token=bot_token)
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
                ai = await generate_prompt_and_affirmation(goal.goal_text, gender)
                result = await generate_image_with_face(ai['prompt'], ai['affirmation'], photos, gender)
                if isinstance(result, str):
                    import aiohttp as ah
                    async with ah.ClientSession() as hs:
                        async with hs.get(result) as resp:
                            image_bytes = await resp.read()
                else:
                    image_bytes = result.image_bytes
                await bot.send_photo(chat_id=u.telegram_id,
                                     photo=BufferedInputFile(image_bytes, filename="affirmation.png"),
                                     caption="")
                async with S() as s2:
                    uu = await s2.get(User, u.telegram_id)
                    uu.last_generation_at = datetime.datetime.utcnow()
                    await s2.commit()
                await record_delivery(u.telegram_id, "manual", goal.goal_text)
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


async def photo_handler(request):
    if not check_login(request):
        return web.HTTPForbidden()
    name = request.match_info["name"]
    f = PHOTOS_DIR / pathlib.Path(name).name
    if not f.exists():
        return web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "no-cache"})


routes.router.add_get("/", index)
routes.router.add_get("/login", login_handler)
routes.router.add_post("/login", login_handler)
routes.router.add_get("/api/send", api_send)
routes.router.add_get("/photo/{name}", photo_handler)

if __name__ == "__main__":
    web.run_app(routes, host="0.0.0.0", port=8080, print=None)
