import json
import os
import logging
import datetime
from typing import Optional, Dict, Any, List, Tuple

import httpx
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup
from dotenv import load_dotenv

# ----------------- НАСТРОЙКИ -----------------

# Загрузка переменных окружения из .env
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
GROQ_MODEL = "llama-3.3-70b-versatile"
MANAGER_IDS: List[int] = [390197983]

REQUESTS_FILE = "requests.json"
USERS_FILE = "users.json"
AI_LOGS_FILE = "ai_logs.json"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

requests_storage: List[Dict[str, Any]] = []
user_states: Dict[int, Dict[str, Any]] = {}
users_profile: Dict[str, Any] = {}

# Статусы заявок
STATUS_NEW = "new"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
STATUS_CANCELED_BY_CLIENT = "canceled_by_client"
STATUS_CANCELED = "canceled"

ALL_STATUSES = {STATUS_NEW, STATUS_IN_PROGRESS, STATUS_DONE, STATUS_CANCELED_BY_CLIENT, STATUS_CANCELED}

# Типы клиентов
CLIENT_FREELANCER = "freelancer"
CLIENT_BUSINESS = "business"
CLIENT_AGENCY = "agency"


# ---------- Утилиты ----------

def load_requests() -> None:
    global requests_storage
    if not os.path.exists(REQUESTS_FILE):
        requests_storage = []
        return
    try:
        with open(REQUESTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        requests_storage = data if isinstance(data, list) else []
    except Exception as e:
        logging.error(f"Ошибка загрузки requests: {e}")
        requests_storage = []


def save_requests() -> None:
    try:
        with open(REQUESTS_FILE, "w", encoding="utf-8") as f:
            json.dump(requests_storage, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения requests: {e}")


def load_users() -> None:
    global users_profile
    if not os.path.exists(USERS_FILE):
        users_profile = {"users": {}, "meta": {"total_users": 0}}
        return
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            users_profile = data if "users" in data else {"users": data, "meta": {"total_users": len(data)}}
        else:
            users_profile = {"users": {}, "meta": {"total_users": 0}}
    except Exception as e:
        logging.error(f"Ошибка загрузки users: {e}")
        users_profile = {"users": {}, "meta": {"total_users": 0}}


def save_users() -> None:
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_profile, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения users: {e}")


def users_dict() -> Dict[str, Any]:
    return users_profile.setdefault("users", {})


def users_meta() -> Dict[str, Any]:
    return users_profile.setdefault("meta", {"total_users": 0})


def get_new_request_id() -> int:
    return 1 if not requests_storage else max(int(r.get("id", 0)) for r in requests_storage) + 1


def get_last_request_by_user(user_id: int) -> Optional[Dict[str, Any]]:
    for r in reversed(requests_storage):
        if r.get("user_id") == user_id:
            return r
    return None


def get_completed_requests_count(user_id: int) -> int:
    """Считает количество успешно завершённых заявок пользователя"""
    return sum(1 for r in requests_storage if r.get("user_id") == user_id and r.get("status") == STATUS_DONE)


def is_first_request(user_id: int) -> bool:
    """Проверяет, первая ли это заявка пользователя"""
    user_reqs = [r for r in requests_storage if r.get("user_id") == user_id]
    return len(user_reqs) == 0


def calculate_commission(amount: float, is_first: bool = False) -> Tuple[float, float]:
    """Расчёт комиссии с учётом специальных условий для первой заявки"""
    if is_first:
        if amount <= 500:
            percent = 15.0
        elif amount <= 1500:
            percent = 10.0
        else:
            percent = 6.0
    else:
        if amount <= 500:
            percent = 15.0
        elif amount <= 1500:
            percent = 10.0
        elif amount <= 3000:
            percent = 6.0
        else:
            percent = 5.0

    fee = round(amount * percent / 100.0, 2)
    return percent, fee


async def send_safe(chat_id: int, text: str, *, parse_mode: Optional[str] = None) -> None:
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"Ошибка отправки {chat_id}: {e}")


def format_request_for_manager(req: Dict[str, Any]) -> str:
    """Форматирование заявки для уведомления менеджера"""
    first_badge = "🎁 ПЕРВАЯ ЗАЯВКА" if req.get("is_first_request") else ""

    return (
        f"📝 НОВАЯ ЗАЯВКА НА АРЕНДУ КАРТЫ {first_badge}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID заявки: #{req['id']}\n\n"
        f"👤 Клиент: {req['full_name']}\n"
        f"🔑 User ID: {req['user_id']}\n"
        f"📱 Username: @{req['username'] if req['username'] else 'не указан'}\n\n"
        f"💰 Сумма: {req['amount']:.2f} $\n"
        f"📊 Ставка: {req['percent']:.0f}%\n"
        f"💸 Комиссия: {req['fee']:.2f} $\n"
        f"💵 Итого: {req['total']:.2f} $\n\n"
        f"💳 Способ оплаты: {req['payment_method']}\n"
        f"💬 Комментарий: {req['comment'] if req['comment'] else '—'}\n\n"
        f"📌 Статус: {req['status']}"
    )


def format_cancel_for_manager(req: Dict[str, Any]) -> str:
    """Форматирование отмены заявки для уведомления менеджера"""
    return (
        "❌ КЛИЕНТ ОТМЕНИЛ ЗАЯВКУ\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 ID заявки: #{req['id']}\n\n"
        f"👤 Клиент: {req['full_name']}\n"
        f"🔑 User ID: {req['user_id']}\n"
        f"📱 Username: @{req['username'] if req['username'] else 'не указан'}\n\n"
        f"💰 Сумма заявки: {req['amount']:.2f} $\n"
        f"💳 Способ оплаты: {req['payment_method']}\n\n"
        f"🔴 Новый статус: отменена клиентом"
    )


def format_ai_query_for_manager(user_id: int, username: str, full_name: str, question: str, answer: str) -> str:
    """Форматирование обращения к ИИ для уведомления менеджера"""
    short_answer = answer[:500] + "..." if len(answer) > 500 else answer

    return (
        "🤖 ОБРАЩЕНИЕ К ИИ-ПОМОЩНИКУ\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 Клиент: {full_name}\n"
        f"🔑 User ID: {user_id}\n"
        f"📱 Username: @{username if username else 'не указан'}\n\n"
        f"❓ Вопрос:\n{question}\n\n"
        f"💬 Ответ ИИ:\n{short_answer}"
    )


def log_ai_interaction(user_id: int, username: str, full_name: str, question: str, answer: str) -> None:
    """Логирование обращений к ИИ в файл"""
    try:
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "question": question,
            "answer": answer
        }

        ai_logs = []
        if os.path.exists(AI_LOGS_FILE):
            try:
                with open(AI_LOGS_FILE, "r", encoding="utf-8") as f:
                    ai_logs = json.load(f)
            except:
                ai_logs = []

        ai_logs.append(log_entry)

        with open(AI_LOGS_FILE, "w", encoding="utf-8") as f:
            json.dump(ai_logs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка логирования ИИ: {e}")


def is_active_status(status: str) -> bool:
    return status in (STATUS_NEW, STATUS_IN_PROGRESS)


def pretty_status(status: str) -> str:
    mapping = {
        STATUS_NEW: "новая (ожидает обработки)",
        STATUS_IN_PROGRESS: "в обработке",
        STATUS_DONE: "завершена",
        STATUS_CANCELED_BY_CLIENT: "отменена клиентом",
        STATUS_CANCELED: "отменена сервисом",
    }
    return mapping.get(status, status)


def is_manager(user_id: int) -> bool:
    return user_id in MANAGER_IDS


def get_client_type(user_id: int) -> Optional[str]:
    u = users_dict().get(str(user_id))
    return u.get("client_type") if u else None


def set_client_type(user_id: int, client_type: str) -> None:
    users_dict().setdefault(str(user_id), {})["client_type"] = client_type
    save_users()


def client_type_label(client_type: Optional[str]) -> str:
    return {
        CLIENT_FREELANCER: "Таргетолог / SMM",
        CLIENT_BUSINESS: "Малый бизнес",
        CLIENT_AGENCY: "Агентство / медиабаинг",
    }.get(client_type, "Не указан")


def format_last_requests(limit: int = 20) -> str:
    if not requests_storage:
        return "Заявок пока нет."
    lines = ["📋 Последние заявки:"]
    for r in reversed(requests_storage[-limit:]):
        first_badge = "🎁" if r.get("is_first_request") else ""
        lines.append(
            f"{first_badge}ID: {r.get('id')} | user_id: {r.get('user_id')} | "
            f"сумма: {float(r.get('amount', 0)):.2f}$ | "
            f"статус: {pretty_status(r.get('status', ''))} | оплата: {r.get('payment_method')}"
        )
    return "\n".join(lines)


def build_stats() -> str:
    if not requests_storage:
        return "Статистика заявок:\n\nЗаявок пока нет."

    by_status = {s: 0 for s in ALL_STATUSES}
    sum_amount = 0.0
    count = 0
    first_requests = 0

    for r in requests_storage:
        status = r.get("status", "")
        if status in by_status:
            by_status[status] += 1
        if r.get("is_first_request"):
            first_requests += 1
        try:
            sum_amount += float(r.get("amount", 0) or 0)
            count += 1
        except (TypeError, ValueError):
            pass

    avg = sum_amount / count if count else 0.0

    return (
        "📊 Статистика заявок:\n\n"
        f"Всего заявок: *{len(requests_storage)}*\n"
        f"🎁 Первых заявок: *{first_requests}*\n"
        f"Новых: *{by_status[STATUS_NEW]}*\n"
        f"В обработке: *{by_status[STATUS_IN_PROGRESS]}*\n"
        f"Завершённых: *{by_status[STATUS_DONE]}*\n"
        f"Отменено клиентами: *{by_status[STATUS_CANCELED_BY_CLIENT]}*\n"
        f"Отменено сервисом: *{by_status[STATUS_CANCELED]}*\n\n"
        f"Средняя сумма заявки: *{avg:.2f} $*"
    )


def build_user_stats(user_id: int) -> str:
    user_reqs = [r for r in requests_storage if r.get("user_id") == user_id]
    if not user_reqs:
        return "У вас пока нет заявок.\nНажмите «📝 Оставить заявку на аренду», чтобы оформить первую."

    sum_amount = sum(float(r.get("amount", 0) or 0) for r in user_reqs)
    avg = sum_amount / len(user_reqs)
    active = sum(1 for r in user_reqs if is_active_status(r.get("status", "")))
    canceled = sum(1 for r in user_reqs if r.get("status") == STATUS_CANCELED_BY_CLIENT)
    completed = sum(1 for r in user_reqs if r.get("status") == STATUS_DONE)

    return (
        "📊 Ваша статистика по заявкам:\n\n"
        f"Всего заявок: *{len(user_reqs)}*\n"
        f"Завершённых: *{completed}*\n"
        f"Суммарная сумма: *{sum_amount:.2f} $*\n"
        f"Средняя сумма заявки: *{avg:.2f} $*\n"
        f"Сейчас активных заявок: *{active}*\n"
        f"Отменено вами: *{canceled}*"
    )


def build_users_stats() -> str:
    meta = users_meta()
    return (
        "👥 Статистика по пользователям:\n\n"
        f"Всего уникальных пользователей: *{meta.get('total_users', 0)}*\n"
        f"Текущих записей в профилях: *{len(users_dict())}*\n\n"
        "Счётчик увеличивается при первом заходе пользователя в бота."
    )


def build_users_list() -> str:
    u_all = users_dict()
    if not u_all:
        return "Пользователей пока нет."

    lines = [f"Пользователи, которые заходили в бота (всего: {len(u_all)}):\n"]
    for uid_str in sorted(u_all.keys(), key=lambda x: (u_all[x].get("username", "").lower(), int(x))):
        data = u_all[uid_str]
        username = data.get("username") or ""
        label = client_type_label(data.get("client_type"))
        user_label = f"@{username}" if username else f"ID {uid_str}"

        user_reqs_count = len([r for r in requests_storage if r.get("user_id") == int(uid_str)])
        lines.append(f"- {user_label} | Тип: {label} | Заявок: {user_reqs_count}")
    return "\n".join(lines)


def find_user_by_username(username: str) -> Optional[int]:
    username = username.lower()
    for uid_str, data in users_dict().items():
        if (data.get("username") or "").lower() == username:
            return int(uid_str)
    return None


def build_admin_help() -> str:
    return (
        "Админ-команды:\n"
        "/last_requests – последние заявки\n"
        "/stats – общая статистика по заявкам\n"
        "/clear_requests – очистить базу заявок\n"
        "/users_stats – статистика по пользователям\n"
        "/users_list – список пользователей\n"
        "/user_info <id или @username> – инфо по пользователю\n"
        "/set_status <request_id> <status> – сменить статус заявки\n"
        "/broadcast – отправить сообщение всем пользователям\n"
        "/ai_stats – статистика обращений к ИИ\n"
        "/clear_ai_logs – очистить логи ИИ\n\n"
        "Статусы: new, in_progress, done, canceled_by_client, canceled"
    )


# ---------- Groq ----------

async def ask_groq(prompt: str) -> str:
    if not GROQ_API_KEY:
        return "Groq API ключ не настроен."

    system_prompt = """Ты — умный, вежливый и профессиональный русскоязычный ИИ-ассистент сервиса AdsPay Cards (аренда виртуальных карт для оплаты рекламы и онлайн-сервисов).

📌 О СЕРВИСЕ AdsPay Cards:
• Мы помогаем оплачивать зарубежную рекламу (Facebook/Instagram, Google Ads, TikTok Ads) и онлайн-сервисы
• Клиенты: таргетологи, SMM-специалисты, малый бизнес, агентства, медиабаинг
• Оформление заявки — через этот Telegram-бот
• Менеджер связывается с клиентом после оформления заявки

💰 УСЛОВИЯ АРЕНДЫ И КОМИССИИ:

🎁 ДЛЯ ПЕРВОЙ ЗАЯВКИ (приветственные условия):
• Минимальная сумма: от 50 $ (чтобы протестировать сервис)
• Сумма 50–500 $ → комиссия 15%
• Сумма 500–1500 $ → комиссия 10%
• Сумма от 1500 $ → комиссия 6%

📋 ДЛЯ ПОСЛЕДУЮЩИХ ЗАЯВОК:
• Минимальная сумма: от 100 $
• Сумма 100–500 $ → комиссия 15%
• Сумма 500–1500 $ → комиссия 10%
• Сумма 1500–3000 $ → комиссия 6%
• Сумма от 3000 $ → комиссия 5%
• При бюджетах от 5000 $ возможны индивидуальные условия

ВАЖНО: Первая заявка — это возможность протестировать сервис с минимальными вложениями (от 50$) и убедиться в качестве работы!

💳 СПОСОБЫ ОПЛАТЫ:
• BYN (белорусский рубль)
• Карта МИР
• USDT TRC-20
• Точные суммы и курс клиент согласует с менеджером

❓ ЧАСТЫЕ ВОПРОСЫ:

1. Почему первая заявка от 50$, а последующие от 100$?
   → Мы хотим дать возможность новым клиентам протестировать сервис с минимальными рисками. После успешного первого опыта клиенты обычно доверяют нам больше и делают более крупные заявки.

2. Сколько времени обрабатывается заявка?
   → Обычно менеджер выходит на связь в течение рабочего времени после оформления заявки.

3. Какие сервисы можно оплачивать?
   → Рекламные кабинеты Facebook/Instagram, Google Ads, TikTok Ads и другие онлайн-сервисы — по согласованию с менеджером.

4. Насколько это безопасно?
   → Мы не запрашиваем доступ к аккаунтам клиента. Оплата согласовывается и проводится по правилам платёжных систем.

5. Как оформить заявку?
   → Нажать кнопку «📝 Оставить заявку на аренду» в боте, ввести сумму, выбрать способ оплаты, написать комментарий. После этого менеджер свяжется.

6. Как посчитать комиссию?
   → Просто спроси меня! Например: «Посчитай комиссию для 750 долларов» — и я рассчитаю. Не забудь уточнить, первая ли это заявка.

🎯 ТВОЯ ЗАДАЧА:
• Если вопрос про сервис, условия, оплату, FAQ — отвечай на основе информации выше
• Если вопрос про комиссию/расчёт — уточни, первая ли это заявка, и посчитай сам по формулам выше
• Подчёркивай преимущество первой заявки от 50$ как возможность протестировать сервис
• Если вопрос НЕ про сервис (маркетинг, реклама, бизнес, жизнь, учёба, технологии, программирование и т.д.) — отвечай как высококлассный универсальный ИИ-помощник
• Отвечай кратко, понятным языком, без лишней «воды»
• Будь дружелюбным и профессиональным
• Если что-то нужно объяснить — делай это простыми словами и по шагам"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 1024,
                    "temperature": 0.7,
                }
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except:
        return "Не удалось связаться с ИИ-помощником. Попробуйте позже."


# ---------- Клавиатуры ----------

main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📝 Оставить заявку на аренду"), KeyboardButton(text="📦 Статус моей заявки")],
        [KeyboardButton(text="❌ Отменить мою заявку")],
        [KeyboardButton(text="🤖 ИИ‑помощник")],
    ],
    resize_keyboard=True
)

payment_menu = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="BYN"), KeyboardButton(text="Карта МИР"), KeyboardButton(text="USDT TRC-20")]],
    resize_keyboard=True
)

client_type_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👤 Таргетолог / SMM")],
        [KeyboardButton(text="🏪 Малый бизнес")],
        [KeyboardButton(text="🏢 Агентство / медиабаинг")],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


# ---------- Хендлеры ----------

@router.message(lambda msg: msg.text == "/start")
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = (message.from_user.full_name or "").strip() or "без имени"

    user_states.pop(user_id, None)

    u_all = users_dict()
    meta = users_meta()
    is_new = str(user_id) not in u_all

    if is_new:
        u_all[str(user_id)] = {"client_type": None, "username": username}
        meta["total_users"] = int(meta.get("total_users", 0)) + 1
        save_users()

        for mid in MANAGER_IDS:
            await send_safe(
                mid,
                f"👤 НОВЫЙ ПОЛЬЗОВАТЕЛЬ В БОТЕ\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔑 ID: {user_id}\n"
                f"👨‍💼 Имя: {full_name}\n"
                f"📱 Username: @{username or 'не указан'}\n\n"
                f"📊 Всего пользователей: {meta['total_users']}"
            )
    else:
        u_all[str(user_id)]["username"] = username
        save_users()

    ctype = get_client_type(user_id)
    if not ctype:
        user_states[user_id] = {"step": "choose_client_type"}
        await message.answer("Привет! Я бот сервиса аренды карт AdsPay Cards.\n\nЧтобы лучше помочь, расскажи, кто ты:",
                             reply_markup=client_type_menu)
        return

    extra = "\n\nАдмин-команды: /help" if is_manager(user_id) else ""

    if is_first_request(user_id):
        welcome_bonus = "\n\n🎁 *Специальное предложение для новых клиентов:*\nПервая заявка от 50$ — протестируйте наш сервис с минимальными вложениями!"
    else:
        welcome_bonus = ""

    await message.answer(
        "Привет! Я бот сервиса аренды карт AdsPay Cards.\n\n"
        "Что я могу:\n"
        "• 📝 Оставить заявку на аренду\n"
        "• 📦 Показать статус заявки\n"
        "• 🤖 ИИ-помощник — ответит на любые вопросы о сервисе, условиях, комиссиях, а также поможет с маркетингом, рекламой и другими темами"
        f"{welcome_bonus}"
        f"{extra}",
        reply_markup=main_menu,
        parse_mode="Markdown"
    )


@router.message(lambda msg: msg.text == "/help")
async def cmd_help(message: Message):
    base = (
        "Команды бота:\n"
        "/start – начать заново\n"
        "/profile – выбрать тип\n"
        "/my_stats – ваша статистика по заявкам\n"
        "/ai <вопрос> – задать вопрос ИИ-помощнику\n\n"
        "Или нажмите кнопку «🤖 ИИ‑помощник» и напишите вопрос.\n\n"
        "ИИ-помощник знает всё о сервисе, условиях аренды, комиссиях, способах оплаты и поможет с любыми вопросами!"
    )
    if is_manager(message.from_user.id):
        base += "\n\n" + build_admin_help()
    await message.answer(base)


@router.message(lambda msg: msg.text and msg.text.startswith("/ai"))
async def cmd_ai(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        await message.answer(
            "Напишите вопрос после команды.\n\n"
            "Например:\n"
            "/ai какие условия аренды?\n"
            "/ai посчитай комиссию для 1200 долларов\n"
            "/ai как настроить таргет в Facebook?"
        )
        return

    question = parts[1].strip()
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = (message.from_user.full_name or "").strip() or "без имени"

    await message.answer("Думаю над ответом...")
    answer = await ask_groq(question)
    await message.answer(answer)

    # Логирование в файл
    log_ai_interaction(user_id, username, full_name, question, answer)

    # Уведомление менеджеру
    for mid in MANAGER_IDS:
        await send_safe(mid, format_ai_query_for_manager(user_id, username, full_name, question, answer))


@router.message(lambda msg: msg.text == "/my_stats")
async def cmd_my_stats(message: Message):
    await message.answer(build_user_stats(message.from_user.id), parse_mode="Markdown", reply_markup=main_menu)


@router.message(lambda msg: msg.text == "/last_requests")
async def cmd_last_requests(message: Message):
    if is_manager(message.from_user.id):
        await message.answer(format_last_requests())


@router.message(lambda msg: msg.text == "/stats")
async def cmd_stats(message: Message):
    if is_manager(message.from_user.id):
        await message.answer(build_stats(), parse_mode="Markdown")


@router.message(lambda msg: msg.text == "/users_stats")
async def cmd_users_stats(message: Message):
    if is_manager(message.from_user.id):
        await message.answer(build_users_stats(), parse_mode="Markdown")


@router.message(lambda msg: msg.text == "/users_list")
async def cmd_users_list(message: Message):
    if is_manager(message.from_user.id):
        await message.answer(build_users_list())


@router.message(lambda msg: msg.text == "/ai_stats")
async def cmd_ai_stats(message: Message):
    if not is_manager(message.from_user.id):
        return

    if not os.path.exists(AI_LOGS_FILE):
        await message.answer("Обращений к ИИ пока не было.")
        return

    try:
        with open(AI_LOGS_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)

        total = len(logs)
        unique_users = len(set(log.get("user_id") for log in logs))

        # Последние 5 обращений
        recent = logs[-5:]
        recent_text = "\n\n".join([
            f"👤 {log.get('username', 'неизвестен')}: {log.get('question', '')[:50]}..."
            for log in reversed(recent)
        ])

        await message.answer(
            f"📊 Статистика ИИ-помощника:\n\n"
            f"Всего обращений: *{total}*\n"
            f"Уникальных пользователей: *{unique_users}*\n\n"
            f"Последние вопросы:\n{recent_text}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"Ошибка чтения логов: {e}")


@router.message(lambda msg: msg.text == "/clear_ai_logs")
async def cmd_clear_ai_logs(message: Message):
    if not is_manager(message.from_user.id):
        return

    if not os.path.exists(AI_LOGS_FILE):
        await message.answer("Логи ИИ пустые.")
        return

    try:
        with open(AI_LOGS_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
        count = len(logs)

        os.remove(AI_LOGS_FILE)
        await message.answer(f"✅ Удалено {count} записей из логов ИИ.")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


@router.message(lambda msg: msg.text in ["👤 Таргетолог / SMM", "🏪 Малый бизнес", "🏢 Агентство / медиабаинг"])
async def choose_client_type(message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state or state.get("step") != "choose_client_type":
        return

    ctype = {
        "👤 Таргетолог / SMM": CLIENT_FREELANCER,
        "🏪 Малый бизнес": CLIENT_BUSINESS,
        "🏢 Агентство / медиабаинг": CLIENT_AGENCY
    }[message.text]

    set_client_type(user_id, ctype)
    user_states.pop(user_id, None)

    if is_first_request(user_id):
        welcome_msg = "\n\n🎁 *Специальное предложение:*\nВаша первая заявка может быть от 50$ — отличная возможность п��отестировать сервис!"
    else:
        welcome_msg = ""

    await message.answer(
        f"Отлично, профиль сохранён.\n\n"
        "Теперь вы можете:\n"
        "• оформить заявку — «📝 Оставить заявку на аренду»\n"
        f"• задать любой вопрос ИИ-помощнику — «🤖 ИИ‑помощник»{welcome_msg}",
        reply_markup=main_menu,
        parse_mode="Markdown"
    )


@router.message(lambda msg: msg.text == "🤖 ИИ‑помощник")
async def ai_button(message: Message):
    user_states[message.from_user.id] = {"step": "ai_wait_question"}
    await message.answer(
        "Задайте любой вопрос! Я помогу с:\n\n"
        "• Условиями аренды и комиссиями\n"
        "• Расчётом стоимости\n"
        "• Способами оплаты\n"
        "• Частыми вопросами о сервисе\n"
        "• Вопросами по маркетингу и рекламе\n"
        "• Любыми другими темами!\n\n"
        "Например:\n"
        "«Какие условия для первой заявки?»\n"
        "«Посчитай комиссию для 800 долларов»\n"
        "«Как настроить ретаргетинг в Instagram?»"
    )


@router.message(lambda msg: msg.text == "📝 Оставить заявку на аренду")
async def new_request_start(message: Message):
    user_id = message.from_user.id

    last = get_last_request_by_user(user_id)
    if last and is_active_status(last.get("status", "")):
        await message.answer(
            "У вас уже есть активная заявка.\n"
            "С вами свяжется менеджер. Если хотите отменить — используйте «❌ Отменить мою заявку».",
            reply_markup=main_menu
        )
        return

    is_first = is_first_request(user_id)
    user_states[user_id] = {"step": "request_amount", "temp_data": {"is_first": is_first}}

    if is_first:
        await message.answer(
            "🎁 Отлично! Это будет ваша первая заявка.\n\n"
            "Специальные условия для новых клиентов:\n"
            "• Минимальная сумма: от *50 $* (вместо обычных 100$)\n"
            "• Комиссия 15% для сумм до 500$\n"
            "• Комиссия 10% для сумм 500-1500$\n"
            "• Комиссия 6% для сумм от 1500$\n\n"
            "1️⃣ Введите сумму в *$* (от 50$).\n\n"
            "Например: `50`, `100`, `300` или `500`",
            parse_mode="Markdown",
            reply_markup=main_menu
        )
    else:
        await message.answer(
            "Окей, давайте оформим заявку.\n\n"
            "1️⃣ Введите сумму в *$* (минимум 100$).\n\n"
            "Например: `100`, `500`, `1500` или `2500`",
            parse_mode="Markdown",
            reply_markup=main_menu
        )


@router.message(lambda msg: msg.text in ["BYN", "Карта МИР", "USDT TRC-20"])
async def handle_payment_method(message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)

    if not state or state.get("step") != "request_payment_method":
        return

    state["temp_data"]["payment_method"] = message.text
    user_states[user_id]["step"] = "request_comment"

    await message.answer(
        "3️⃣ Напишите комментарий к заявке (например: когда удобно, дополнительные пожелания).\n\n"
        "Если ничего добавлять не хотите — напишите `нет`.",
        reply_markup=main_menu
    )


@router.message(lambda msg: msg.text and msg.text.replace(".", "", 1).replace(",", "").isdigit())
async def handle_number(message: Message):
    user_id = message.from_user.id

    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("Не удалось распознать сумму. Введите только число.", reply_markup=main_menu)
        return

    state = user_states.get(user_id)

    if state and state.get("step") == "ai_wait_question":
        return

    if state and state.get("step") == "request_amount":
        is_first = state["temp_data"].get("is_first", False)
        min_amount = 50 if is_first else 100

        if amount < min_amount:
            if is_first:
                await message.answer(
                    f"Минимальная сумма для первой заявки: *50 $*\n\n"
                    f"Вы ввели: *{amount:.2f} $*\n\n"
                    "Пожалуйста, введите сумму не менее 50$.",
                    parse_mode="Markdown",
                    reply_markup=main_menu
                )
            else:
                await message.answer(
                    f"Минимальная сумма для заявки: *100 $*\n\n"
                    f"Вы ввели: *{amount:.2f} $*\n\n"
                    "Пожалуйста, введите сумму не менее 100$.",
                    parse_mode="Markdown",
                    reply_markup=main_menu
                )
            return

        percent, fee = calculate_commission(amount, is_first)
        total = round(amount + fee, 2)

        state["temp_data"]["amount"] = amount
        user_states[user_id]["step"] = "request_payment_method"

        first_badge = "🎁 " if is_first else ""

        await message.answer(
            f"{first_badge}📊 Предварительный расчёт:\n\n"
            f"Сумма: *{amount:.2f} $*\n"
            f"Ставка: *{percent:.0f}%*\n"
            f"Комиссия: *{fee:.2f} $*\n"
            f"Ориентировочно к оплате: *{total:.2f} $*\n\n"
            "2️⃣ Теперь выберите способ оплаты:",
            parse_mode="Markdown",
            reply_markup=payment_menu
        )
        return

    return


@router.message(lambda msg: True)
async def handle_all_text(message: Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()
    text_lower = text.lower()
    state = user_states.get(user_id)

    # ИИ ждёт вопрос
    if state and state.get("step") == "ai_wait_question":
        if not text:
            return

        user_states.pop(user_id, None)
        username = message.from_user.username or ""
        full_name = (message.from_user.full_name or "").strip() or "без имени"

        await message.answer("Думаю над ответом...")
        answer = await ask_groq(text)
        await message.answer(answer, reply_markup=main_menu)

        # Логирование в файл
        log_ai_interaction(user_id, username, full_name, text, answer)

        # Уведомление менеджеру
        for mid in MANAGER_IDS:
            await send_safe(mid, format_ai_query_for_manager(user_id, username, full_name, text, answer))

        return

    # Подтверждение очистки базы заявок
    if state and state.get("step") == "confirm_clear_requests" and is_manager(user_id):
        if text == "УДАЛИТЬ ВСЕ ЗАЯВКИ":
            count = len(requests_storage)
            requests_storage.clear()
            save_requests()
            user_states.pop(user_id, None)
            await message.answer(f"✅ Все заявки были удалены из базы.\n\nУдалено заявок: {count}",
                                 reply_markup=main_menu)
        else:
            user_states.pop(user_id, None)
            await message.answer("Операция отменена.", reply_markup=main_menu)
        return

    # Менеджер: рассылка
    if state and state.get("step") == "broadcast_wait_text" and is_manager(user_id):
        if not text:
            await message.answer("Текст рассылки не может быть пустым.")
            return

        user_states.pop(user_id, None)
        success = failed = 0
        for uid in [int(u) for u in users_dict().keys()]:
            try:
                await send_safe(uid, text)
                success += 1
            except:
                failed += 1

        await message.answer(f"Рассылка завершена.\nУспешно: {success}\nОшибок: {failed}", reply_markup=main_menu)
        return

    # Админ: /user_info
    if is_manager(user_id) and text.startswith("/user_info"):
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            await message.answer("Используйте: /user_info <id или @username>")
            return

        arg = parts[1].strip()
        target_id = find_user_by_username(arg[1:]) if arg.startswith("@") else (int(arg) if arg.isdigit() else None)

        if not target_id:
            await message.answer("Пользователь не найден.")
            return

        u = users_dict().get(str(target_id))
        if not u:
            await message.answer("Этот пользователь ещё не заходил в бота.")
            return

        user_reqs = [r for r in requests_storage if r.get("user_id") == target_id]
        last_req = user_reqs[-1] if user_reqs else None
        completed = sum(1 for r in user_reqs if r.get("status") == STATUS_DONE)

        resp = (
            f"Информация о пользователе:\n\n"
            f"ID: {target_id}\n"
            f"Юзернейм: @{u.get('username') or 'нет'}\n"
            f"Тип клиента: {client_type_label(u.get('client_type'))}\n"
            f"Всего заявок: {len(user_reqs)}\n"
            f"Завершённых: {completed}\n"
        )
        if last_req:
            resp += f"\nПоследняя заявка:\nID: {last_req.get('id')}\nСумма: {float(last_req.get('amount', 0)):.2f} $\nСтатус: {pretty_status(last_req.get('status', ''))}"

        await message.answer(resp)
        return

    # Админ: /set_status
    if is_manager(user_id) and text.startswith("/set_status"):
        parts = text.split()
        if len(parts) != 3:
            await message.answer(
                "Используйте: /set_status <request_id> <status>\nstatus: new, in_progress, done, canceled_by_client, canceled")
            return

        req_id_str, status = parts[1], parts[2]
        if not req_id_str.isdigit() or status not in ALL_STATUSES:
            await message.answer("Неверный формат команды.")
            return

        req_id = int(req_id_str)
        target_req = next((r for r in requests_storage if int(r.get("id", 0)) == req_id), None)

        if not target_req:
            await message.answer(f"Заявка с ID {req_id} не найдена.")
            return

        old_status = target_req.get("status")
        target_req["status"] = status
        save_requests()

        await message.answer(
            f"Статус заявки {req_id} изменён с '{pretty_status(old_status)}' на '{pretty_status(status)}'.")

        if target_req.get("user_id"):
            await send_safe(target_req["user_id"],
                            f"Статус вашей заявки ID {req_id} был обновлён: {pretty_status(status)}.")
        return

    # Админ: /broadcast
    if text == "/broadcast" and is_manager(user_id):
        user_states[user_id] = {"step": "broadcast_wait_text"}
        await message.answer(
            f"Режим рассылки.\n\n"
            f"Сейчас в базе пользователей: {len(users_dict())}.\n"
            "Отправьте текст сообщения, которое нужно разослать всем пользователям.\n\n"
            "Форматирование Markdown лучше не использовать, чтобы не было ошибок.",
            reply_markup=main_menu
        )
        return

    # Админ: /clear_requests
    if text == "/clear_requests" and is_manager(user_id):
        if not requests_storage:
            await message.answer("База заявок уже пуста.", reply_markup=main_menu)
            return

        user_states[user_id] = {"step": "confirm_clear_requests"}
        await message.answer(
            f"⚠️ Вы собираетесь *удалить все заявки* из базы.\n\n"
            f"Сейчас в базе заявок: *{len(requests_storage)}*.\n\n"
            "Если вы уверены, напишите:\n`УДАЛИТЬ ВСЕ ЗАЯВКИ`\n\n"
            "Любой другой ответ отменит операцию.",
            parse_mode="Markdown",
            reply_markup=main_menu
        )
        return

    # Комментарий к заявке
    if state and state.get("step") == "request_comment":
        temp = state["temp_data"]
        amount = float(temp.get("amount", 0))
        payment_method = temp.get("payment_method", "")
        is_first = temp.get("is_first", False)
        comment = "" if text_lower == "нет" else text

        req_id = get_new_request_id()
        percent, fee = calculate_commission(amount, is_first)
        total = round(amount + fee, 2)

        new_req = {
            "id": req_id,
            "user_id": user_id,
            "username": message.from_user.username or "",
            "full_name": (message.from_user.full_name or "").strip() or "без имени",
            "amount": amount,
            "percent": percent,
            "fee": fee,
            "total": total,
            "payment_method": payment_method,
            "comment": comment,
            "status": STATUS_NEW,
            "is_first_request": is_first,
        }

        requests_storage.append(new_req)
        save_requests()
        user_states.pop(user_id, None)

        first_badge = "🎁 " if is_first else ""
        first_msg = "\n\n🎉 Это ваша первая заявка! Спасибо за доверие к нашему сервису." if is_first else ""

        await message.answer(
            f"{first_badge}✅ Ваша заявка на аренду карты оформлена!\n\n"
            f"ID заявки: *{req_id}*\n"
            f"Сумма: *{amount:.2f} $*\n"
            f"Ставка: *{percent:.0f}%*\n"
            f"Комиссия: *{fee:.2f} $*\n"
            f"Итого ориентировочно: *{total:.2f} $*\n"
            f"Способ оплаты: *{payment_method}*\n"
            f"Комментарий: {comment if comment else '—'}"
            f"{first_msg}\n\n"
            "С вами свяжется менеджер в ближайшее время.\n"
            "Если вы передумаете, можете отменить заявку через «❌ Отменить мою заявку».",
            parse_mode="Markdown",
            reply_markup=main_menu
        )

        for mid in MANAGER_IDS:
            await send_safe(mid, format_request_for_manager(new_req))

        return

    # Отмена заявки
    if text == "❌ Отменить мою заявку":
        last = get_last_request_by_user(user_id)

        if not last:
            await message.answer(
                "У вас ещё нет заявок, которые можно отменить.\n"
                "Нажмите «📝 Оставить заявку на аренду», чтобы оформить первую.",
                reply_markup=main_menu
            )
            return

        status = last.get("status", "")

        if status == STATUS_CANCELED_BY_CLIENT:
            await message.answer(
                f"Ваша последняя заявка (ID *{last['id']}*) уже была отменена ранее.\n\n"
                "Если вам снова нужна карта — вы можете оставить новую заявку.",
                parse_mode="Markdown",
                reply_markup=main_menu
            )
            return

        if not is_active_status(status):
            await message.answer(
                f"Последняя заявка (ID *{last['id']}*) уже имеет статус: *{pretty_status(status)}*.\n"
                "Отменить можно только новые или находящиеся в обработке заявки.",
                parse_mode="Markdown",
                reply_markup=main_menu
            )
            return

        last["status"] = STATUS_CANCELED_BY_CLIENT
        save_requests()

        await message.answer(
            f"Ваша заявка ID *{last['id']}* была отменена.\n"
            "Если нужно, вы можете оставить новую заявку.",
            parse_mode="Markdown",
            reply_markup=main_menu
        )

        for mid in MANAGER_IDS:
            await send_safe(mid, format_cancel_for_manager(last))

        return

    # Статус заявки
    if text == "📦 Статус моей заявки":
        last = get_last_request_by_user(user_id)

        if not last:
            await message.answer(
                "У вас пока нет заявок.\n"
                "Нажмите «📝 Оставить заявку на аренду», чтобы отправить первую.",
                reply_markup=main_menu
            )
            return

        first_badge = "🎁 " if last.get("is_first_request") else ""

        await message.answer(
            f"{first_badge}Статус вашей последней заявки:\n\n"
            f"ID заявки: *{last['id']}*\n"
            f"Сумма: *{last['amount']:.2f} $*\n"
            f"Статус: *{pretty_status(last.get('status', ''))}*",
            parse_mode="Markdown",
            reply_markup=main_menu
        )
        return

    # Fallback
    await message.answer(
        "Используйте кнопки внизу экрана или команду /help.\n\n"
        "💡 Совет: задайте вопрос ИИ-помощнику — он знает всё о сервисе и поможет с любыми темами!",
        reply_markup=main_menu
    )


# ---------- Запуск ----------

async def main():
    load_requests()
    load_users()
    dp.include_router(router)
    print("✅ Бот запущен. Нажми Ctrl+C для остановки.")

    for mid in MANAGER_IDS:
        await send_safe(
            mid,
            "✅ БОТ ЗАПУЩЕН\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🎁 Новые условия:\n"
            "• Первая заявка от 50$\n"
            "• Последующие от 100$\n\n"
            "Уведомления:\n"
            "• 👤 Новые пользователи\n"
            "• 📝 Новые заявки (с пометкой 🎁)\n"
            "• ❌ Отмена заявок\n"
            "• 🤖 Обращения к ИИ-помощнику\n\n"
            "Команды:\n"
            "/help, /stats, /last_requests,\n"
            "/users_stats, /broadcast,\n"
            "/ai_stats, /clear_ai_logs"
        )

    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
