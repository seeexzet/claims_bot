import telebot
from telebot import types
import os
from dotenv import load_dotenv
from supabase_client import SupabaseClient

class TelegramBot:
    def __init__(self):
        load_dotenv(override=True)
        self.TG_TOKEN = os.getenv("TG_TOKEN")
        self.bot = telebot.TeleBot(self.TG_TOKEN)
        # Глобальный экземпляр SupabaseClient
        self.supabase_client = SupabaseClient()
        self.supabase_client.sign_in()
        self.register_handlers()

    def register_handlers(self):
        # Обработчики команд
        self.bot.message_handler(commands=['start'])(self.start)
        self.bot.message_handler(commands=['help'])(self.send_help)
        self.bot.message_handler(content_types=['text'])(self.handle_text)
        self.bot.callback_query_handler(func=lambda call: True)(self.handle_query)

    def start(self, message):
        if not message.chat.username:
            self.bot.send_message(message.chat.id, "Перед работой с ботом установите имя аккаунта в настройках Telegram")
            return
        if message.chat.first_name:
            self.bot.send_message(message.chat.id, f"Привет, {message.chat.first_name}!")
        else:
            self.bot.send_message(message.chat.id, f"Привет, {message.chat.username}!")
        self.create_keyboard(message.chat.id)

    def send_help(self, message):
        return
        # self.bot.send_message(message.chat.id,
        #                       "Список доступных команд:\n"
        #                       "/start - Начать работу с ботом\n"
        #                       "/reg - Регистрация пользователя\n"
        #                       "/claim - Оставить заявку\n"
        #                       "/check - Проверить статус заявки\n"
        #                       "/help - Получить помощь")

    def create_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        button1 = types.InlineKeyboardButton('Регистрация пользователя', callback_data='button1')
        button2 = types.InlineKeyboardButton('Оставить заявку', callback_data='button2')
        button3 = types.InlineKeyboardButton('Проверить статус заявки', callback_data='button3')
        markup.add(button1)
        markup.add(button2)
        markup.add(button3)
        self.bot.send_message(chat_id, "Выберите одну из кнопок:", reply_markup=markup)

    def handle_query(self, call):
        user = call.from_user
        username = user.username
        if not username:
            self.bot.send_message(call.message.chat.id, "Установите имя пользователя в настройках Telegram")
            return

        if call.data == 'button1':
            self.bot.answer_callback_query(call.id, "Вы нажали Регистрация пользователя")
            if not self.supabase_client.check_user(username):
                self.bot.send_message(call.message.chat.id, "Вы выбрали регистрацию пользователя")
                response = self.supabase_client.add_user(username)
            else:
                self.bot.send_message(call.message.chat.id, "Вы уже зарегистрированы")

        elif call.data == 'button2':
            self.bot.answer_callback_query(call.id, "Вы нажали Оставить заявку")
            if self.supabase_client.check_user(username):
                self.bot.send_message(call.message.chat.id,
                                      "Вы выбрали оставить заявку. Оставьте здесь текст заявки:")
                # Регистрируем обработчик следующего сообщения пользователя
                self.bot.register_next_step_handler(call.message, self.process_claim_text)
            else:
                self.bot.send_message(call.message.chat.id, "Сначала нужно зарегистрироваться")

        elif call.data == 'button3':
            self.bot.answer_callback_query(call.id, "Вы нажали Проверить статус заявки")
            if self.supabase_client.check_user(username):
                self.bot.send_message(call.message.chat.id, "Вы выбрали проверить статус заявки")
                response_check_status = self.supabase_client.check_claims_status(username)
                if response_check_status:
                    for resp in response_check_status:
                        self.bot.send_message(call.message.chat.id,
                            f"Статус заявки №{resp['id']} сейчас {resp[self.supabase_client.field_claims_status]}.\n\nТекст заявки: {resp[self.supabase_client.field_claims_text]}")
                    self.create_keyboard(call.message.chat.id)
                else:
                    self.bot.send_message(call.message.chat.id, "У вас нет созданных заявок")
                    self.create_keyboard(call.message.chat.id)
            else:
                self.bot.send_message(call.message.chat.id, "Сначала нужно зарегистрироваться")

    def process_claim_text(self, message):
        username = message.from_user.username
        claim_text = message.text
        response_claim = self.supabase_client.create_claim(username, claim_text)
        print(response_claim)
        if response_claim:
            self.bot.send_message(message.chat.id,
                f"Ваша заявка принята. Номер заявки: {response_claim[0]['id']}. Статус заявки: {response_claim[0][self.supabase_client.field_claims_status]}")
        else:
            self.bot.send_message(message.chat.id, "Не удалось создать заявку")
        self.create_keyboard(message.chat.id)

    def handle_text(self, message):
        self.bot.send_message(message.chat.id, "Используйте кнопки для навигации по боту. " )
        self.create_keyboard(message.chat.id)

    def run(self):
        self.bot.polling()

if __name__ == '__main__':
    telegram_bot = TelegramBot()
    telegram_bot.run()
