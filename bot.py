import telebot
import sqlite3
from telebot.types import LabeledPrice, SuccessfulPayment, PreCheckoutQuery, ChatJoinRequest

# --- НАСТРОЙКИ ---
API_TOKEN = 'BOT_TOKEN'
CHANNEL_ID = -100*******
CHANNEL_LINK = "LINK_TG"

PRICE_IN_STAR = 10 #цена в звездх


# --- ИНИЦИАЛИЗАЦИЯ ---
bot = telebot.TeleBot(API_TOKEN)
DB_NAME = 'bot_payments.db'

# -------------------------------------------------------------
# ФУНКЦИИ SQLITE
# -------------------------------------------------------------

def init_db():
    """Создает базу данных и таблицу для хранения запросов на вступление."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Храним информацию о запросе на вступление, ожидающем оплаты
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS join_requests (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            charge_id TEXT 
        )
    """)
    conn.commit()
    conn.close()


def save_join_request(user_id, chat_id):
    """Сохраняет ожидающий оплаты запрос на вступление."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO join_requests (user_id, chat_id, status) VALUES (?, ?, ?)",
        (user_id, chat_id, 'PENDING_PAYMENT')
    )
    conn.commit()
    conn.close()


def update_request_status(user_id, status, charge_id=None):
    """Обновляет статус запроса после оплаты."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if charge_id:
        cursor.execute(
            "UPDATE join_requests SET status = ?, charge_id = ? WHERE user_id = ?",
            (status, charge_id, user_id)
        )
    else:
        cursor.execute(
            "UPDATE join_requests SET status = ? WHERE user_id = ?",
            (status, user_id)
        )
    conn.commit()
    conn.close()


# -------------------------------------------------------------
# ОБРАБОТКА ЗАПРОСОВ НА ВСТУПЛЕНИЕ
# -------------------------------------------------------------

@bot.chat_join_request_handler(func=lambda request: request.chat.id == CHANNEL_ID)
def handle_join_request(request: ChatJoinRequest):
    """
    Перехватывает запрос на вступление в канал, сохраняет его и отправляет инвойс.
    """
    user_id = request.from_user.id
    chat_id = request.chat.id
    user_full_name = request.from_user.full_name

    print(f"Принят запрос на вступление от {user_id} ({user_full_name}) в чат {chat_id}.")

    # 1. Сохраняем запрос в БД со статусом 'PENDING_PAYMENT'
    save_join_request(user_id, chat_id)

    # 2. Создаем уникальный инвойс
    prices = [
        LabeledPrice(label='Доступ в закрытый канал', amount=PRICE_IN_STAR)
    ]

    # Пейлоад связываем с ID пользователя, чтобы знать, кого принять после оплаты
    invoice_payload = f"JOIN_REQUEST_{user_id}"

    try:
        # 3. Отправляем счет в личные сообщения пользователя
        bot.send_invoice(
            chat_id=user_id,
            title='Оплата доступа в канал',
            description=f'Оплатите {PRICE_IN_STAR} Stars, чтобы получить доступ в канал.',
            invoice_payload=invoice_payload,
            provider_token='',
            currency="XTR",
            prices=prices,
            is_flexible=False
        )


    except telebot.apihelper.ApiTelegramException as e:
        if "bot was blocked by the user" in str(e) or "user is a bot" in str(e):
            bot.approve_chat_join_request(chat_id, user_id)  # Опционально: можно сразу принять
        else:
            print(f"❌ Критическая ошибка при отправке счета {user_id}: {e}")
            bot.send_message(user_id, "❌ Произошла ошибка при формировании счета. Попробуйте позже.")


# -------------------------------------------------------------
# ОБРАБОТКА ПЛАТЕЖЕЙ И ПРИНЯТИЕ В КАНАЛ
# -------------------------------------------------------------

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    """Подтверждает готовность принять платеж."""
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message: telebot.types.Message):
    """
    Обрабатывает успешную оплату и автоматически принимает пользователя в канал.
    """
    payment_info: SuccessfulPayment = message.successful_payment
    user_id = message.from_user.id

    # 1. Проверяем пейлоад, чтобы убедиться, что это оплата за вступление
    if not payment_info.invoice_payload.startswith("JOIN_REQUEST_"):
        print(f"Предупреждение: Неизвестный пейлоад: {payment_info.invoice_payload}")
        return

    # 2. Получаем ID пользователя и ID канала (из БД)
    # Нам нужен только user_id, channel_id берем из константы
    channel_id = CHANNEL_ID
    charge_id = payment_info.telegram_payment_charge_id

    # 3. Обновляем статус в БД
    update_request_status(user_id, 'PAID', charge_id)

    # 4. Автоматически принимаем пользователя в канал
    try:
        bot.approve_chat_join_request(chat_id=channel_id, user_id=user_id)

        # 5. Уведомляем пользователя
        bot.send_message(
            user_id,
            f"🎉 **Оплата {payment_info.total_amount} ⭐️ принята!**\n\n"
            f"Вы автоматически приняты в канал! [Добро пожаловать]({CHANNEL_LINK}).\n",
            parse_mode='Markdown'
        )
        print(f"✅ Пользователь {user_id} успешно принят в канал {channel_id}.")

    except telebot.apihelper.ApiTelegramException as e:
        # Эта ошибка возникает, если пользователь уже вступил или отменил запрос
        bot.send_message(user_id,
                         "❌ Ошибка: Не удалось принять вас в канал. Возможно, вы отменили запрос или уже состоите в нем.")
        print(f"❌ Ошибка принятия пользователя {user_id}: {e}")


# -------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------

if __name__ == '__main__':
        init_db()
        print("Бот запущен. Ожидание команд...")
        bot.polling(none_stop=True)
