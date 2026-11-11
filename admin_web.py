"""Админ-веб панель «Фото будущего»: подписчики, фото, цели, лог отправок с картинками,
ручная отправка, редактирование профиля (фото/таймзона/цели/пожелания), выдача доступа."""
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


def icon(name: str) -> str:
    I = {
        "send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
        "plus30": '<path d="M8 2v4"/><path d="M16 2v4"/><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M8 12h8"/><path d="M12 8v8"/>',
        "plus90": '<path d="M8 2v4"/><path d="M16 2v4"/><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M8 13h8"/><path d="M12 9v8"/>',
        "edit": '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
        "trash": '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
        "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
        "search": '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
        "chevron": '<path d="m6 9 6 6 6-6"/>',
        "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
        "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    }
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round">{I.get(name, "")}</svg>')


def page(body: str) -> str:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Фото будущего — админ</title><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root {{
  color-scheme: dark;
  --bg:#0F172A; --card:#1B2336; --muted:#272F42; --border:#475569;
  --fg:#F8FAFC; --fg-muted:#94A3B8; --accent:#22C55E; --on-accent:#0F172A;
  --primary:#1E293B; --danger:#EF4444; --warn:#EAB308;
}}
* {{ box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--fg); font-family:'Fira Sans',sans-serif; font-size:16px; line-height:1.5; margin:0; padding:0 24px 40px; }}
h1 {{ font-size:22px; font-weight:600; margin:0; }}
svg {{ width:16px; height:16px; flex-shrink:0; }}

.topbar {{ display:flex; align-items:center; gap:16px; flex-wrap:wrap; padding:20px 0 14px; }}
.topbar .spacer {{ flex:1; }}

.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:14px; }}
.stat {{ background:linear-gradient(135deg,rgba(255,255,255,.06),rgba(255,255,255,.02));
  backdrop-filter:blur(12px); border:1px solid rgba(255,255,255,.12); border-radius:12px; padding:10px 14px; }}
.stat .n {{ font-family:'Fira Code',monospace; font-size:22px; font-weight:600; }}
.stat .l {{ color:var(--fg-muted); font-size:12px; }}
.stat.warn .n {{ color:var(--warn); }} .stat.bad .n {{ color:var(--danger); }} .stat.ok .n {{ color:var(--accent); }}

.filters {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:16px; position:sticky; top:0;
  background:rgba(15,23,42,.9); backdrop-filter:blur(12px); padding:10px 0; z-index:10; }}
.search {{ position:relative; }}
.search svg {{ position:absolute; left:10px; top:50%; transform:translateY(-50%); color:var(--fg-muted); }}
input[type=text], input[type=time], select, textarea {{ background:var(--card); color:var(--fg);
  border:1px solid var(--border); border-radius:8px; padding:8px 12px; font-size:14px; font-family:inherit; }}
.search input {{ padding-left:34px; width:240px; }}
.search input:focus, select:focus, textarea:focus, input[type=time]:focus {{ outline:2px solid var(--accent); outline-offset:1px; }}
.chip {{ background:var(--muted); border:1px solid var(--border); color:var(--fg-muted); border-radius:999px;
  padding:6px 14px; font-size:13px; cursor:pointer; user-select:none; }}
.chip.on {{ background:var(--accent); border-color:var(--accent); color:var(--on-accent); font-weight:500; }}

button {{ background:var(--primary); color:var(--fg); border:1px solid var(--border); border-radius:8px;
  padding:8px 14px; font-size:13px; font-family:inherit; cursor:pointer; display:inline-flex; gap:6px; align-items:center;
  transition:background .15s; }}
button:hover {{ background:var(--muted); }}
button.primary {{ background:var(--accent); color:var(--on-accent); border-color:var(--accent); font-weight:500; }}
button.primary:hover {{ background:#1eb852; }}
button.danger {{ background:transparent; color:var(--danger); border-color:var(--danger); }}
button.danger:hover {{ background:rgba(239,68,68,.15); }}
button:disabled {{ opacity:.5; cursor:wait; }}
button:focus-visible, .chip:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; }}

