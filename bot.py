import csv
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import threading
import telebot
from telebot import types as tg_types
from google import genai
from google.genai import types

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ВСТАВ_СЮДИ_ТОКЕН_ВІД_BOTFATHER")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "ВСТАВ_СЮДИ_КЛЮЧ_ВІД_GOOGLE_AI_STUDIO")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KNOWLEDGE_PATH = os.path.join(BASE_DIR, "knowledge.txt")
LEADS_PATH = os.path.join(BASE_DIR, "leads.csv")

with open(KNOWLEDGE_PATH, "r", encoding="utf-8") as f:
    KNOWLEDGE_BASE = f.read()

SYSTEM_PROMPT = f"""
Ти — досвідчений менеджер-консультант аграрної компанії «АгроПостач Плюс».
Твоє завдання — консультувати фермерів та агропідприємців, допомагати з розрахунком обсягів на гектар і збирати заявки.

ПРАВИЛА РОБОТИ:
1. Відповідай виключно на основі БАЗИ ЗНАНЬ нижче. Не вигадуй товари, ціни чи знижки, яких немає в базі. Якщо чогось немає — скажи, що уточниш у головного агронома.
2. Спілкуйся впевнено, по-діловому, з повагою до праці аграріїв, українською мовою. Не пиши занадто довгих простирадл тексту (оптимально 3–6 речень).
3. Завжди допомагай порахувати потрібну кількість посівних одиниць, тонн чи каністр під площу клієнта (у гектарах) та орієнтовну вартість.
4. М'яко веди діалог до цільової дії: запропонуй зафіксувати ціну або передати розрахунок менеджеру для виставлення рахунку. Для цього попроси ім'я та номер телефону клієнта.
5. ВАЖЛИВО: Щойно клієнт напише своє ім'я та номер телефону, подякуй йому в тексті, а в самому кінці повідомлення з нового рядка обов'язково додай службовий тег суворо у такому форматі:
[LEAD: Ім'я | Телефон | Суть замовлення або площа в га]

БАЗА ЗНАНЬ КОМПАНІЇ:
{KNOWLEDGE_BASE}
"""

bot = telebot.TeleBot(TELEGRAM_TOKEN)
ai_client = genai.Client(api_key=GEMINI_API_KEY)

AVAILABLE_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]
user_chats = {}


def get_main_keyboard():
    """Створює зручне мобільне меню кнопок під полем вводу."""
    markup = tg_types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_price = tg_types.KeyboardButton("🌾 Прайс і норми")
    btn_calc = tg_types.KeyboardButton("🧮 Розрахунок на площу")
    btn_delivery = tg_types.KeyboardButton("🚚 Доставка і знижки")
    btn_reset = tg_types.KeyboardButton("🔄 Новий діалог")
    markup.add(btn_price, btn_calc, btn_delivery, btn_reset)
    return markup


def get_user_chat(chat_id, model_name):
    if chat_id not in user_chats:
        user_chats[chat_id] = ai_client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.3,
            ),
        )
    return user_chats[chat_id]


def send_with_fallback(chat_id, text):
    for model_name in AVAILABLE_MODELS:
        try:
            chat = get_user_chat(chat_id, model_name)
            return chat.send_message(text).text
        except Exception as e:
            print(f"[Пропускаємо {model_name}]: {e}")
            user_chats.pop(chat_id, None)
            continue
    raise Exception("Усі моделі зараз перевантажені")


def save_lead_to_csv(user_id, lead_data):
    file_exists = os.path.isfile(LEADS_PATH)
    with open(LEADS_PATH, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        if not file_exists:
            writer.writerow(
                ["Дата і час", "Telegram ID", "Деталі заявки (Ім'я | Телефон | Запит)"]
            )
        writer.writerow(
            [datetime.now().strftime("%Y-%m-%d %H:%M"), user_id, lead_data]
        )


@bot.message_handler(commands=["start", "reset"])
@bot.message_handler(func=lambda m: m.text == "🔄 Новий діалог")
def send_welcome(message):
    user_chats.pop(message.chat.id, None)
    bot.reply_to(
        message,
        "Вітаю у «АгроПостач Плюс»! 🌾\n"
        "Я ваш АІ-консультант. Оберіть потрібний розділ у меню нижче або напишіть, "
        "яка культура та площа (в га) вас цікавить:",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(commands=["price"])
@bot.message_handler(func=lambda m: m.text == "🌾 Прайс і норми")
def handle_price(message):
    message.text = "Надай короткий структурований список усіх товарів із прайсу з цінами та нормами витрат на гектар."
    handle_message(message)


@bot.message_handler(commands=["delivery"])
@bot.message_handler(func=lambda m: m.text == "🚚 Доставка і знижки")
def handle_delivery(message):
    message.text = "Розкажи коротко про мінімальне замовлення, умови безкоштовної доставки, способи оплати та оптову знижку."
    handle_message(message)


@bot.message_handler(func=lambda m: m.text == "🧮 Розрахунок на площу")
def handle_calc_prompt(message):
    bot.reply_to(
        message,
        "Напишіть, яку культуру чи препарат плануєте вносити та скільки у вас гектарів (наприклад: *соняшник 120 га* або *селітра на 50 га*) — і я миттєво порахую обсяг та суму зі знижкою.",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    bot.send_chat_action(message.chat.id, "typing")
    try:
        reply_text = send_with_fallback(message.chat.id, message.text)

        if "[LEAD:" in reply_text:
            parts = reply_text.split("[LEAD:")
            clean_reply = parts[0].strip()
            lead_info = parts[1].replace("]", "").strip()

            save_lead_to_csv(message.chat.id, lead_info)
            bot.reply_to(message, clean_reply, reply_markup=get_main_keyboard())

            bot.send_message(
                message.chat.id,
                f"🔔 *[Сповіщення для власника бізнесу / CRM]*\n"
                f"Нова заявка зафіксована:\n`{lead_info}`",
                parse_mode="Markdown",
            )
        else:
            bot.reply_to(message, reply_text, reply_markup=get_main_keyboard())

    except Exception:
        bot.reply_to(
            message,
            "Зараз спостерігається високе навантаження на лінію. Напишіть, будь ласка, ще раз через 10 секунд!",
            reply_markup=get_main_keyboard(),
        )


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Agro AI Bot is running!")


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    print("Агро-агент запущений на сервері...")
    bot.infinity_polling()
