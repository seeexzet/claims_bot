from dotenv import load_dotenv
import os
from supabase import create_client, Client


class SupabaseClient:
    def __init__(self):
        load_dotenv()   # Загрузить переменные окружения из .env
        self.url: str = os.environ.get("SUPABASE_URL")
        self.anon_key: str = os.environ.get("SUPABASE_KEY")
        self.email = os.environ.get("USER_MAIL")
        self.password = os.environ.get("USER_PASS")
        self.secret_code_for_token = os.environ.get("SUPABASE_SECRET_CODE_FOR_TOKEN")
        self.supabase_func_of_read = os.environ.get("SUPABASE_FUNCTION_OF_READ")
        self.supabase_func_of_insert = os.environ.get("SUPABASE_FUNCTION_OF_INSERT")

        self.table_username = os.environ.get("TABLE_USERNAME")
        self.field_username = os.environ.get("FIELD_USERNAME")
        self.field_fio = os.environ.get("FIELD_FIO")
        self.field_company = os.environ.get("FIELD_COMPANY")
        self.field_email = os.environ.get("FIELD_EMAIL")
        self.field_phone = os.environ.get("FIELD_PHONE")
        self.field_token = os.environ.get("FIELD_TOKEN")

        self.table_subscriptions = os.environ.get("TABLE_SUBSCRIBE")
        self.field_user_id = os.environ.get("FIELD_SUBSCRIBE_USER_ID")
        self.field_chat_id = os.environ.get("FIELD_SUBSCRIBE_CHAT_ID")
        self.field_claim_number = os.environ.get("FIELD_SUBSCRIBE_CLAIM_NUMBER")
        self.field_claim_status = os.environ.get("FIELD_SUBSCRIBE_CLAIM_STATUS")
        # Создать клиента Supabase с использованием анонимного ключа
        self.client: Client = create_client(self.url, self.anon_key)
        self.user = None # для будущей аутентификации

    def sign_in(self):
        auth_response = self.client.auth.sign_in_with_password({
            "email": self.email,
            "password": self.password,
        })
        self.user = auth_response
        return auth_response

    def get_data(self, table_name: str):
        response = self.client.table(self.table_username).select("*").execute()
        return response

    def check_user(self, username: int) -> bool:
        print('ttt ',username, type(username))
        try:
            response = self.client.table(self.table_username).select(self.field_username).eq(self.field_username, username).execute()
            data = response.data
            print(data)
            return bool(data and len(data) > 0)
        except Exception as e:
            return False

    def add_user(self, username: int, token: str): # registration_data: dict):
        if not self.check_user(username):
            data = {
                self.field_username: username,
                self.field_token: token
                # self.field_fio: registration_data['fio'],
                # self.field_company: registration_data['company'],
                # self.field_email: registration_data['email'],
                # self.field_phone: registration_data['phone']
            }
            try:
                # response = self.client.table(self.table_username).insert(data).execute()
                response = self.client.rpc(self.supabase_func_of_insert, {
                    self.field_username : int(username),
                    "token": token,
                    "enc_key": self.secret_code_for_token
                }).execute()
                del token
                return response.data # Ответ от Supabase.
            except Exception as e:
                print(f"Error adding user '{username}': {str(e)}")
                return None
        else:
            return None

    def get_user_id_by_username(self, username: int):
        if self.check_user(username):
            try:
                response = self.client.table(self.table_username).select("id").eq(self.field_username, username).execute()
                data = response.data
                if data and len(data) > 0:
                    return data[0].get("id")
            except Exception as e:
                print(f"Error searching user '{username}': {str(e)}")
                return None
        return None

    def get_username_by_user_id(self, user_id: int):
        try:
            response = self.client.table(self.table_username).select(self.field_username).eq("id", user_id).execute()
            data = response.data
            if data and len(data) > 0:
                return data[0].get(self.field_username)
        except Exception as e:
                print(f"Error searching user '{user_id}': {str(e)}")
                return None
        return None

    def get_token_from_supabase(self, username: int):
        if self.check_user(username):
            try:
                response = self.client.rpc(self.supabase_func_of_read, {
                    "p_name": username,
                    "p_key": self.secret_code_for_token
                }).execute()

                if response.data:
                    token = response.data
                    return token
                else:
                    print("Токен не найден или произошла ошибка:", response.error)
                    return None
            except Exception as e:
                print(f"Не удалось получить токен для пользователя {username}: {str(e)}")
                return None
        else:
            print(f"Нет пользователя с именем {username}")

    def delete_user(self, username: int):
        try:
            response = self.client.table(self.table_username) \
                .delete(returning="representation") \
                .eq(self.field_username, username) \
                .execute()
            return response.data
        except Exception as e:
            print(f"Ошибка удаления пользователя {username}: {e}")
            return None

    def save_subscription(self, username, chat_id, claim_number, status):
        try:
            user_id = self.get_user_id_by_username(username)
            response = self.client.table(self.table_subscriptions).insert({
                self.field_user_id: user_id,
                self.field_chat_id: chat_id,
                self.field_claim_number: claim_number,
                self.field_claim_status: status
            }).execute()
            return response
        except Exception as e:
            print(f"Ошибка сохранения подписки: {e}")
            return None

    def get_subscriptions(self):
        """
        Возвращает список подписок.
        Каждая подписка – словарь с ключами: username, issue_key, chat_id, last_status.
        """
        try:
            response = self.client.table(self.table_subscriptions).select("*").execute()
            return response.data
        except Exception as e:
            print(f"Ошибка получения подписок: {e}")
            return None

    def update_subscription_status(self, username, claim_number, chat_id, new_status):
        try:
            user_id = self.get_user_id_by_username(username)
            print(user_id, chat_id, claim_number.split('-')[1], new_status)
            # response = self.client.table(self.table_subscriptions).update({self.field_claim_status: new_status}).match({
            #     self.field_user_id: user_id,
            #     self.field_chat_id: chat_id,
            #     self.field_claim_number: int(claim_number.split('-')[1])
            # }).execute()
            response = self.client.table(self.table_subscriptions).update({self.field_claim_status: new_status})\
                .eq(self.field_user_id, user_id)\
                .eq(self.field_chat_id, chat_id)\
                .eq(self.field_claim_number, int(claim_number.split('-')[1]))\
            .execute()
            print(f"Поменяли статус в базе", response)
        except Exception as e:
            print(f"Ошибка обновления статуса подписки: {e}")

    def logout(self):
        try:
            response = self.client.auth.sign_out()
            self.user = None
            return response
        except Exception as e:
            print(f"Ошибка при выходе: {e}")
            return None


