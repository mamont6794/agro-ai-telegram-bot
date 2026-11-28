import csv
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import threading
import telebot
from google import genai
from google.genai import types

# Зчитуємо ключі зі змінних оточення сервера (або підставляємо локально)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "ВСТАВ_СЮДИ_ТОКЕН_ВІД_BOTFATHER")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "ВСТАВ_СЮДИ_КЛЮЧ_ВІД_GOOGLE_AI_STUDIO")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 5281798463))

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
def send_welcome(message):
    user_chats.pop(message.chat.id, None)
    bot.reply_to(
        message,
        "Вітаю у «АгроПостач Плюс»! 🌾\n"
        "Я ваш АІ-консультант. Допоможу підібрати насіння, добрива чи ЗЗР, "
        "розрахувати норму та вартість на вашу площу, а також оформити замовлення.\n\n"
        "Яка культура чи площа вас цікавить?",
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

            # 1. Зберігаємо заявку у файл CSV
            save_lead_to_csv(message.chat.id, lead_info)

            # 2. Відповідаємо клієнту (без службових даних)
            bot.reply_to(message, clean_reply)

            # 3. Надсилаємо миттєве сповіщення власнику бізнесу
            username = f"@{message.from_user.username}" if message.from_user.username else "не вказано"
            try:
                bot.send_message(
                    ADMIN_ID,
                    f"🔥 *Нова заявка з Telegram-бота!*\n\n"
                    f"📋 *Деталі:* `{lead_info}`\n"
                    f"👤 *Telegram клієнта:* {username} (ID: `{message.chat.id}`)\n"
                    f"🕒 *Час:* {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                    parse_mode="Markdown",
                )
            except Exception as admin_err:
                print(f"[Помилка відправки адміну]: {admin_err}")
        else:
            bot.reply_to(message, reply_text)

    except Exception:
        bot.reply_to(
            message,
            "Зараз спостерігається високе навантаження на лінію. Напишіть, будь ласка, ще раз через 10 секунд!",
        )


# Мінівебсервер для підтримки роботи на безкоштовному хостингу Render
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