.card {{ background:var(--card); border:1px solid rgba(255,255,255,.1); border-radius:14px; padding:16px 18px; margin-bottom:14px; }}
.card.flash {{ border-color:var(--accent); }}
.uhead {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }}
.uhead b {{ font-size:16px; font-weight:600; }}
.uid {{ color:var(--fg-muted); font-size:12px; font-family:'Fira Code',monospace; }}
.badge {{ background:var(--muted); border-radius:6px; padding:2px 10px; font-size:12px; }}
.badge.active {{ background:rgba(34,197,94,.18); color:var(--accent); }}
.badge.trial {{ background:rgba(234,179,8,.18); color:var(--warn); }}
.badge.expired {{ background:rgba(239,68,68,.18); color:var(--danger); }}
.meta {{ color:var(--fg-muted); font-size:13px; margin:8px 0; display:flex; gap:6px 18px; flex-wrap:wrap; }}
.meta svg {{ width:14px; height:14px; vertical-align:-2px; }}
.meta b {{ color:var(--fg); font-weight:500; }}

.thumbs {{ display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; align-items:center; }}
.thumbwrap {{ position:relative; }}
.thumbwrap img {{ width:80px; height:80px; object-fit:cover; border-radius:10px; border:1px solid var(--border); cursor:zoom-in; }}
.thumbwrap img:hover {{ border-color:var(--accent); }}
.thumbwrap .del {{ position:absolute; top:-7px; right:-7px; background:var(--danger); color:#fff; border:0;
  border-radius:50%; width:22px; height:22px; cursor:pointer; display:grid; place-items:center; padding:0; }}