if __name__ == "__main__":
    supabase_client = SupabaseClient()
    supabase_client.sign_in()

    # # Получить данные из таблицы до аутентификации
    # response = supabase_client.get_data("users").data
    # print("Данные из таблицы (без аутентификации): ", response)
    #
    # # Выполнить аутентификацию пользователя
    # auth_response = supabase_client.sign_in()
    # print("Результат аутентификации:", auth_response)
    #
    # # Получить данные из таблицы после аутентификации
    # response = supabase_client.get_data("sample_table").data
    # print("Данные из таблицы (после аутентификации):", response)
    #
    # # Проверка на наличие пользователя в БД
    # response_check_user = supabase_client.check_user("user2")
    # print("Проверка наличия пользователя:", response_check_user)
    #
    # # # Проверка на вставку данных в БД
    # # response_insert_data = supabase_client.add_user("tgname2")
    # # print("Проверка вставки данных:", response_insert_data)
    #
    # # Проверка на создание заявки
    # claim_data = {'priority': 'low', 'theme': 'Всё плохо', 'text': 'Все очень плохо'}
    # response_add_claim = supabase_client.create_claim("@tgname", claim_data)
    # print("Проверка на создание заявки:", response_add_claim)
    #
    # # Проверка номеров заявок
    # response_get_claim_numbers = supabase_client.get_claims_numbers("user1")
    # print("У пользователя есть заявки:", response_get_claim_numbers)

    # # Записать подписку
    # response = supabase_client.save_subscription(1, 2222, "default_status").data
    # print("Результат записи новых данных в таблицу подписок: ", response)
    #
    # # Получить подписки
    # response = supabase_client.get_subscriptions()
    # print("Все подписки: ", response)

    # Получить имя пользователя по id
    # response = supabase_client.get_username_by_user_id(27)
    # print("Имя пользователя по id: ", response)


