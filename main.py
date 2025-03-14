import telebot
from telebot import types
import os
import re
from dotenv import load_dotenv
from supabase_client import SupabaseClient

# Регистрация пользователей в БД с нашей стороны, ФИО, имейл, телефон, компания.
# Пользователь из БД бота совпадает с пользователем джиры, под соответствующих акком джиры создается заявка в том или ином проекте
#
# Бот умеет:
# 1 - заводить заявки в джире, запрашивая:
#  ⁃ приоритет
#  ⁃ тему заявки
#  ⁃ детальное описание заявки
#  ⁃ принимает вложения (можно отложить этот пункт на потом)
# в ответ бот возвращает номер заявки и линку в джире на созданную заявку
#
# 2 - предоставлять статус заявки, при вводе номера заявки. Статус = последний видимый (не internal) апдейт в джире
#
# 3 - уведомлять (подписка на обновления) об изменении статус и новых апдейтах в тех заявках, на которые пользователь «подписался»

class TelegramBot:
    def __init__(self):
        load_dotenv(override=True)
        self.TG_TOKEN = os.getenv("TG_TOKEN")
        self.bot = telebot.TeleBot(self.TG_TOKEN)
        self.low_priority = os.environ.get("LOW_PRIORITY")
        self.middle_priority = os.environ.get("MIDDLE_PRIORITY")
        self.high_priority = os.environ.get("HIGH_PRIORITY")

        # Глобальный экземпляр SupabaseClient
        self.supabase_client = SupabaseClient()
        self.supabase_client.sign_in()
        self.register_handlers()
        self.reg_data = {}
        self.claim_data = {}

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

    def priority_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        button4 = types.InlineKeyboardButton('Низкий', callback_data='button4')
        button5 = types.InlineKeyboardButton('Средний', callback_data='button5')
        button6 = types.InlineKeyboardButton('Высокий', callback_data='button6')
        markup.add(button4)
        markup.add(button5)
        markup.add(button6)
        self.bot.send_message(chat_id, "Выберите приоритет заявки:", reply_markup=markup)

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
                # функции для регистрации
                self.bot.send_message(call.message.chat.id, "Введите ваши фамилию, имя, отчество:")
                self.bot.register_next_step_handler(call.message, self.process_registration_name)
            else:
                self.bot.send_message(call.message.chat.id, "Вы уже зарегистрированы")

        elif call.data == 'button2':
            self.bot.answer_callback_query(call.id, "Вы нажали Оставить заявку")
            if self.supabase_client.check_user(username):
                self.bot.send_message(call.message.chat.id,
                                      "Вы выбрали оставить заявку. Выберите приоритет заявки:")
                # Регистрируем обработчик следующего сообщения пользователя
                self.priority_keyboard(call.message.chat.id)
                # self.bot.register_next_step_handler(call.message, self.process_claim_priority)
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

        elif call.data == 'button4':
            # выбран низкий статус заявки
            self.bot.send_message(call.message.chat.id, "Выбран низкий уровень статуса заявок")
            self.claim_data[username] = {}
            self.claim_data[username]['priority'] = self.low_priority
            msg = self.bot.send_message(call.message.chat.id, "Введите тему заявки:")
            self.bot.register_next_step_handler(msg, self.process_claim_theme)


        elif call.data == 'button5':
            # выбран средний уровень обработки заявок
            self.bot.send_message(call.message.chat.id, "Выбран средний уровень статуса заявок")
            self.claim_data[username] = {}
            self.claim_data[username]['priority'] = self.middle_priority
            msg = self.bot.send_message(call.message.chat.id, "Введите тему заявки:")
            self.bot.register_next_step_handler(msg, self.process_claim_theme)

        elif call.data == 'button6':
            # выбран высокий уровень обработки заявок
            self.bot.send_message(call.message.chat.id, "Выбран высокий уровень статуса заявок")
            self.claim_data[username] = {}
            self.claim_data[username]['priority'] = self.high_priority
            msg = self.bot.send_message(call.message.chat.id, "Введите тему заявки:")
            self.bot.register_next_step_handler(msg, self.process_claim_theme)


    def process_registration_name(self, message):
        username = message.from_user.username
        self.reg_data[username] = {}
        if len(message.text.split(' ')) == 3:
            self.reg_data[username]['fio'] = message.text
            self.bot.send_message(message.chat.id, "Введите название компании:")
            self.bot.register_next_step_handler(message, self.process_registration_company, username)
        else:
            self.bot.send_message(message.chat.id, "Фамилия, имя и отчество введены неверно. Повторите запрос")
            self.bot.register_next_step_handler(message, self.process_registration_name)

    def process_registration_company(self, message, username):
        # Сохраняем компанию
        self.reg_data[username]['company'] = message.text
        # Запрос email
        self.bot.send_message(message.chat.id, "Введите ваш email:")
        self.bot.register_next_step_handler(message, self.process_registration_email, username)

    def process_registration_email(self, message, username):
        # Сохраняем email
        if self.is_email(message.text):
            self.reg_data[username]['email'] = message.text
            # Запрос номера телефона
            self.bot.send_message(message.chat.id, "Введите ваш телефон:")
            self.bot.register_next_step_handler(message, self.process_registration_phone, username)
        else:
            self.bot.send_message(message.chat.id, "Введён неправильный email, введите заново:")
            self.bot.register_next_step_handler(message, self.process_registration_email, username)

    def process_registration_phone(self, message, username):
        clear_phone = self.is_phone(message.text)
        if clear_phone: # проверка номера телефона
            self.reg_data[username]['phone'] = clear_phone
            # Формируем регистрационные данные
            registration_data = self.reg_data[username]
            response = self.supabase_client.add_user(username, registration_data)
            if response:
                self.bot.send_message(message.chat.id, "Регистрация прошла успешно!")
            else:
                self.bot.send_message(message.chat.id, "Ошибка регистрации, попробуйте еще раз.")
            # Отображаем клавиатуру (метод create_keyboard реализуется отдельно)
            self.create_keyboard(message.chat.id)
            del self.reg_data[username]
        else:
            self.bot.send_message(message.chat.id, "Телефон введён с ошибкой, введите ещё раз:")
            self.bot.register_next_step_handler(message, self.process_registration_phone, username)

    def is_phone(self, tel : str) -> str:
        tel = tel.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
        if tel.startswith('+79') and len(tel) == 12 and tel[1:].isdigit():
            return int('8'+tel[2:])
        elif tel.startswith('79') and len(tel) == 11  and tel.isdigit():
            return int('8'+tel[1:])
        elif tel.startswith('89') and len(tel) == 11  and tel.isdigit():
            return int(tel)
        elif tel.startswith('9') and len(tel) == 10 and tel.isdigit():
            return int('8'+tel)
        else:
            return None

    def is_email(self, text: str) -> bool:
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z.]+$"
        return re.match(pattern, text) is not None


    def process_claim_theme(self, message):
        username = message.from_user.username
        if len(message.text) > 0:
            self.claim_data[username]['theme'] = message.text
            print(self.claim_data)
            print(message)
            print(username)
            # Запрос детального описания заявки
            self.bot.send_message(message.chat.id, "Введите описание заявки:")
            self.bot.register_next_step_handler(message, self.process_claim_text, username)
        else:
            self.bot.send_message(message.chat.id, "Тема введена неправильно, введите заново:")
            self.bot.register_next_step_handler(message, self.process_claim_theme, username)

    def process_claim_text(self, message, username):
        if len(message.text) > 0:
            self.claim_data[username]['text'] = message.text
            claim_data = self.claim_data[username]
            response_claim = self.supabase_client.create_claim(username, claim_data)
            print(response_claim)
            if response_claim:
                self.bot.send_message(message.chat.id,
                    f"Ваша заявка принята. Номер заявки: {response_claim[0]['id']}. Статус заявки: {response_claim[0][self.supabase_client.field_claims_status]}")
            else:
                self.bot.send_message(message.chat.id, "Не удалось создать заявку")
        else:
            self.bot.send_message(message.chat.id, "Описание заявки введено неверно, повторите:")
            self.bot.register_next_step_handler(message, self.process_claim_text, username)
        self.create_keyboard(message.chat.id)

    def handle_text(self, message):
        self.bot.send_message(message.chat.id, "Используйте кнопки для навигации по боту. " )
        self.create_keyboard(message.chat.id)

    def run(self):
        self.bot.polling()

if __name__ == '__main__':
    telegram_bot = TelegramBot()
    telegram_bot.run()