.thumbwrap .del svg {{ width:11px; height:11px; }}
.uploadbtn {{ border-style:dashed; color:var(--fg-muted); height:80px; width:110px; justify-content:center; }}
.actions {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
.goals-preview {{ display:flex; gap:6px; flex-wrap:wrap; margin:4px 0 10px; }}
.gchip {{ background:var(--muted); border:1px solid var(--border); border-radius:999px;
  padding:3px 12px; font-size:12.5px; color:#c6cddb; }}
.gchip.more {{ color:var(--accent); border-color:var(--accent); }}
.catgroup {{ margin-right:14px; }}
.catlabel {{ font-size:11px; text-transform:uppercase; letter-spacing:.4px; color:var(--fg-muted); margin-bottom:5px; }}
.catgroup-thumbs {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
.catgroup .uploadbtn {{ height:64px; width:86px; font-size:11px; }}
.catgroup .thumbwrap img {{ width:64px; height:64px; }}

.logtbl {{ width:100%; border-collapse:collapse; font-size:12.5px; margin-top:10px; }}
.logtbl th, .logtbl td {{ border-bottom:1px solid var(--muted); padding:7px 8px; text-align:left; vertical-align:top; }}
.logtbl th {{ color:var(--fg-muted); font-weight:500; font-size:11px; text-transform:uppercase; letter-spacing:.4px; }}
.logtbl tr:last-child td {{ border-bottom:0; }}
.logtbl img {{ width:64px; height:64px; object-fit:cover; border-radius:8px; cursor:zoom-in; }}
.promptcell {{ max-width:240px; font-size:11px; color:var(--fg-muted); white-space:pre-wrap; word-break:break-word;
  display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; cursor:pointer; }}
.promptcell:hover {{ -webkit-line-clamp:unset; color:var(--fg); }}
.err {{ color:var(--danger); max-width:160px; word-break:break-word; }}
.empty {{ color:var(--fg-muted); font-style:italic; }}

details summary {{ cursor:pointer; color:var(--fg-muted); font-size:13px; margin-top:8px; list-style:none; display:flex; gap:6px; align-items:center; }}
details summary:hover {{ color:var(--fg); }}
details[open] summary {{ color:var(--accent); }}

.modal-bg {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.7); z-index:50; align-items:flex-start; justify-content:center; padding:40px 16px; overflow-y:auto; }}
.modal {{ background:var(--card); border:1px solid var(--border); border-radius:16px; width:560px; max-width:100%; padding:22px; }}
.modal h3 {{ margin:0 0 14px; font-size:17px; }}
.modal .field {{ margin-bottom:14px; }}
.modal label {{ display:block; font-size:12px; color:var(--fg-muted); margin-bottom:5px; }}
.modal textarea {{ width:100%; min-height:110px; resize:vertical; }}
.modal .row {{ display:flex; gap:10px; }}
.modal .row > * {{ flex:1; }}
.modal .foot {{ display:flex; gap:10px; justify-content:flex-end; margin-top:16px; }}

#lightbox {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.94); z-index:100; cursor:zoom-out; align-items:center; justify-content:center; }}
#lightbox img {{ max-width:96vw; max-height:96vh; border-radius:8px; }}

#toasts {{ position:fixed; top:16px; right:16px; z-index:200; display:flex; flex-direction:column; gap:8px; }}
.toast {{ background:var(--card); border:1px solid var(--border); border-left:3px solid var(--accent);
  border-radius:10px; padding:10px 16px; font-size:13px; box-shadow:0 8px 30px rgba(0,0,0,.5); animation:tin .2s ease; }}
.toast.err {{ border-left-color:var(--danger); }}
@keyframes tin {{ from {{ transform:translateX(30px); opacity:0; }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ animation:none !important; transition:none !important; }} }}

.login-wrap {{ min-height:90vh; display:flex; align-items:center; justify-content:center; }}
.login-card {{ background:var(--card); border:1px solid var(--border); border-radius:16px; padding:28px; width:340px; }}
.login-card input {{ width:100%; }}
@media (max-width:640px) {{ body {{ padding:0 12px 30px; }} .thumbs img, .thumbwrap img {{ width:64px; height:64px; }} }}
</style></head><body>{body}
<div id="lightbox" onclick="this.style.display='none'"><img id="lbimg" alt=""></div>
<div id="toasts"></div>
</body></html>"""


async def login_handler(request):
    if request.method == "POST":
        form = await request.post()
        if form.get("password") == settings.ADMIN_WEB_PASSWORD:
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, settings.ADMIN_WEB_PASSWORD, max_age=30 * 24 * 3600)
            raise resp
    body = page(f"""<div class="login-wrap"><div class="login-card">
<h1 style="margin-bottom:6px">Фото будущего</h1>
<p style="color:var(--fg-muted);font-size:13px;margin:0 0 18px">Панель управления</p>
<form method="post"><label style="display:block;font-size:12px;color:var(--fg-muted);margin-bottom:5px" for="pw">Пароль</label>
<input type="password" id="pw" name="password" autofocus>
<button class="primary" style="width:100%;margin-top:14px;justify-content:center">{icon('send')} Войти</button></form>
</div></div>""")
    return web.Response(text=body, content_type="text/html")


def user_card(u, logs) -> str:
    CATS = [("me", "Я"), ("partner", "Партнёр"), ("wish1", "Желание 1"),
            ("wish2", "Желание 2"), ("wish3", "Желание 3")]
    thumbs = ""
    for cat_key, cat_label in CATS:
        cat_thumbs = "".join(
            f'<span class="thumbwrap"><img loading="lazy" src="/photo/{html.escape(p.s3_url.split("/")[-1])}" alt="референс {cat_label}">'
            f'<button class="del" title="Удалить фото" onclick="delPhoto({u.telegram_id}, {p.id}, this)">{icon("trash")}</button></span>'
            for p in u.photos if (p.category or "me") == cat_key)
        uid = str(u.telegram_id)
        up_input = ('<input type="file" id="up' + uid + '_' + cat_key + '" multiple accept="image/*" style="display:none" onchange="uploadPhotos(' + uid + ', \'' + cat_key + '\', this)">')
        up_btn = ('<button class="uploadbtn" onclick="document.getElementById(\'up' + uid + '_' + cat_key + '\').click()">' + icon('upload') + ' Загрузить</button>')
        empty_ph = "<span class='empty'>—</span>"
        thumbs += ('<div class="catgroup"><div class="catlabel">' + cat_label + '</div>'
            + '<span class="catgroup-thumbs">' + (cat_thumbs or empty_ph)
            + up_input + up_btn + '</span></div>')
    goals_text = "\n".join(g.goal_text for g in u.goals)
    tz_opts = "".join(
        f'<option value="{tz}"{" selected" if tz == u.timezone else ""}>{tz}</option>'
        for tz in TIMEZONES)
    delivery_val = u.delivery_time.strftime("%H:%M") if u.delivery_time else ""
    interval = u.interval_days or 1
    freq_opts = "".join(
        f'<option value="{d}"{" selected" if d == interval else ""}>{("каждый день" if d == 1 else f"раз в {d} дн.")}</option>'
        for d in (1, 2, 3, 5, 7, 14, 30))
    interval_label = "каждый день" if interval == 1 else f"раз в {interval} дн."
    # Следующая плановая отправка: последняя генерация + интервал (в таймзоне юзера)
    next_send = "—"
    if u.last_generation_at and u.timezone:
        try:
            next_utc = u.last_generation_at + datetime.timedelta(days=interval)
            next_local = next_utc.replace(tzinfo=pytz.utc).astimezone(pytz.timezone(u.timezone))
            overdue = next_utc < datetime.datetime.utcnow()
            next_send = ("~ " + next_local.strftime("%d.%m %H:%M")) + (" (уже пора)" if overdue else "")
        except Exception:
            pass
    elif not u.last_generation_at:
        next_send = "первая — по расписанию"
    goal_items = [g.goal_text for g in u.goals]
    if goal_items:
        goals_preview = "".join(
            f'<span class="gchip">{html.escape(g)}</span>' for g in goal_items[:3])
        if len(goal_items) > 3:
            goals_preview += f'<span class="gchip more">+{len(goal_items) - 3}</span>'
    else:
        goals_preview = '<span class="empty">целей пока нет</span>'

    log_rows = ""
    for l in logs:
        img_cell = f'<img loading="lazy" src="/genphoto/{html.escape(l.image_path)}" alt="генерация">' if l.image_path else ""
        prompt_cell = f'<div class="promptcell" title="Полный промпт">{html.escape(l.prompt_text)}</div>' if l.prompt_text else ""
        log_rows += (
            f"<tr><td>{fmt_dt(l.sent_at, u.timezone)}</td>"
            f"<td>{'✓' if l.success else '✗'}</td>"
            f"<td>{html.escape(l.source)}</td>"
            f"<td>{html.escape(l.goal_text or '')}</td>"
            f"<td>{img_cell}</td>"
            f"<td>{prompt_cell}</td>"
            f"<td><span class='err'>{html.escape(l.error or '')}</span></td></tr>")
    if not log_rows:
        log_rows = '<tr><td colspan="7" class="empty">отправок пока не было</td></tr>'

    return f"""
<div class="card user" data-status="{u.subscription_status.value}" data-search="{html.escape((u.username or '') + ' ' + str(u.telegram_id)).lower()}">
 <div class="uhead">
  <input type="checkbox" class="sel" data-id="{u.telegram_id}" title="Выбрать">
  <b>@{html.escape(u.username or '—')}</b><span class="uid">{u.telegram_id}</span>
  <span class="badge {u.subscription_status.value}">{u.subscription_status.value}</span>
  <span class="badge">{u.gender or 'пол не указан'}</span>
 </div>
 <div class="meta">
  <span>{icon('clock')} <b>{u.delivery_time or '—'}</b></span>
  <span>{interval_label}</span>
  <span>{u.timezone or 'ТЗ не указана'}</span>
  <span>до <b>{fmt_dt(u.subscription_end_date)}</b></span>
  <span>ген.: <b>{fmt_dt(u.last_generation_at, u.timezone)}</b></span>
  <span>след.: <b style="color:{'var(--warn)' if 'уже пора' in next_send else 'var(--accent)'}">{next_send}</b>
   <span class="badge">{interval_label}</span></span>
 </div>
 <div class="goals-preview">{goals_preview}</div>
 <div class="thumbs">{thumbs}</div>
 <div class="actions">
  <button class="primary" onclick="sendNow({u.telegram_id}, this)">{icon('send')} Отправить сейчас</button>
  <button class="grant" onclick="grant({u.telegram_id}, 30, this)">{icon('plus30')} +30 дн.</button>
  <button class="grant" onclick="grant({u.telegram_id}, 90, this)">{icon('plus90')} +90 дн.</button>
  <button onclick="openEdit({u.telegram_id})">{icon('edit')} Редактировать</button>
 </div>
 <details><summary>{icon('chevron')} История отправок ({len(logs)})</summary>
 <table class="logtbl"><tr><th>Время</th><th></th><th>Тип</th><th>Цель</th><th>Картинка</th><th>Промпт</th><th>Ошибка</th></tr>{log_rows}</table>
 </details>
</div>

<div class="modal-bg" id="m{u.telegram_id}" onclick="if(event.target===this)closeModal({u.telegram_id})">
 <div class="modal">
  <h3>Редактирование — @{html.escape(u.username or '—')}</h3>
  <div class="field"><label>Часовой пояс</label>
   <select id="tz{u.telegram_id}" style="width:100%">{tz_opts}</select></div>
  <div class="field"><label>Время доставки (HH:MM)</label>
   <input type="time" id="dt{u.telegram_id}" value="{delivery_val}" style="width:100%"></div>
  <div class="field"><label>Периодичность</label>
   <select id="iv{u.telegram_id}" style="width:100%">{freq_opts}</select></div>
  <div class="field"><label>Особые пожелания и ограничения к каждому фото (напр.: надпись с именем Ваня, летают голуби, без детей, только мужская компания)</label>
   <input type="text" id="ex{u.telegram_id}" value="{html.escape(u.prompt_extra or '')}" style="width:100%"></div>
  <div class="field"><label>Цели — по одной на строку</label>
   <textarea id="gl{u.telegram_id}">{html.escape(goals_text)}</textarea></div>
  <div class="foot">
   <button onclick="closeModal({u.telegram_id})">Отмена</button>
   <button class="primary" onclick="saveAll({u.telegram_id}, this)">{icon('edit')} Сохранить всё</button>
  </div>
 </div>
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

    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    sent_today = sum(1 for l in logs if l.success and (l.sent_at or datetime.datetime.min).strftime("%Y-%m-%d") == today)
    failed_today = sum(1 for l in logs if not l.success and (l.sent_at or datetime.datetime.min).strftime("%Y-%m-%d") == today)
    n_active = sum(1 for u in users if u.subscription_status.value == "active")
    n_trial = sum(1 for u in users if u.subscription_status.value == "trial")
    n_expired = sum(1 for u in users if u.subscription_status.value == "expired")

    cards = "".join(user_card(u, logs_by_user.get(u.telegram_id, [])) for u in users)
    body = f"""
<header class="topbar"><h1>Фото будущего</h1><span class="uid">панель управления</span>
 <span class="spacer"></span>
 <button onclick="location.reload()">{icon('chevron')} Обновить</button></header>

<div class="stats">
 <div class="stat"><div class="n">{len(users)}</div><div class="l">подписчиков</div></div>
 <div class="stat ok"><div class="n">{n_active}</div><div class="l">активных</div></div>
 <div class="stat"><div class="n">{n_trial}</div><div class="l">на триале</div></div>
 <div class="stat warn"><div class="n">{n_expired}</div><div class="l">истекших</div></div>
 <div class="stat ok"><div class="n">{sent_today}</div><div class="l">отправлено сегодня</div></div>
 <div class="stat bad"><div class="n">{failed_today}</div><div class="l">ошибок сегодня</div></div>
</div>

<div class="filters">
 <span class="search">{icon('search')}
  <input type="text" id="q" placeholder="Поиск по имени или ID" oninput="applyFilters()"></span>
 <span class="chip on" data-f="all" onclick="pickFilter(this)">Все</span>
 <span class="chip" data-f="active" onclick="pickFilter(this)">Активные</span>
 <span class="chip" data-f="trial" onclick="pickFilter(this)">Триал</span>
 <span class="chip" data-f="expired" onclick="pickFilter(this)">Истекшие</span>
 <span class="spacer" style="flex:1"></span>
 <label style="display:flex;gap:6px;align-items:center;font-size:13px;cursor:pointer">
  <input type="checkbox" id="all" onchange="toggleAll(this)"> выделить всех</label>
 <button onclick="sendSelected(this)">{icon('send')} Отправить выбранным</button>
</div>

{cards}

<script>
const $ = id => document.getElementById(id);
function toast(msg, err=false) {{
  const t = document.createElement('div');
  t.className = 'toast' + (err ? ' err' : '');
  t.textContent = msg;
  $('toasts').appendChild(t);
  setTimeout(() => t.remove(), 4000);
}}
let curFilter = 'all';
function pickFilter(el) {{
  document.querySelectorAll('.chip').forEach(c => c.classList.remove('on'));
  el.classList.add('on'); curFilter = el.dataset.f; applyFilters();
}}
function applyFilters() {{
  const q = $('q').value.trim().toLowerCase();
  document.querySelectorAll('.card.user').forEach(c => {{
    const okS = !q || c.dataset.search.includes(q);
    const okF = curFilter === 'all' || c.dataset.status === curFilter;
    c.style.display = (okS && okF) ? '' : 'none';
  }});
}}
function toggleAll(cb) {{ document.querySelectorAll('.sel').forEach(c => c.checked = cb.checked); }}
function openEdit(id) {{ $('m' + id).style.display = 'flex'; }}
function closeModal(id) {{ $('m' + id).style.display = 'none'; }}
async function sendNow(id, btn) {{
  if (!confirm('Сгенерировать и отправить картинку юзеру ' + id + '?')) return;
  btn.disabled = true; toast('⏳ генерация, это занимает 1-2 минуты');
  const r = await fetch('/api/send?id=' + id); const j = await r.json();
  if (j.ok) {{ toast('✅ отправлено юзеру ' + id); setTimeout(() => location.reload(), 1500); }}
  else toast('❌ ' + (j.error || 'ошибка'), true);
  btn.disabled = false;
}}
async function sendSelected(btn) {{
  const ids = [...document.querySelectorAll('.sel')].filter(c => c.checked && c.closest('.card').style.display !== 'none').map(c => c.dataset.id);
  if (!ids.length) {{ toast('Никого не выбрано', true); return; }}
  if (!confirm('Отправить ' + ids.length + ' юзерам?')) return;
  btn.disabled = true; toast('⏳ генерация для ' + ids.length + ' юзеров...');
  const r = await fetch('/api/send?ids=' + ids.join(',')); const j = await r.json();
  toast(j.ok ? '✅ запущено' : '❌ ' + j.error, !j.ok);
  btn.disabled = false;
}}
async function grant(id, days, btn) {{
  if (!confirm('Продлить доступ юзеру ' + id + ' на ' + days + ' дней?')) return;
  btn.disabled = true;
  const r = await fetch('/api/grant?id=' + id + '&days=' + days); const j = await r.json();
  if (j.ok) {{ toast('✅ доступ до ' + j.until); setTimeout(() => location.reload(), 1200); }}
  else toast('❌ ' + j.error, true);
  btn.disabled = false;
}}
async function delPhoto(id, photoId, btn) {{
  if (!confirm('Удалить это фото-референс?')) return;
  btn.disabled = true;
  const r = await fetch('/api/del_photo?id=' + id + '&photo=' + photoId); const j = await r.json();
  if (j.ok) {{ btn.closest('.thumbwrap').remove(); toast('Фото удалено'); }}
  else toast('❌ ' + j.error, true);
}}
async function uploadPhotos(id, cat, input) {{
  if (!input.files.length) return;
  const fd = new FormData();
  for (const f of input.files) fd.append('files', f);
  toast('⏳ загрузка ' + input.files.length + ' фото...');
  const r = await fetch('/api/upload?id=' + id + '&cat=' + cat, {{ method: 'POST', body: fd }}); const j = await r.json();
  if (j.ok) {{ toast('✅ загружено: ' + j.added); setTimeout(() => location.reload(), 1000); }}
  else toast('❌ ' + j.error, true);
  input.value = '';
}}
async function saveAll(id, btn) {{
  btn.disabled = true;
  const body = {{ id, timezone: $('tz' + id).value, delivery_time: $('dt' + id).value,
                 extra: $('ex' + id).value, goals: $('gl' + id).value,
                 interval_days: parseInt($('iv' + id).value) || 1 }};
  const r = await fetch('/api/save_all', {{ method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(body) }});
  const j = await r.json();
  if (j.ok) {{ toast('✅ сохранено (' + j.count + ' целей)'); closeModal(id); setTimeout(() => location.reload(), 1000); }}
  else {{ toast('❌ ' + j.error, true); btn.disabled = false; }}
}}
function lb(src) {{ $('lbimg').src = src; $('lightbox').style.display = 'flex'; }}
document.addEventListener('DOMContentLoaded', () => {{
  document.querySelectorAll('.logtbl td img, .thumbwrap > img').forEach(i => i.onclick = () => lb(i.src));
}});
</script>"""
    return web.Response(text=page(body), content_type="text/html")


_send_locks: set = set()


def task_engine():
    engine = create_async_engine(settings.DATABASE_URL)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


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
                photos = [(p.category or "me", p.s3_url) for p in u.photos]
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
                await record_delivery(u.telegram_id, "manual", goal.goal_text, image_path=img_path,
                                      prompt_text=getattr(result, "scene_text", None))
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


async def api_save_all(request):
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
            u.prompt_extra = (data.get("extra") or "").strip() or None
            try:
                u.interval_days = max(1, int(data.get("interval_days") or 1))
            except (TypeError, ValueError):
                u.interval_days = 1
            goals = [g.strip() for g in (data.get("goals") or "").splitlines()
                     if g.strip() and len(g.strip()) > 2][:10]
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
    cat = request.rel_url.query.get("cat", "me")
    if cat not in ("me", "partner", "wish1", "wish2", "wish3"):
        cat = "me"
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
                session.add(Photo(user_id=uid, s3_url=f"http://host.docker.internal:8000/{name}", category=cat))
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
routes.router.add_post("/api/save_all", api_save_all)
routes.router.add_post("/api/upload", api_upload)
routes.router.add_get("/api/del_photo", api_del_photo)
routes.router.add_get("/photo/{name}", photo_handler)
routes.router.add_get("/genphoto/{path:.*}", genphoto_handler)

if __name__ == "__main__":
    web.run_app(routes, host="0.0.0.0", port=8080, print=None)
