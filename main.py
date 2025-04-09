import jira
import telebot
import schedule
import threading
from telebot import types
import os
import re
import time
import requests
from io import BytesIO
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
    def __init__(self):
        load_dotenv(override=True)
        self.TG_TOKEN = os.getenv("TG_TOKEN")
        self.bot = telebot.TeleBot(self.TG_TOKEN)
        self.low_priority = os.environ.get("LOW_PRIORITY")
        self.middle_priority = os.environ.get("MIDDLE_PRIORITY")
        self.high_priority = os.environ.get("HIGH_PRIORITY")
        self.field_claims_number_in_jira = os.environ.get("FIELD_CLAIMS_NUMBER_IN_JIRA")

        self.field_user_id = os.environ.get("FIELD_SUBSCRIBE_USER_ID")
        self.field_chat_id = os.environ.get("FIELD_SUBSCRIBE_CHAT_ID")
        self.field_claim_number = os.environ.get("FIELD_SUBSCRIBE_CLAIM_NUMBER")
        self.field_claim_status = os.environ.get("FIELD_SUBSCRIBE_CLAIM_STATUS")

        self.todo_status = os.environ.get("GIRA_TODO_STATUS")
        self.inprogress_status = os.environ.get("GIRA_TODO_INPROGRESS")
        self.done_status = os.environ.get("GIRA_TODO_DONE")
        self.closed_status = os.environ.get("GIRA_CLOSED")
        self.typetask_field_1 = os.environ.get("GIRA_TYPETASK_FIELD_1")
        self.typetask_field_2 = os.environ.get("GIRA_TYPETASK_FIELD_2")
        # self.typetask_field_3 = os.environ.get("GIRA_TYPETASK_FIELD_3")
        self.gira_project_key = os.environ.get("GIRA_PROJECT_KEY")

        self.buttons_per_page = 50
        self.list_of_claims = []

        self.register_handlers()
        self.start_polling_scheduler()
        self.reg_data = {}
        self.attachment = None
        self.photo = None

    def register_handlers(self):
        # Обработчики команд
        self.bot.message_handler(commands=['start'])(self.start)
        self.bot.message_handler(commands=['help'])(self.send_help)
        self.bot.message_handler(content_types=['text'])(self.handle_text)
        self.bot.message_handler(content_types=['document'])(self.handle_document)
        self.bot.message_handler(content_types=['photo'])(self.handle_photo)
        self.bot.callback_query_handler(func=lambda call: True)(self.handle_query)

    def start(self, message):
        # Удаляем все зарегистрированные обработчики, чтобы прервать текущую регистрацию или другой процесс.
        self.bot.clear_step_handler_by_chat_id(message.chat.id)
        if not message.chat.username:
            pass
        elif message.chat.first_name:
            self.bot.send_message(message.chat.id, f"Привет, {message.chat.first_name}!")
        else:
            self.bot.send_message(message.chat.id, f"Привет, {message.chat.username}!")
        self.username = message.from_user.id
        self.create_keyboard(message.chat.id, self.username)

    def send_help(self, message):
        self.bot.send_message(message.chat.id,
                              "Список доступных команд:\n"
                              "/start - Начать работу с ботом\n"
                              # "/reg - Регистрация пользователя\n"
                              # "/claim - Оставить заявку\n"
                              # "/check - Проверить статус заявки\n"
                              "/help - Получить помощь")

    def create_keyboard(self, chat_id, user_id):
        markup = types.InlineKeyboardMarkup()
        # подключение к Supabase
        supabase_client = self.initialize_supabase_client()
        if supabase_client.check_user_token(user_id):
            button_create_claim = types.InlineKeyboardButton('Оставить заявку', callback_data='button_create_claim')
            button_all_claims = types.InlineKeyboardButton('Все открытые заявки', callback_data='button_all_claims')
            button_all_subs = types.InlineKeyboardButton('Все подписки на обновления', callback_data=f"button_all_subs_{user_id}")
            button_check_claim = types.InlineKeyboardButton('Посмотреть статус заявки', callback_data='button_check_claim')
            button_reset_reg = types.InlineKeyboardButton('Сбросить регистрацию', callback_data='button_reset_reg')
            markup.add(button_create_claim)
            markup.add(button_all_claims)
            markup.add(button_all_subs)
            markup.add(button_check_claim)
            markup.add(button_reset_reg)
        else:
            button_reg = types.InlineKeyboardButton('Регистрация пользователя', callback_data='button_reg')
            markup.add(button_reg)
        supabase_client.logout()
        self.supabase_client = None
        self.bot.send_message(chat_id, "Выберите одну из кнопок:", reply_markup=markup)

    def priority_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        button_middle = types.InlineKeyboardButton('Средний', callback_data='button_middle')
        button_high = types.InlineKeyboardButton('Высокий', callback_data='button_high')
        button_critical = types.InlineKeyboardButton('Критический', callback_data='button_critical')
        markup.add(button_middle)
        markup.add(button_high)
        markup.add(button_critical)
        self.bot.send_message(chat_id, "Выберите приоритет заявки:", reply_markup=markup)

    def type_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        button_type1 = types.InlineKeyboardButton(self.typetask_field_1, callback_data='button_type1')
        button_type2 = types.InlineKeyboardButton(self.typetask_field_2, callback_data='button_type2')
        # button_type3 = types.InlineKeyboardButton(self.typetask_field_3, callback_data='button_type3')
        markup.add(button_type1)
        markup.add(button_type2)
        # markup.add(button_type3)
        self.bot.send_message(chat_id, "Выберите тип заявки:", reply_markup=markup)

    def attachenent_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        btn_yes = types.InlineKeyboardButton(text="Да", callback_data=f"upload_yes")
        btn_no = types.InlineKeyboardButton(text="Нет", callback_data=f"upload_no")
        markup.add(btn_yes, btn_no)
        self.bot.send_message(chat_id, "Хотите загрузить документ или фотографию для заявки?", reply_markup=markup)

    def handle_query(self, call):
        user = call.from_user
        self.username = user.id

        if call.data == 'button_reset_reg':
            self.bot.answer_callback_query(call.id, "Вы нажали Сбросить регистрацию")
            self.reset_keyboard(call.message.chat.id)

        if call.data == 'button_reg':
            self.bot.answer_callback_query(call.id, "Вы нажали Регистрация пользователя")
            self.registration(call)

        elif call.data == 'button_create_claim':
            self.bot.answer_callback_query(call.id, "Вы нажали Оставить заявку")
            self.claim_data = {}
            supabase_client = self.initialize_supabase_client()
            if supabase_client.check_user(self.username):
                self.bot.send_message(call.message.chat.id,
                                      "Вы выбрали оставить заявку. Выберите приоритет заявки:")
                self.priority_keyboard(call.message.chat.id)
                # self.bot.register_next_step_handler(call.message, self.process_claim_priority)
            else:
                self.bot.send_message(call.message.chat.id, "Нет регистрации или токен недействителен")
            supabase_client.logout()
            self.supabase_client = None

        elif call.data == 'button_all_claims':
            self.list_of_claims = []
            self.bot.answer_callback_query(call.id, "Вы нажали Проверить статус заявки")
            supabase_client = self.initialize_supabase_client()
            if supabase_client.check_user(self.username):
                self.bot.send_message(call.message.chat.id, "Вы выбрали посмотреть все открытые заявки")
                jira_token = supabase_client.get_token_from_supabase(self.username)
                if jira_token:
                    jira_client = JiraClient(jira_token)
                    del jira_token
                    self.list_of_claims = jira_client.get_claims_numbers_and_themes()
                    if self.list_of_claims:
                        self.keyboard_list_of_claims(call, 0)
                    else:
                        self.bot.send_message(call.message.chat.id, "У вас нет созданных заявок")
                        self.create_keyboard(call.message.chat.id, self.username)
                else:
                    self.bot.send_message(call.message.chat.id, "Нет регистрации или токен недействителен")
            else:
                self.bot.send_message(call.message.chat.id, "Нет регистрации или токен недействителен")
            supabase_client.logout()
            self.supabase_client = None

        elif call.data == 'button_check_claim':
            # посмотреть статус конкретной заявки
            self.get_claim_input_number(call)

        elif call.data == 'button_middle':
            # выбран низкий статус заявки
            self.handle_priority_selection(call, self.low_priority, "средний")

        elif call.data == 'button_high':
            # выбран средний уровень обработки заявок
            self.handle_priority_selection(call, self.middle_priority, "высокий")

        elif call.data == 'button_critical':
            # выбран высокий уровень обработки заявок
            self.handle_priority_selection(call, self.high_priority, "критический")

        elif call.data == 'button_type1':
            self.process_claim_type(call, self.typetask_field_1)

        elif call.data == 'button_type2':
            self.process_claim_type(call, self.typetask_field_2)

        # elif call.data == 'button_type3':
        #     self.process_claim_type(call, self.typetask_field_3)

        elif call.data == 'main_menu_button':
            self.create_keyboard(call.message.chat.id, self.username)

        elif call.data.startswith('claim_'):
            number = call.data.split('_')[1]
            self.get_claim_status(call.message, number)

        elif call.data.startswith('comment_'):
            number = call.data.split('_')[1]
            self.comment_message(call, number)

        elif call.data.startswith('subscribe_'):
            number = call.data.split('_')[1]
            self.add_subscribe(call, number)

        elif call.data.startswith('unsubscribe_'):
            number = call.data.split('_')[1]
            self.unsubscribe_claim(call, number)

        elif call.data.startswith('button_all_subs_'):
            self.check_subscribe(call)

        elif call.data.startswith("list_of_claims_"):
            number = call.data.split('_')[-1]
            self.keyboard_list_of_claims(call, number)

        elif call.data.startswith("upload_yes"):
            # Пользователь выбрал загрузку документа. Извлекаем issue_key из callback_data.
            # issue_key = call.data.split("_")[-1]
            self.bot.send_message(call.message.chat.id, f"Пожалуйста, прикрепите файл или фотографию для заявки.")
            # Здесь можно обновить состояние, если используете FSM или регистрировать следующий шаг.

        elif call.data.startswith("upload_no"):
            self.upload_claim(call.message)

        elif call.data.startswith("reset_yes"):
            self.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            self.reset_registration(call.message)

        elif call.data.startswith("reset_no"):
            self.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            self.create_keyboard(call.message.chat.id, self.username)

    def reset_keyboard(self, chat_id):
        markup = types.InlineKeyboardMarkup()
        btn_yes = types.InlineKeyboardButton(text="Да", callback_data=f"reset_yes")
        btn_no = types.InlineKeyboardButton(text="Нет", callback_data=f"reset_no")
        markup.add(btn_yes, btn_no)
        self.bot.send_message(chat_id, "Вы уверены, что хотите сбросить регистрацию?", reply_markup=markup)

    def reset_registration(self, message):
        if not self.if_start(message) and not self.if_help(message):
            supabase_client = self.initialize_supabase_client()
            if supabase_client.check_user_token(self.username):
                response = supabase_client.delete_user_token(self.username)
                supabase_client.logout()
                self.supabase_client = None
                if response:
                    self.bot.send_message(message.chat.id, f"Токен пользователя был успешно удалён, пройдите регистрацию заново для дальнейшей работы")
                    self.create_keyboard(message.chat.id, self.username)
                else:
                    self.bot.send_message(message.chat.id, f"Не удалось удалить токен пользователя")
            else:
                self.bot.send_message(message.chat.id, f"Пользователь не зарегистрирован")
                self.create_keyboard(message.chat.id, self.username)

    def handle_priority_selection(self, call, priority_level, priority_name):
            self.bot.send_message(call.message.chat.id, f"Выбран уровень статуса заявки: <b>{priority_name}</b>", parse_mode='HTML')
            print('priority_level=', priority_level)
            self.claim_data = {'priority': priority_level}
            # self.bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id,
            #                                    reply_markup=None)
            self.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
            self.type_keyboard(call.message.chat.id)

    def process_claim_type(self, call, type: str):
        self.claim_data['type'] = type
        self.bot.send_message(call.message.chat.id, f"Выбран тип заявки: <b>{type}</b>", parse_mode='HTML')
        # self.bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id,
        #                                    reply_markup=None)
        self.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        msg = self.bot.send_message(call.message.chat.id, "Введите тему заявки:")
        self.bot.register_next_step_handler(msg, self.process_claim_theme)

    def handle_document(self, message):
        if message.document:
            file_id = message.document.file_id
            file_info = self.bot.get_file(file_id)
            downloaded_file = self.bot.download_file(file_info.file_path)
            filename = message.document.file_name

            # Оборачиваем скачанные байты в BytesIO и задаем имя файла
            file_data = BytesIO(downloaded_file)
            file_data.name = filename  # задаем имя файла, чтобы Jira могла его распознать
            file_data.seek(0)

            self.attachment=file_data
            self.filename=filename
            self.bot.send_message(message.chat.id, f"Файл {filename} успешно прикреплён к заявке.")
            self.bot.send_message(message.chat.id, f"Формирую заявку...")
            self.upload_claim(message)
        else:
            self.bot.send_message(message.chat.id, "Документ не найден.")
            self.attachenent_keyboard(message.chat.id)

    def handle_photo(self, message):
        if message.photo:
            file_id = message.photo[-1].file_id  # берём фото с наивысшим разрешением
            file_info = self.bot.get_file(file_id)
            downloaded_file = self.bot.download_file(file_info.file_path)

            from io import BytesIO
            file_data = BytesIO(downloaded_file)
            file_data.name = "photo.jpg"  # Задаем имя файла вручную
            file_data.seek(0)

            self.photo=file_data
            self.filename=file_data.name
            self.bot.send_message(message.chat.id, f"Фотография успешно прикреплена к заявке.")
            self.upload_claim(message)
        else:
            self.bot.send_message(message.chat.id, "Фотография не найдена.")
            self.attachenent_keyboard(message.chat.id)

    def registration(self, call):
        supabase_client = self.initialize_supabase_client()
        if not supabase_client.check_user_token(self.username):
            self.bot.send_message(call.message.chat.id, "Вы выбрали регистрацию пользователя")
            # функции для регистрации
            user_email = None
            try:
                user_email = supabase_client.get_user_email(self.username)
            except:
                print('Ошибка')
            if not self.is_email(user_email):
                self.bot.send_message(
                    call.message.chat.id,
                    (
                        "Введите email"
                    )
                )
                self.bot.register_next_step_handler(call.message, self.process_registration_email)
            else:
                self.bot.send_message(
                    call.message.chat.id,
                    (
                        "Нужно завести токен. \n"
                        "1. Пройдите по ссылке: https://support24.team/secure/ViewProfile.jspa\n"
                        "Нажмите справа вверху Create token (Создать токен)\n"
                        "2. Введите название токена в поле Token name и нажмите внизу Create (Создать)\n"
                        "3. Скопируйте в открывшейся странице Token (длинную последовательность символов) и вставьте сюда"
                    )
                )
                self.bot.register_next_step_handler(call.message, self.process_registration_token)
        else:
            self.bot.send_message(call.message.chat.id, "Вы уже зарегистрированы")
        supabase_client.logout()
        self.supabase_client = None

    def process_registration_token(self, message, email=None):
        supabase_client = self.initialize_supabase_client()
        if not self.if_start(message) and not self.if_help(message):
            if len(message.text) > 18:
                if email:
                    response = supabase_client.add_user(self.username, "".join(message.text.split()), email)
                else:
                    response = supabase_client.add_user_without_email(self.username, "".join(message.text.split()))
                if response:
                    self.bot.send_message(message.chat.id, "Регистрация прошла успешно!")
                else:
                    self.bot.send_message(message.chat.id, "Ошибка регистрации, попробуйте еще раз.")
                # Отображаем клавиатуру (метод create_keyboard реализуется отдельно)
                self.create_keyboard(message.chat.id, self.username)
                del message.text
        else:
            self.bot.send_message(message.chat.id, "Токен введён неверно. Повторите ввод")
            self.bot.register_next_step_handler(message, self.process_registration_token)
        supabase_client.logout()
        self.supabase_client = None

    # def process_registration_name(self, message):
    #     if not self.if_start(message) and not self.if_help(message):
    #         self.reg_data[username] = {}
    #         if len(message.text.split(' ')) == 3:
    #             self.reg_data[username]['fio'] = message.text
    #             self.bot.send_message(message.chat.id, "Введите название компании:")
    #             self.bot.register_next_step_handler(message, self.process_registration_company, username)
    #         else:
    #             self.bot.send_message(message.chat.id, "Фамилия, имя и отчество введены неверно. Повторите запрос")
    #             self.bot.register_next_step_handler(message, self.process_registration_name)
    #
    # def process_registration_company(self, message):
    #     if not self.if_start(message) and not self.if_help(message):
    #         # Сохраняем компанию
    #         self.reg_data[username]['company'] = message.text
    #         # Запрос email
    #         self.bot.send_message(message.chat.id, "Введите ваш email:")
    #         self.bot.register_next_step_handler(message, self.process_registration_email)

    def process_registration_email(self, message):
        if not self.if_start(message) and not self.if_help(message):
            # Сохраняем email
            if self.is_email(message.text):
                email = message.text
                # Запрос номера телефона
                self.bot.send_message(
                    message.chat.id,
                    (
                        "Нужно завести токен. \n"
                        "1. Пройдите по ссылке: https://support24.team/secure/ViewProfile.jspa\n"
                        "Нажмите справа вверху Create token (Создать токен)\n"
                        "2. Введите название токена в поле Token name и нажмите внизу Create (Создать)\n"
                        "3. Скопируйте в открывшейся странице Token (длинную последовательность символов) и вставьте сюда"
                    )
                )
                self.bot.register_next_step_handler(message, self.process_registration_token, email)
            else:
                self.bot.send_message(message.chat.id, "Введён неправильный email, введите заново:")
                self.bot.register_next_step_handler(message, self.process_registration_email)

    # def process_registration_phone(self, message):
    #     if not self.if_start(message) and not self.if_help(message):
    #         clear_phone = self.is_phone(message.text)
    #         if clear_phone: # проверка номера телефона
    #             self.reg_data[username]['phone'] = clear_phone
    #             # Формируем регистрационные данные
    #             registration_data = self.reg_data[username]
    #             response = self.supabase_client.add_user(registration_data)
    #             if response:
    #                 self.bot.send_message(message.chat.id, "Регистрация прошла успешно!")
    #             else:
    #                 self.bot.send_message(message.chat.id, "Ошибка регистрации, попробуйте еще раз.")
    #             # Отображаем клавиатуру (метод create_keyboard реализуется отдельно)
    #             self.create_keyboard(message.chat.id, self.username)
    #             del self.reg_data[username]
    #         else:
    #             self.bot.send_message(message.chat.id, "Телефон введён с ошибкой, введите ещё раз:")
    #             self.bot.register_next_step_handler(message, self.process_registration_phone)
    #
    # def is_phone(self, tel : str) -> str:
    #     tel = tel.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    #     if tel.startswith('+79') and len(tel) == 12 and tel[1:].isdigit():
    #         return int('8'+tel[2:])
    #     elif tel.startswith('79') and len(tel) == 11  and tel.isdigit():
    #         return int('8'+tel[1:])
    #     elif tel.startswith('89') and len(tel) == 11  and tel.isdigit():
    #         return int(tel)
    #     elif tel.startswith('9') and len(tel) == 10 and tel.isdigit():
    #         return int('8'+tel)
    #     else:
    #        return None

    def is_email(self, text: str) -> bool:
        if not text:
            return False
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z.]+$"
        return re.match(pattern, text) is not None

    def process_claim_theme(self, message):
        if not self.if_start(message) and not self.if_help(message):
            if len(message.text) > 0:
                self.claim_data['theme'] = message.text
                if self.claim_data['type'] == self.typetask_field_1:
                    self.bot.send_message(message.chat.id, "Введите описание заявки:")
                    self.bot.register_next_step_handler(message, self.process_claim_text)
                elif self.claim_data['type'] == self.typetask_field_2:
                    self.attachenent_keyboard(message.chat.id)
            else:
                self.bot.send_message(message.chat.id, "Тема введена неправильно, введите заново:")
                self.bot.register_next_step_handler(message, self.process_claim_theme)

    def process_claim_text(self, message):
        if not self.if_start(message) and not self.if_help(message):
            if len(message.text) > 1:
                self.claim_data['text'] = message.text
                claim_data = self.claim_data
                self.attachenent_keyboard(message.chat.id)
            else:
                self.bot.send_message(message.chat.id, "Описание заявки введено неверно, повторите:")
                self.bot.register_next_step_handler(message, self.process_claim_text)

    def upload_claim(self, message):
        #получение токена для Jira из Supabase
        supabase_client = self.initialize_supabase_client()
        jira_token = supabase_client.get_token_from_supabase(self.username)
        self.supabase_client = None
        if jira_token:
            jira_client = JiraClient(jira_token)
            # добавление заявки в Jira
            response_claim_jira = jira_client.create_claim(self.username, self.claim_data)
            jira_claim_number = response_claim_jira['issueKey'].split('-')[-1]
            email = supabase_client.get_user_email(self.username)
            claim_link = jira_client.get_claim_link_by_number(jira_claim_number)
            del jira_token
            if response_claim_jira:
                markup = types.InlineKeyboardMarkup()
                subscribe_button = types.InlineKeyboardButton(
                    text="Подписаться на обновления по заявке", callback_data=f"subscribe_{jira_claim_number}")
                markup.add(subscribe_button)
                del self.claim_data
                if self.photo:
                    # загрузить фото или документ
                    result_add_attachment = jira_client.add_photo_to_claim(jira_claim_number, self.photo, self.filename)
                    if result_add_attachment:
                        self.bot.send_message(message.chat.id,
                                              f"Заявка успешно создана, вложение успешно добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка: \n{claim_link}",
                                              parse_mode='HTML', reply_markup=markup)
                    else:
                        self.bot.send_message(message.chat.id,
                                              f"Заявка успешно создана, но вложение не добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка: \n{claim_link}",
                                              parse_mode='HTML', reply_markup=markup)
                elif self.attachment:
                    result_add_attachment = jira_client.add_attachment_to_claim(jira_claim_number, self.attachment, self.filename)
                    if result_add_attachment:
                        self.bot.send_message(message.chat.id,
                                              f"Заявка успешно создана, вложение успешно добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка: \n{claim_link}",
                                              parse_mode='HTML', reply_markup=markup)
                    else:
                        self.bot.send_message(message.chat.id,
                                              f"Заявка успешно создана, но вложение не добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка: \n{claim_link}",
                                              parse_mode='HTML', reply_markup=markup)
                else:
                    self.bot.send_message(message.chat.id,
                                          f"Заявка успешно создана, номер в Jira: <b>{jira_claim_number}</b>, Ссылка: \n{claim_link}",
                                          parse_mode='HTML', reply_markup=markup)
                # if claim_link:
                #     self.bot.send_message(message.chat.id, f"Ссылка на заявку: \n{claim_link}")
                # else:
                #     self.bot.send_message(message.chat.id, f"Ссылку невозможно прислать, поскольку email не совпадает с тем, что указан в Jira.")
                jira_client.logout()
            else:
                self.bot.send_message(message.chat.id, "Не удалось создать заявку")
                del self.claim_data
        else:
            self.bot.send_message(message.chat.id, f"Пользователь {self.username} не зарегистрирован в Supabase")
        supabase_client.logout()

    def get_claim_input_number(self, call):
        self.bot.send_message(call.message.chat.id, "Введите номер заявки:")
        self.bot.register_next_step_handler(call.message, self.get_claim_status)

    def get_claim_status(self, message, number=None):
        # Если number не передан, то берем его из message.text с проверкой
        if number is None:
            if self.if_start(message) or self.if_help(message):
                return
            if message.text.isdigit():
                number = self.gira_project_key + '-' + message.text
            elif re.compile(r'\b[A-Z]+-[0-9]+\b').search(message.text):
                number = message.text
            elif re.compile(r'\b[A-Za-z]+-[0-9]+\b').search(message.text):
                number = message.text.upper()
            else:
                self.send_invalid_claim_message(message)
                return
        supabase_client = self.initialize_supabase_client()
        subscribe_status = supabase_client.is_subscription(self.username, number)
        jira_token = supabase_client.get_token_from_supabase(self.username)
        if jira_token:
            jira_client = JiraClient(jira_token)
            del jira_token
            claim_info = jira_client.check_claim_status(number, self.username)
            # print('claim_info==', claim_info)
            jira_client.logout()
            if claim_info:
                markup = types.InlineKeyboardMarkup()
                comment_button = types.InlineKeyboardButton(
                    text="Оставить комментарий", callback_data=f"comment_{number}"
                )
                markup = types.InlineKeyboardMarkup()
                if subscribe_status:
                    subscribe_button = types.InlineKeyboardButton(
                        text="Отписаться от обновлений по заявке", callback_data=f"unsubscribe_{number}")
                else:
                    subscribe_button = types.InlineKeyboardButton(
                        text="Подписаться на обновления по заявке", callback_data=f"subscribe_{number}")
                main_menu_button = types.InlineKeyboardButton(
                        text="Главное меню", callback_data='main_menu_button')
                markup.add(comment_button)
                markup.add(subscribe_button)
                markup.add(main_menu_button)
                if claim_info['last_comment']:
                    self.bot.send_message(
                        message.chat.id,
                        f"Статус заявки {number}: <b>{claim_info['status']}</b> \n\nТема заявки:\n"
                        f"{claim_info['summary']}\n\nОписание заявки:\n{claim_info['description']}"
                        f"\n\nПоследнее обновление: <b>{claim_info['last_update']}</b> \n\nПоследний комментарий "
                        f"оставлен <b>{claim_info['last_comment']['author']}</b> в "
                        f"<b>{claim_info['last_comment']['created']}</b>:\n\n"
                        f"{claim_info['last_comment']['text']}",
                        parse_mode='HTML',
                        reply_markup=markup
                    )
                else:
                    self.bot.send_message(
                        message.chat.id,
                        f"Статус заявки №{number}: <b>{claim_info['status']}</b> \n\nТема заявки:\n"
                        f"{claim_info['summary']}\n\nОписание заявки:\n{claim_info['description']}"
                        f"\n\nПоследнее обновление: <b>{claim_info['last_update']}</b> \n\nКомментариев нет.",
                        parse_mode='HTML',
                        reply_markup=markup
                    )
            else:
                self.send_invalid_claim_message(message)
        else:
            self.bot.send_message(message.chat.id, "Пользователь не зарегистрирован в Supabase")
            self.create_keyboard(message.chat.id, self.username)
        supabase_client.logout()
        self.supabase_client = None

    def send_invalid_claim_message(self, message):
        self.bot.send_message(message.chat.id, "Номер введён неправильно, повторите:")
        self.bot.register_next_step_handler(message, self.get_claim_status)

    def comment_message(self, call, number):
        if self.if_start(call.message) or self.if_help(call.message):
            return
        self.bot.send_message(call.message.chat.id, "Введите комментарий:")
        self.bot.register_next_step_handler(call.message, self.add_comment, number)

    def add_comment(self, message, number):
        supabase_client = self.initialize_supabase_client()
        jira_token = supabase_client.get_token_from_supabase(self.username)
        supabase_client.logout()
        self.supabase_client = None
        if jira_token:
            jira_client = JiraClient(jira_token)
            del jira_token
            response = jira_client.add_comment_to_claim(number, self.username, message.text)
            jira_client.logout()
            # print('Ответ при добавлении комментария', response)
            if response:
                # del response
                self.bot.send_message(message.chat.id, f"Комментарий к заявке <b>{number}</b> добавлен", parse_mode='HTML')
                self.create_keyboard(message.chat.id, self.username)
            else:
                self.bot.send_message(message.chat.id, "Не удалось добавить комментарий")
                self.create_keyboard(message.chat.id, self.username)
        else:
            self.bot.send_message(message.chat.id, "Пользователь не зарегистрирован в Supabase")
            self.create_keyboard(message.chat.id, self.username)

    def add_subscribe(self, call, number):
        # проверка, а нет ли уже такой записи? Если нет - добавить запись в базу.
        supabase_client = self.initialize_supabase_client()
        if not supabase_client.is_subscription(self.username, number):
            print("Добавляем в базу subscription запись")
            # здесь надо идти в Jira и получать статус
            jira_token = supabase_client.get_token_from_supabase(self.username)
            if jira_token:
                jira_client = JiraClient(jira_token)
                del jira_token
                response_from_jira = jira_client.check_claim_status(number, self.username)
                jira_client.logout()
                if response_from_jira:
                    response = supabase_client.save_subscription(self.username, number, response_from_jira['status'])
                    if response:
                        self.bot.send_message(call.message.chat.id, f"Вы подписались на обновление статуса заявки {number}")
                    else:
                        self.bot.send_message(call.message.chat.id, f"Не удалось подписаться на заявку {number}")
                else:
                    self.bot.send_message(call.message.chat.id, f"Не удалось проверить статус заявки {number}")
        else:
            self.bot.send_message(call.message.chat.id, f"Вы уже подписаны на обновления статуса заявки {number}")
        supabase_client.logout()

    def unsubscribe_claim(self, call, number):
        supabase_client = self.initialize_supabase_client()
        if supabase_client.is_subscription(self.username, number):
            response = supabase_client.delete_subscription(call.message.chat.id, number.split('-')[1])
            if response:
                self.bot.send_message(call.message.chat.id, f"Подписка на заявку {number} удалена")
            else:
                self.bot.send_message(call.message.chat.id, f"Подписку на заявку {number} не удалось удалить")
        else:
            self.bot.send_message(call.message.chat.id, f"Подписки на заявку {number} нет")
        supabase_client.logout()

    def check_subscribe(self, call):
        supabase_client = self.initialize_supabase_client()
        self.bot.answer_callback_query(call.id, "Вы нажали Посмотреть все подписки на обновления")
        if supabase_client.check_user(self.username):
            self.bot.send_message(call.message.chat.id, "Вы выбрали посмотреть все подписки на обновления")
            subscriptions = supabase_client.get_subscriptions(call.message.chat.id, fields=self.field_claim_number)
            subscription_numbers = sorted(s[self.field_claim_number] for s in subscriptions)
            if subscription_numbers:
                buttons = []
                jira_token = supabase_client.get_token_from_supabase(self.username)
                if jira_token:
                    current_page = 1
                    jira_client = JiraClient(jira_token)
                    del jira_token
                    for sub in subscription_numbers:
                        # собираем словарь номера - темы заявок, все какие есть у пользователя
                        number = self.gira_project_key + '-' + str(sub)
                        theme = jira_client.get_theme_by_number(number)
                        claim = {'number': number, 'theme': theme}
                        self.list_of_claims.append(claim)
                    jira_client.logout()
                    self.keyboard_list_of_claims(call, 0)
                else:
                    self.bot.send_message(call.message.chat.id, "Проблема с подключением к Jira, сбросьте регистрацию и обновите токен.")
            else:
                self.bot.send_message(call.message.chat.id, "Вы пока не подписаны ни на одно обновление.\nВыберите пункт «Все открытые заявки», затем — конкретную заявку и подпишитесь на её обновление.")
                self.create_keyboard(call.message.chat.id, self.username)
        else:
            self.bot.send_message(call.message.chat.id, "Нет регистрации или токен недействителен")
        supabase_client.logout()
        self.supabase_client = None

    def keyboard_list_of_claims(self, call, number):
        try:
            self.bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=None
            )
        except Exception as e:
            print("Не удалось удалить предыдущую клавиатуру:", e)

        # number - номер начала куска списка
        number = int(number)
        print('number =', number)
        print('self.buttons_per_page = ', self.buttons_per_page)
        buttons = []
        print('Мы внутри keyboard_list_of_claims')
        # вывод клавиатуры - куска списка заявок
        i = number
        k = 0
        while (i < len(self.list_of_claims)) and (k < self.buttons_per_page):
            button = types.InlineKeyboardButton(f"{self.list_of_claims[i]['number']} — {self.list_of_claims[i]['theme']}",  callback_data=f"claim_{i}")
            buttons.append(button)
            i += 1
            k += 1
        markup = types.InlineKeyboardMarkup(row_width=1)
        # вывод кнопки назад, если не начало
        if (number - self.buttons_per_page >= 0):
            buttons.append(types.InlineKeyboardButton("<< Предыдущие заявки",
                                                      callback_data=f"list_of_claims_{str(number - self.buttons_per_page)}"))
        # вывод кнопки вперёд, если не конец
        if (number + self.buttons_per_page < len(self.list_of_claims)):
            buttons.append(types.InlineKeyboardButton("Следующие заявки >>",
                                                      callback_data=f"list_of_claims_{str(number + self.buttons_per_page)}"))
        markup.add(*buttons)
        try:
            self.bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        except Exception as e:
            print("Не удалось удалить предыдущее сообщение:", e)
        self.bot.send_message(call.message.chat.id, "Выберите заявку для проверки её статуса:", reply_markup=markup)

    def poll_issue_status(self):
        supabase_client = self.initialize_supabase_client()
        user_list = supabase_client.get_user_list()
        for user in user_list:
            subscriptions = supabase_client.get_subscriptions(user)
            jira_token = supabase_client.get_token_from_supabase(user)
            if jira_token:
                jira_client = JiraClient(jira_token)
                del jira_token
                if subscriptions:
                    for sub in subscriptions:
                        claim_number = self.gira_project_key + '-' + str(sub[self.field_claim_number])
                        # username = supabase_client.get_username_by_user_id(sub[self.field_user_id])
                        last_status = sub.get(self.field_claim_status, "")
                        print('Проверка статуса ', user, ' ', claim_number)
                        try:
                            current_status = jira_client.check_claim_status(claim_number, user)['status']
                            print('current_status=', current_status, ' last=', last_status)
                            claim_link = jira_client.get_claim_status_by_number(claim_number)
                            if current_status != last_status:
                                # Обновляем статус в Supabase
                                print('Статусы отличаются')
                                supabase_client.update_subscription_status(user, claim_number, current_status)
                                # Уведомляем подписчика
                                print("self.field_chat_id = ", self.field_chat_id)
                                self.bot.send_message(user, f"Статус заявки {claim_number} изменился с {last_status} на: {current_status}.\n{claim_link}")
                                if claim_link == self.done_status or claim_link == self.closed_status:
                                    jira_client.delete_subscription(self.username, sub[self.field_claim_number])
                                    self.bot.send_message(user, f"Подписка на обновление статуса заявки удалена")
                        except Exception as e:
                            print(f"Ошибка опроса заявки {claim_number}: {e}")
                jira_client.logout()
            # else:
            #     self.bot.send_message(user, f"У вас нет подписок")
        supabase_client.logout()

    def start_polling_scheduler(self):
        schedule.every(6).minutes.do(self.poll_issue_status)

        def run_schedule():
            while True:
                schedule.run_pending()
                time.sleep(1)

        t = threading.Thread(target=run_schedule)
        t.daemon = True
        t.start()

    def run(self):
        self.bot.polling(none_stop=True)

    def initialize_supabase_client(self):
        self.supabase_client = SupabaseClient()
        self.supabase_client.sign_in()
        return self.supabase_client

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

    def handle_text(self, message):
        self.bot.send_message(message.chat.id, "Используйте кнопки для навигации по боту.")
        self.create_keyboard(message.chat.id, self.username)

    def run(self):
        self.bot.polling() # non_stop=True, timeout=30, long_polling_timeout=30)


if __name__ == '__main__':
    # jira_client = JiraClient()
    telegram_bot = TelegramBot()
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