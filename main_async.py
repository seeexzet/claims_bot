import os
import re
import asyncio
import schedule
import time
import threading
from io import BytesIO
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from supabase_client import SupabaseClient
from jira_client import JiraClient

# Загружаем переменные окружения
load_dotenv(override=True)

# Определяем FSM для регистрации и создания заявки

class RegistrationState(StatesGroup):
    waiting_for_email = State()
    waiting_for_token = State()


class ClaimState(StatesGroup):
    waiting_for_topic = State()
    waiting_for_description = State()


class TelegramBot:
    def __init__(self):
        # Инициализируем объекты бота, диспетчера и FSM‑хранилища
        self.token = os.getenv("TG_TOKEN")
        self.storage = MemoryStorage()
        self.bot = Bot(token=self.token, default=DefaultBotProperties(parse_mode="HTML"))
        self.dp = Dispatcher(storage=self.storage)  # создаём диспетчер без передачи бота

        # Временное хранилище данных (для некоторых значений, например, заявок)
        self.ctx_data = {}
        self.low_priority = os.environ.get("LOW_PRIORITY")
        self.middle_priority = os.environ.get("MIDDLE_PRIORITY")
        self.high_priority = os.environ.get("HIGH_PRIORITY")
        self.typetask_field_1 = os.environ.get("GIRA_TYPETASK_FIELD_1")
        self.typetask_field_2 = os.environ.get("GIRA_TYPETASK_FIELD_2")
        self.gira_project_key = os.environ.get("GIRA_PROJECT_KEY")
        self.buttons_per_page = 50

        self.register_handlers()
        self.start_polling_scheduler()

    def register_handlers(self):
        # Регистрируем обработчики команд
        self.dp.message.register(self.start_handler, Command("start"))
        self.dp.message.register(self.help_handler, Command("help"))
        self.dp.message.register(self.text_handler)

        # Регистрируем обработчики для файлов и фотографий с использованием фильтра F
        self.dp.message.register(self.document_handler, F.content_type == types.ContentType.DOCUMENT)
        self.dp.message.register(self.photo_handler, F.content_type == types.ContentType.PHOTO)

        # Обработчик callback‑запросов для inline‑кнопок
        self.dp.callback_query.register(self.callback_query_handler)

        # Регистрируем FSM‑обработчики для регистрации
        self.dp.message.register(self.process_registration_email, RegistrationState.waiting_for_email)
        self.dp.message.register(self.process_registration_token, RegistrationState.waiting_for_token)

        # Регистрируем FSM‑обработчики для создания заявки
        self.dp.message.register(self.process_claim_topic, ClaimState.waiting_for_topic)
        self.dp.message.register(self.process_claim_description, ClaimState.waiting_for_description)

    async def start_handler(self, message: types.Message):
        # Обработчик команды /start
        await message.answer(
            f"Привет, {message.from_user.first_name or message.from_user.username}!"
        )
        self.ctx_data['username'] = message.from_user.id
        await self.create_keyboard(message.chat.id, message.from_user.id)

    async def help_handler(self, message: types.Message):
        # Обработчик команды /help
        await message.answer("Список доступных команд:\n"
                             "/start - Начать работу с ботом\n"
                             "/help - Получить помощь")

    async def create_keyboard(self, chat_id: int, user_id: int):
        # Формирование основного меню с inline‑клавиатурой через InlineKeyboardBuilder
        builder = InlineKeyboardBuilder()
        supabase_client = self.initialize_supabase_client()
        if supabase_client.check_user_token(user_id):
            builder.row(
                types.InlineKeyboardButton(text='Оставить заявку', callback_data='button_create_claim')
            )
            builder.row(
                types.InlineKeyboardButton(text='Все открытые заявки', callback_data='button_all_claims')
            )
            builder.row(
                types.InlineKeyboardButton(text='Все подписки на обновления', callback_data=f'button_all_subs_{user_id}')
            )
            builder.row(
                types.InlineKeyboardButton(text='Посмотреть статус заявки', callback_data='button_check_claim')
            )
            builder.row(
                types.InlineKeyboardButton(text='Сбросить регистрацию', callback_data='button_reset_reg')
            )
        else:
            builder.row(
                types.InlineKeyboardButton(text='Регистрация пользователя', callback_data='button_reg')
            )
        supabase_client.logout()
        markup = builder.as_markup()
        await self.bot.send_message(chat_id, "Выберите одну из кнопок:", reply_markup=markup)

    def initialize_supabase_client(self):
        client = SupabaseClient()
        client.sign_in()
        return client

    async def priority_keyboard(self, chat_id: int):
        # Inline‑клавиатура для выбора приоритета заявки
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text='Средний', callback_data='button_middle'),
            types.InlineKeyboardButton(text='Высокий', callback_data='button_high'),
            types.InlineKeyboardButton(text='Критический', callback_data='button_critical')
        )
        markup = builder.as_markup()
        await self.bot.send_message(chat_id, "Выберите приоритет заявки:", reply_markup=markup)

    async def type_keyboard(self, chat_id: int):
        # Inline‑клавиатура для выбора типа заявки
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text=self.typetask_field_1, callback_data='button_type1'),
            types.InlineKeyboardButton(text=self.typetask_field_2, callback_data='button_type2')
        )
        markup = builder.as_markup()
        await self.bot.send_message(chat_id, "Выберите тип заявки:", reply_markup=markup)

    async def attachenent_keyboard(self, chat_id: int):
        # Клавиатура для выбора загрузки вложения
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="Да", callback_data="upload_yes"),
            types.InlineKeyboardButton(text="Нет", callback_data="upload_no")
        )
        markup = builder.as_markup()
        await self.bot.send_message(chat_id, "Хотите загрузить документ или фотографию для заявки?", reply_markup=markup)

    async def reset_keyboard(self, chat_id: int):
        # Клавиатура для подтверждения сброса регистрации
        builder = InlineKeyboardBuilder()
        builder.row(
            types.InlineKeyboardButton(text="Да", callback_data="reset_yes"),
            types.InlineKeyboardButton(text="Нет", callback_data="reset_no")
        )
        markup = builder.as_markup()
        await self.bot.send_message(chat_id, "Вы уверены, что хотите сбросить регистрацию?", reply_markup=markup)

    async def callback_query_handler(self, call: types.CallbackQuery):
        # Универсальный обработчик inline‑кнопок
        user_id = call.from_user.id
        data = call.data

        if data == 'button_reset_reg':
            await call.answer("Вы нажали Сбросить регистрацию")
            await self.reset_keyboard(call.message.chat.id)

        elif data == 'button_reg':
            await call.answer("Вы нажали Регистрация пользователя")
            await self.registration(call)

        elif data == 'button_create_claim':
            await call.answer("Вы нажали Оставить заявку")
            self.ctx_data['claim_data'] = {}
            supabase_client = self.initialize_supabase_client()
            if supabase_client.check_user(user_id):
                await self.bot.send_message(call.message.chat.id,
                                            "Вы выбрали оставить заявку. Выберите приоритет заявки:")
                await self.priority_keyboard(call.message.chat.id)
            else:
                await self.bot.send_message(call.message.chat.id, "Нет регистрации или токен недействителен")
            supabase_client.logout()

        elif data == 'button_all_claims':
            self.ctx_data['list_of_claims'] = []
            await call.answer("Вы нажали Проверить статус заявки")
            supabase_client = self.initialize_supabase_client()
            if supabase_client.check_user(user_id):
                await self.bot.send_message(call.message.chat.id, "Вы выбрали посмотреть все открытые заявки")
                jira_token = supabase_client.get_token_from_supabase(user_id)
                if jira_token:
                    jira_client = JiraClient(jira_token)
                    self.ctx_data['list_of_claims'] = jira_client.get_claims_numbers_and_themes()
                    if self.ctx_data['list_of_claims']:
                        await self.keyboard_list_of_claims(call, 0)
                    else:
                        await self.bot.send_message(call.message.chat.id, "У вас нет созданных заявок")
                        await self.create_keyboard(call.message.chat.id, user_id)
                    jira_client.logout()
                else:
                    await self.bot.send_message(call.message.chat.id, "Нет регистрации или токен недействителен")
            else:
                await self.bot.send_message(call.message.chat.id, "Нет регистрации или токен недействителен")
            supabase_client.logout()

        elif data == 'button_check_claim':
            await self.get_claim_input_number(call)

        # Обработка выбора приоритета заявки
        elif data == 'button_middle':
            await self.bot.send_message(call.message.chat.id,
                                        "Выбран уровень статуса заявки: <b>средний</b>",
                                        parse_mode="HTML")
            self.ctx_data.setdefault('claim_data', {})['priority'] = os.environ.get("LOW_PRIORITY")
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            await self.type_keyboard(call.message.chat.id)

        elif data == 'button_high':
            await self.bot.send_message(call.message.chat.id,
                                        "Выбран уровень статуса заявки: <b>высокий</b>",
                                        parse_mode="HTML")
            self.ctx_data.setdefault('claim_data', {})['priority'] = os.environ.get("MIDDLE_PRIORITY")
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            await self.type_keyboard(call.message.chat.id)

        elif data == 'button_critical':
            await self.bot.send_message(call.message.chat.id,
                                        "Выбран уровень статуса заявки: <b>критический</b>",
                                        parse_mode="HTML")
            self.ctx_data.setdefault('claim_data', {})['priority'] = os.environ.get("HIGH_PRIORITY")
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            await self.type_keyboard(call.message.chat.id)

        # Обработка выбора типа заявки с переходом в FSM для ввода темы и описания
        elif data == 'button_type1':
            self.ctx_data.setdefault('claim_data', {})['type'] = self.typetask_field_1
            await self.bot.send_message(call.message.chat.id,
                                        f"Выбран тип заявки: <b>{self.typetask_field_1}</b>",
                                        parse_mode="HTML")
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            await self.bot.send_message(call.message.chat.id, "Введите тему заявки:")
            state = self.dp.current_state(user=call.from_user.id, chat=call.message.chat.id)
            await state.set_state(ClaimState.waiting_for_topic)

        elif data == 'button_type2':
            self.ctx_data.setdefault('claim_data', {})['type'] = self.typetask_field_2
            await self.bot.send_message(call.message.chat.id,
                                        f"Выбран тип заявки: <b>{self.typetask_field_2}</b>",
                                        parse_mode="HTML")
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
            await self.attachenent_keyboard(call.message.chat.id)

        elif data == 'main_menu_button':
            await self.create_keyboard(call.message.chat.id, user_id)

        elif data == "upload_yes":
            await self.bot.send_message(call.message.chat.id,
                                        "Пожалуйста, прикрепите файл или фотографию для заявки.")

        elif data == "upload_no":
            await self.upload_claim(call.message)

        elif data == "reset_yes":
            try:
                await self.bot.edit_message_reply_markup(call.message.chat.id,
                                                         call.message.message_id,
                                                         reply_markup=None)
            except Exception as e:
                print("Ошибка при удалении клавиатуры:", e)
            await self.reset_registration(call.message)

        elif data == "reset_no":
            try:
                await self.bot.edit_message_reply_markup(call.message.chat.id,
                                                         call.message.message_id,
                                                         reply_markup=None)
            except Exception as e:
                print("Ошибка при удалении клавиатуры:", e)
            await self.create_keyboard(call.message.chat.id, user_id)

    async def text_handler(self, message: types.Message):
        # Обработка стандартных текстовых сообщений (если не задействован FSM)
        await self.bot.send_message(message.chat.id, "Используйте кнопки для навигации по боту.")
        if 'username' in self.ctx_data:
            await self.create_keyboard(message.chat.id, self.ctx_data['username'])

    async def document_handler(self, message: types.Message):
        if message.document:
            file = await self.bot.get_file(message.document.file_id)
            downloaded = await self.bot.download_file(file.file_path)
            filename = message.document.file_name
            file_data = BytesIO(downloaded.getvalue())
            file_data.name = filename
            file_data.seek(0)
            self.ctx_data['attachment'] = file_data
            self.ctx_data['filename'] = filename
            await self.bot.send_message(message.chat.id,
                                        f"Файл {filename} успешно прикреплён к заявке.")
            await self.bot.send_message(message.chat.id, "Формирую заявку...")
            await self.upload_claim(message)
        else:
            await self.bot.send_message(message.chat.id, "Документ не найден.")
            await self.attachenent_keyboard(message.chat.id)

    async def photo_handler(self, message: types.Message):
        if message.photo:
            file = await self.bot.get_file(message.photo[-1].file_id)
            downloaded = await self.bot.download_file(file.file_path)
            file_data = BytesIO(downloaded.getvalue())
            file_data.name = "photo.jpg"
            file_data.seek(0)
            self.ctx_data['photo'] = file_data
            self.ctx_data['filename'] = file_data.name
            await self.bot.send_message(message.chat.id,
                                        "Фотография успешно прикреплена к заявке.")
            await self.upload_claim(message)
        else:
            await self.bot.send_message(message.chat.id, "Фотография не найдена.")
            await self.attachenent_keyboard(message.chat.id)

    async def registration(self, call: types.CallbackQuery):
        # Инициализируем FSM для регистрации
        supabase_client = self.initialize_supabase_client()
        if not supabase_client.check_user_token(call.from_user.id):
            await self.bot.send_message(call.message.chat.id,
                                        "Вы выбрали регистрацию пользователя. Введите email:")
            state = self.dp.current_state(user=call.from_user.id, chat=call.message.chat.id)
            await state.set_state(RegistrationState.waiting_for_email)
        else:
            await self.bot.send_message(call.message.chat.id, "Вы уже зарегистрированы")
        supabase_client.logout()

    async def process_registration_email(self, message: types.Message, state: FSMContext):
        # Обработка ввода email при регистрации
        if self.is_email(message.text):
            await state.update_data(email=message.text)
            await message.answer(
                "Чтобы создать токен, выполните следующие шаги:\n"
                "1. Перейдите по ссылке: https://support24.team/secure/ViewProfile.jspa\n"
                "2. Нажмите Create token (Создать токен) в правом верхнем углу\n"
                "3. Введите название токена и нажмите Create\n"
                "4. Скопируйте полученный токен и введите его здесь:"
            )
            await state.set_state(RegistrationState.waiting_for_token)
        else:
            await message.answer("Неправильный email. Введите email ещё раз:")

    async def process_registration_token(self, message: types.Message, state: FSMContext):
        # Обработка ввода токена при регистрации
        token_text = message.text.strip()
        if len(token_text) > 18:
            data = await state.get_data()
            email = data.get("email")
            user_id = message.from_user.id
            supabase_client = self.initialize_supabase_client()
            response = supabase_client.add_user(user_id, token_text, email)
            supabase_client.logout()
            if response:
                await message.answer("Регистрация прошла успешно!")
            else:
                await message.answer("Ошибка регистрации, попробуйте ещё раз.")
            await state.finish()
            await self.create_keyboard(message.chat.id, user_id)
        else:
            await message.answer("Токен введён неверно. Повторите ввод:")

    def is_email(self, text: str) -> bool:
        if not text:
            return False
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z.]+$"
        return re.match(pattern, text) is not None

    async def process_claim_topic(self, message: types.Message, state: FSMContext):
        # Обработка ввода темы заявки
        if message.text:
            self.ctx_data.setdefault('claim_data', {})['theme'] = message.text
            await message.answer("Введите описание заявки:")
            await state.set_state(ClaimState.waiting_for_description)
        else:
            await message.answer("Тема введена неверно, введите ещё раз:")

    async def process_claim_description(self, message: types.Message, state: FSMContext):
        # Обработка ввода описания заявки
        if len(message.text) > 1:
            self.ctx_data.setdefault('claim_data', {})['text'] = message.text
            await message.answer("Данные получены, формирую заявку...")
            await state.finish()
            await self.upload_claim(message)
        else:
            await message.answer("Описание заявки введено неверно, повторите:")

    async def upload_claim(self, message: types.Message):
        # Получаем токен Jira через Supabase и создаем заявку
        supabase_client = self.initialize_supabase_client()
        jira_token = supabase_client.get_token_from_supabase(message.from_user.id)
        if jira_token:
            jira_client = JiraClient(jira_token)
            response_claim_jira = jira_client.create_claim(message.from_user.id, self.ctx_data.get('claim_data', {}))
            jira_claim_number = response_claim_jira['issueKey'].split('-')[-1]
            claim_link = jira_client.get_claim_link_by_number(jira_claim_number)
            builder = InlineKeyboardBuilder()
            builder.row(
                types.InlineKeyboardButton(
                    text="Подписаться на обновления по заявке",
                    callback_data=f"subscribe_{jira_claim_number}"
                )
            )
            markup = builder.as_markup()
            if 'photo' in self.ctx_data:
                result = jira_client.add_photo_to_claim(jira_claim_number, self.ctx_data['photo'],
                                                        self.ctx_data.get('filename'))
                if result:
                    await self.bot.send_message(message.chat.id,
                                                f"Заявка успешно создана, вложение успешно добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка:\n{claim_link}",
                                                reply_markup=markup)
                else:
                    await self.bot.send_message(message.chat.id,
                                                f"Заявка успешно создана, но вложение не добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка:\n{claim_link}",
                                                reply_markup=markup)
            elif 'attachment' in self.ctx_data:
                result = jira_client.add_attachment_to_claim(jira_claim_number, self.ctx_data['attachment'],
                                                             self.ctx_data.get('filename'))
                if result:
                    await self.bot.send_message(message.chat.id,
                                                f"Заявка успешно создана, вложение успешно добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка:\n{claim_link}",
                                                reply_markup=markup)
                else:
                    await self.bot.send_message(message.chat.id,
                                                f"Заявка успешно создана, но вложение не добавлено, номер в Jira: <b>{jira_claim_number}</b>, ссылка:\n{claim_link}",
                                                reply_markup=markup)
            else:
                await self.bot.send_message(message.chat.id,
                                            f"Заявка успешно создана, номер в Jira: <b>{jira_claim_number}</b>, ссылка:\n{claim_link}",
                                            reply_markup=markup)
            jira_client.logout()
        else:
            await self.bot.send_message(message.chat.id,
                                        f"Пользователь {message.from_user.id} не зарегистрирован в Supabase")
        supabase_client.logout()

    async def get_claim_input_number(self, call: types.CallbackQuery):
        await self.bot.send_message(call.message.chat.id, "Введите номер заявки:")
        # Обработку ввода номера заявки можно реализовать аналогично с FSM или через отдельный обработчик

    async def keyboard_list_of_claims(self, call: types.CallbackQuery, start_index):
        try:
            await self.bot.edit_message_reply_markup(call.message.chat.id,
                                                     call.message.message_id,
                                                     reply_markup=None)
        except Exception as e:
            print("Не удалось удалить предыдущую клавиатуру:", e)
        start_index = int(start_index)
        buttons = []
        list_of_claims = self.ctx_data.get('list_of_claims', [])
        i, k = start_index, 0
        while i < len(list_of_claims) and k < self.buttons_per_page:
            buttons.append(
                [types.InlineKeyboardButton(
                    text=f"{list_of_claims[i]['number']} — {list_of_claims[i]['theme']}",
                    callback_data=f"claim_{list_of_claims[i]['number']}"
                )]
            )
            i += 1
            k += 1

        builder = InlineKeyboardBuilder()
        # Кнопки навигации (предыдущие/следующие заявки)
        if start_index - self.buttons_per_page >= 0:
            builder.row(
                types.InlineKeyboardButton(text="<< Предыдущие заявки",
                                           callback_data=f"list_of_claims_{start_index - self.buttons_per_page}")
            )
        if start_index + self.buttons_per_page < len(list_of_claims):
            builder.row(
                types.InlineKeyboardButton(text="Следующие заявки >>",
                                           callback_data=f"list_of_claims_{start_index + self.buttons_per_page}")
            )
        # Добавляем кнопки заявок (каждая кнопка в отдельном ряду)
        for row in buttons:
            builder.row(*row)
        markup = builder.as_markup()
        try:
            await self.bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            print("Не удалось удалить предыдущее сообщение:", e)
        await self.bot.send_message(call.message.chat.id,
                                    "Выберите заявку для проверки её статуса:",
                                    reply_markup=markup)

    def start_polling_scheduler(self):
        # Планировщик опроса статусов заявок каждые 5 минут
        schedule.every(5).minutes.do(self.poll_issue_status)

        def run_schedule():
            while True:
                schedule.run_pending()
                time.sleep(1)

        t = threading.Thread(target=run_schedule, daemon=True)
        t.start()

    def poll_issue_status(self):
        try:
            supabase_client = self.initialize_supabase_client()
            user_list = supabase_client.get_user_list()
            for user in user_list:
                subscriptions = supabase_client.get_subscriptions(user)
                jira_token = supabase_client.get_token_from_supabase(user)
                if jira_token:
                    jira_client = JiraClient(jira_token)
                    if subscriptions:
                        for sub in subscriptions:
                            claim_number = os.environ.get("GIRA_PROJECT_KEY") + '-' + str(
                                sub[os.environ.get("FIELD_SUBSCRIBE_CLAIM_NUMBER")]
                            )
                            last_status = sub.get(os.environ.get("FIELD_SUBSCRIBE_CLAIM_STATUS"), "")
                            try:
                                current_status = jira_client.check_claim_status(claim_number, user)['status']
                                claim_link = jira_client.get_claim_link_by_number(
                                    sub[os.environ.get("FIELD_SUBSCRIBE_CLAIM_NUMBER")]
                                )
                                if current_status != last_status:
                                    supabase_client.update_subscription_status(user, claim_number, current_status)
                                    asyncio.run(
                                        self.bot.send_message(
                                            user,
                                            f"Статус заявки {claim_number} изменился с {last_status} на: {current_status}.\n{claim_link}"
                                        )
                                    )
                                    if current_status in [os.environ.get("GIRA_TODO_DONE"), os.environ.get("GIRA_CLOSED")]:
                                        jira_client.delete_subscription(user, sub[os.environ.get("FIELD_SUBSCRIBE_CLAIM_NUMBER")])
                                        asyncio.run(
                                            self.bot.send_message(user, f"Подписка на обновление статуса заявки удалена")
                                        )
                            except Exception as e:
                                print(f"Ошибка опроса заявки {claim_number}: {e}")
                    jira_client.logout()
                # Можно добавить обработку случая отсутствия подписок
            supabase_client.logout()
        except Exception as e:
            print(f"Ошибка подключения к Supabase: {e}")

    async def reset_registration(self, message: types.Message):
        supabase_client = self.initialize_supabase_client()
        if supabase_client.check_user_token(message.from_user.id):
            response = supabase_client.delete_user_token(message.from_user.id)
            supabase_client.logout()
            if response:
                await self.bot.send_message(message.chat.id,
                                            "Токен пользователя был успешно удалён, пройдите регистрацию заново для дальнейшей работы")
                await self.create_keyboard(message.chat.id, message.from_user.id)
            else:
                await self.bot.send_message(message.chat.id, "Не удалось удалить токен пользователя")
        else:
            await self.bot.send_message(message.chat.id, "Пользователь не зарегистрирован")
            await self.create_keyboard(message.chat.id, message.from_user.id)

    async def run(self):
        # Бот передаётся в start_polling при запуске
        await self.dp.start_polling(self.bot)


if __name__ == '__main__':
    telegram_bot = TelegramBot()
    asyncio.run(telegram_bot.run())
