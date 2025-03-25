import jira
import telebot
from telebot import types
import os
import re
import time
import requests
from dotenv import load_dotenv
from supabase_client import SupabaseClient
from jira_client import JiraClient

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
    def __init__(self, supabase_client):
        load_dotenv(override=True)
        self.TG_TOKEN = os.getenv("TG_TOKEN")
        self.bot = telebot.TeleBot(self.TG_TOKEN)
        self.low_priority = os.environ.get("LOW_PRIORITY")
        self.middle_priority = os.environ.get("MIDDLE_PRIORITY")
        self.high_priority = os.environ.get("HIGH_PRIORITY")
        self.field_claims_number_in_jira = os.environ.get("FIELD_CLAIMS_NUMBER_IN_JIRA")
        self.todo_status = os.environ.get("GIRA_TODO_STATUS")
        self.inprogress_status = os.environ.get("GIRA_TODO_INPROGRESS")
        self.done_status = os.environ.get("GIRA_TODO_DONE")
        self.typetask_field_1 = os.environ.get("GIRA_TYPETASK_FIELD_1")
        self.typetask_field_2 = os.environ.get("GIRA_TYPETASK_FIELD_2")
        self.typetask_field_3 = os.environ.get("GIRA_TYPETASK_FIELD_3")

        # экземпляр SupabaseClient
        self.supabase_client = supabase_client
        # self.supabase_client = SupabaseClient()
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
        # Удаляем все зарегистрированные обработчики, чтобы прервать текущую регистрацию или другой процесс.
        self.bot.clear_step_handler_by_chat_id(message.chat.id)
        if not message.chat.username:
            self.bot.send_message(message.chat.id, "Перед работой с ботом установите имя аккаунта в настройках Telegram")
            return
        if message.chat.first_name:
            self.bot.send_message(message.chat.id, f"Привет, {message.chat.first_name}!")
        else:
            self.bot.send_message(message.chat.id, f"Привет, {message.chat.username}!")
        self.create_keyboard(message.chat.id)

    def send_help(self, message):
        self.bot.send_message(message.chat.id,
                              "Список доступных команд:\n"
                              "/start - Начать работу с ботом\n"
                              # "/reg - Регистрация пользователя\n"
                              # "/claim - Оставить заявку\n"
                              # "/check - Проверить статус заявки\n"
                              "/help - Получить помощь")

    def create_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        # button1 = types.InlineKeyboardButton('Регистрация пользователя', callback_data='button1')
        button2 = types.InlineKeyboardButton('Оставить заявку', callback_data='button2')
        button3 = types.InlineKeyboardButton('Все открытые заявки', callback_data='button3')
        button4 = types.InlineKeyboardButton('Посмотреть статус заявки', callback_data='button4')
        # markup.add(button1)
        markup.add(button2)
        markup.add(button3)
        markup.add(button4)
        self.bot.send_message(chat_id, "Выберите одну из кнопок:", reply_markup=markup)

    def priority_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        button5 = types.InlineKeyboardButton('Низкий', callback_data='button5')
        button6 = types.InlineKeyboardButton('Средний', callback_data='button6')
        button7 = types.InlineKeyboardButton('Высокий', callback_data='button7')
        markup.add(button5)
        markup.add(button6)
        markup.add(button7)
        self.bot.send_message(chat_id, "Выберите приоритет заявки:", reply_markup=markup)

    def type_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        button8 = types.InlineKeyboardButton(self.typetask_field_1, callback_data='button8')
        button9 = types.InlineKeyboardButton(self.typetask_field_2, callback_data='button9')
        button10 = types.InlineKeyboardButton(self.typetask_field_3, callback_data='button10')
        markup.add(button8)
        markup.add(button9)
        markup.add(button10)
        self.bot.send_message(chat_id, "Выберите тип заявки:", reply_markup=markup)

    def handle_query(self, call):
        user = call.from_user
        username = user.id
        if not username:
            self.bot.send_message(call.message.chat.id, "Установите имя пользователя в настройках Telegram")
            return

        if call.data == 'button1':
            self.bot.answer_callback_query(call.id, "Вы нажали Регистрация пользователя")
            self.registration(call, username)

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
                self.bot.send_message(call.message.chat.id, "Вы выбрали посмотреть все открытые заявки")
                jira_token = supabase_client.get_token_from_supabase(username)
                if jira_token:
                    jira_client = JiraClient(jira_token)
                    del jira_token
                    jira_claims_numbers = jira_client.get_claims_numbers() # раньше было через Supabase
                    if jira_claims_numbers:
                        buttons = []
                        for number in jira_claims_numbers:
                            button = types.InlineKeyboardButton(f"№{number}",
                                                                callback_data=f'claim_{number}')
                            buttons.append(button)
                        markup = types.InlineKeyboardMarkup(row_width=4)
                        markup.add(*buttons)
                        self.bot.send_message(call.message.chat.id,
                                            "Выберите заявку для проверки её статуса:",
                                            reply_markup=markup)
                    else:
                        self.bot.send_message(call.message.chat.id, "У вас нет созданных заявок")
                        self.create_keyboard(call.message.chat.id)
                else:
                    self.bot.send_message(call.message.chat.id, "Сначала нужно зарегистрироваться")
            else:
                self.bot.send_message(call.message.chat.id, "Сначала нужно зарегистрироваться")

        elif call.data == 'button4':
            # посмотреть статус конкретной заявки
            self.get_claim_input_number(call, username)

        elif call.data == 'button5':
            # выбран низкий статус заявки
            self.handle_priority_selection(call, username, self.low_priority, "низкий")

        elif call.data == 'button6':
            # выбран средний уровень обработки заявок
            self.handle_priority_selection(call, username, self.middle_priority, "средний")

        elif call.data == 'button7':
            # выбран высокий уровень обработки заявок
            self.handle_priority_selection(call, username, self.high_priority, "высокий")

        elif call.data == 'button8':
            self.handle_priority_selection(call, username, self.process_claim_type, self.typetask_field_1)

        elif call.data == 'button9':
            self.handle_priority_selection(call, username, self.process_claim_type, self.typetask_field_2)

        elif call.data == 'button10':
            self.handle_priority_selection(call, username, self.process_claim_type, self.typetask_field_3)

        elif call.data.startswith('claim_'):
            number = call.data.split('_')[1]
            self.get_claim_status(call.message, username, number)

        elif call.data.startswith('comment_'):
            number = call.data.split('_')[1]
            self.comment_message(call, username, number)

    def handle_priority_selection(self, call, username, priority_level, priority_name):
        self.bot.send_message(call.message.chat.id, f"Выбран {priority_name} уровень статуса заявки")
        print('priority_level=', priority_level)
        self.claim_data[username] = {'priority': priority_level}
        self.bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id,
                                           reply_markup=None)
        msg = self.bot.send_message(call.message.chat.id, "Введите тему заявки:")
        self.bot.register_next_step_handler(msg, self.process_claim_theme)

    def registration(self, call, username):
        if not self.supabase_client.check_user(username):
            self.bot.send_message(call.message.chat.id, "Вы выбрали регистрацию пользователя")
            # функции для регистрации
            self.bot.send_message(call.message.chat.id, "Введите ваши фамилию, имя, отчество:")
            self.bot.register_next_step_handler(call.message, self.process_registration_name)
        else:
            self.bot.send_message(call.message.chat.id, "Вы уже зарегистрированы")

    def process_registration_name(self, message):
        if not self.if_start(message) and not self.if_help(message):
            username = message.from_user.id
            self.reg_data[username] = {}
            if len(message.text.split(' ')) == 3:
                self.reg_data[username]['fio'] = message.text
                self.bot.send_message(message.chat.id, "Введите название компании:")
                self.bot.register_next_step_handler(message, self.process_registration_company, username)
            else:
                self.bot.send_message(message.chat.id, "Фамилия, имя и отчество введены неверно. Повторите запрос")
                self.bot.register_next_step_handler(message, self.process_registration_name)

    def process_registration_company(self, message, username):
        if not self.if_start(message) and not self.if_help(message):
            # Сохраняем компанию
            self.reg_data[username]['company'] = message.text
            # Запрос email
            self.bot.send_message(message.chat.id, "Введите ваш email:")
            self.bot.register_next_step_handler(message, self.process_registration_email, username)

    def process_registration_email(self, message, username):
        if not self.if_start(message) and not self.if_help(message):
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
        if not self.if_start(message) and not self.if_help(message):
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

    def if_start(self, message):
        if message.text.startswith('/start'):
            self.bot.clear_step_handler_by_chat_id(message.chat.id)
            self.start(message)
            return True
        else:
            return False

    def if_help(self, message):
        if message.text.startswith('/help'):
            self.bot.clear_step_handler_by_chat_id(message.chat.id)
            self.send_help(message)
            return True
        else:
            return False

    def process_claim_theme(self, message):
        if not self.if_start(message) and not self.if_help(message):
            username = message.from_user.id
            if len(message.text) > 0:
                self.claim_data[username]['theme'] = message.text
                # print(self.claim_data)
                # print(message)
                # print(username)
                self.bot.send_message(message.chat.id, "Выберите тип заявки:")
                self.bot.register_next_step_handler(message, self.process_claim_type, username)
            else:
                self.bot.send_message(message.chat.id, "Тема введена неправильно, введите заново:")
                self.bot.register_next_step_handler(message, self.process_claim_theme, username)

    def process_claim_type(self, message, username):
        if not self.if_start(message) and not self.if_help(message):
            username = message.from_user.id
            if len(message.text) > 0:
                self.claim_data[username]['type'] = message.text
                # print(self.claim_data)
                # print(message)
                # print(username)
                self.bot.send_message(message.chat.id, "Введите описание заявки:")
                self.bot.register_next_step_handler(message, self.process_claim_text, username) #  ЗДЕСЬ НАДО ПЕРЕХОД НА ОСТАВЛЕНИЕ ПРИЛОЖЕНИЯ
            else:
                self.bot.send_message(message.chat.id, "Тип введен неправильно, введите заново:")
                self.bot.register_next_step_handler(message, self.process_claim_type, username)

    def process_claim_text(self, message, username):
        if not self.if_start(message) and not self.if_help(message):
            if len(message.text) > 1:
                self.claim_data[username]['text'] = message.text
                claim_data = self.claim_data[username]
                # print('claim_data=', claim_data)
                #получение токена для Jira из Supabase
                jira_token = supabase_client.get_token_from_supabase(username)
                if jira_token:
                    jira_client = JiraClient(jira_token)
                    del jira_token
                    # добавление заявки в Jira
                    response_claim_jira = jira_client.create_claim(username, claim_data)
                    jira_client.logout()
                    if response_claim_jira:
                        jira_claim_number = int(response_claim_jira.key.split('-')[1])
                        self.bot.send_message(message.chat.id, f"Заявка успешно создана, номер в Jira: <b>{jira_claim_number}</b>, Ссылка: \n{response_claim_jira.permalink()}", parse_mode='HTML')
                        #response_claim_supabase = self.supabase_client.create_claim(username, claim_data, jira_claim_number)
                        #if response_claim_supabase:
                        #     self.bot.send_message(message.chat.id,
                        #         f"<b>Ваша заявка принята</b>. \n\nНомер заявки в Supabase: <b>{response_claim_supabase[0]['id']}</b> \n"
                        #         f"Номер заявки в Jira: <b>{response_claim_jira.key.split('-')[1]}</b>, ссылка: \n{response_claim_jira.permalink()}", parse_mode='HTML')
                        # else:
                        #     self.bot.send_message(message.chat.id, "Не удалось добавить заявку в Supabase\n"
                        #         f"Номер заявки в Jira: {response_claim_jira.key}, ссылка: \n{response_claim_jira.permalink()}")
                        del self.claim_data
                    else:
                        self.bot.send_message(message.chat.id, "Не удалось создать заявку")
                else:
                    self.bot.send_message(message.chat.id, f"Пользователь {username} не зарегистрирован в Supabase")
            else:
                self.bot.send_message(message.chat.id, "Описание заявки введено неверно, повторите:")
                self.bot.register_next_step_handler(message, self.process_claim_text, username)
            self.create_keyboard(message.chat.id)

    def get_claim_input_number(self, call, username):
        self.bot.send_message(call.message.chat.id, "Введите номер заявки:")
        self.bot.register_next_step_handler(call.message, self.get_claim_status, username)

    def get_claim_status(self, message, username, number=None):
        # Если number не передан, то берем его из message.text с проверкой
        if number is None:
            if self.if_start(message) or self.if_help(message):
                return
            if not message.text.isdigit():
                self.send_invalid_claim_message(message, username)
                return
            number = message.text

        # Запрашиваем информацию по заявке
        jira_token = supabase_client.get_token_from_supabase(username)
        if jira_token:
            jira_client = JiraClient(jira_token)
            del jira_token
            claim_info = jira_client.check_claim_status(number, username)
            # print('claim_info==', claim_info)
            jira_client.logout()
            if claim_info:
                markup = types.InlineKeyboardMarkup()
                comment_button = types.InlineKeyboardButton(
                    text="Оставить комментарий", callback_data=f"comment_{number}"
                )
                markup.add(comment_button)
                if claim_info['last_comment']:
                    self.bot.send_message(
                        message.chat.id,
                        f"Статус заявки №{number}: <b>{claim_info['status']}</b> \n\nТема заявки:\n"
                        f"{claim_info['summary']}\n\nОписание заявки:\n{claim_info['description']}"
                        f"\n\nПоследнее обновление: <b>{claim_info['last_update']}</b> \n\nПоследний комментарий "
                        f"оставлен <b>{claim_info['last_comment']['author']}</b> в "
                        f"<b>{claim_info['last_comment']['created']}</b>:\n\n"
                        f"{claim_info['last_comment']['text']}",
                        parse_mode='HTML',
                        reply_markup=markup
                    )
                    self.create_keyboard(message.chat.id)
                else:
                    self.bot.send_message(
                        message.chat.id,
                        f"Статус заявки №{number}: <b>{claim_info['status']}</b> \n\nТема заявки:\n"
                        f"{claim_info['summary']}\n\nОписание заявки:\n{claim_info['description']}"
                        f"\n\nПоследнее обновление: <b>{claim_info['last_update']}</b> \n\nКомментариев нет.",
                        parse_mode='HTML',
                        reply_markup=markup
                    )
                    self.create_keyboard(message.chat.id)
            else:
                self.send_invalid_claim_message(message, username)
        else:
            self.bot.send_message(message.chat.id, "Пользователь не зарегистрирован в Supabase")
            self.create_keyboard(message.chat.id)

    def send_invalid_claim_message(self, message, username):
        self.bot.send_message(message.chat.id, "Номер введён неправильно, повторите:")
        self.bot.register_next_step_handler(message, self.get_claim_status, username)

    def comment_message(self, call, username, number):
        if self.if_start(call.message) or self.if_help(call.message):
            return
        self.bot.send_message(call.message.chat.id, "Введите комментарий:")
        self.bot.register_next_step_handler(call.message, self.add_comment, username, number)

    def add_comment(self, message, username, number):
        jira_token = supabase_client.get_token_from_supabase(username)
        if jira_token:
            jira_client = JiraClient(jira_token)
            del jira_token
            response = jira_client.add_comment_to_claim(number, username, message.text)
            jira_client.logout()
            # print('Ответ при добавлении комментария', response)
            if response:
                # del response
                self.bot.send_message(message.chat.id, f"Комментарий к заявке <b>{number}</b> добавлен", parse_mode='HTML')
                self.create_keyboard(message.chat.id)
            else:
                self.bot.send_message(message.chat.id, "Не удалось добавить комментарий")
                self.create_keyboard(message.chat.id)
        else:
            self.bot.send_message(message.chat.id, "Пользователь не зарегистрирован в Supabase")
            self.create_keyboard(message.chat.id)

    def handle_text(self, message):
        self.bot.send_message(message.chat.id, "Используйте кнопки для навигации по боту.")
        self.create_keyboard(message.chat.id)

    def run(self):
        self.bot.polling() # non_stop=True, timeout=30, long_polling_timeout=30)


if __name__ == '__main__':
    supabase_client = SupabaseClient()
    # jira_client = JiraClient()
    telegram_bot = TelegramBot(supabase_client)
    # while True:
    #     try:
    #         telegram_bot.run()
    #     except requests.exceptions.ReadTimeout:
    #         print("Произошёл тайм-аут. Повтор через 5 секунд...")
    #         time.sleep(5)
    #     except Exception as e:
    #         print(f"Неожиданная ошибка: {e}")
    #         time.sleep(5)
    telegram_bot.run()