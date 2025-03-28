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

        self.table_claims = os.environ.get("TABLE_CLAIM")
        self.field_claims_user_id = os.environ.get("FIELD_CLAIMS_USER_ID")
        self.field_claims_priority = os.environ.get("FIELD_CLAIMS_PRIORITY")
        self.field_claims_theme = os.environ.get("FIELD_CLAIMS_THEME")
        self.field_claims_text = os.environ.get("FIELD_CLAIMS_TEXT")
        self.field_claims_text_new_status = os.environ.get("FIELD_CLAIMS_TEXT_NEW_STATUS")
        self.field_claims_number_in_jira = os.environ.get("FIELD_CLAIMS_NUMBER_IN_JIRA")
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
        try:
            response = self.client.table(self.table_username).select(self.field_username).eq(self.field_username, username).execute()
            data = response.data
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
                    "user_tg": int(username),
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

    def create_claim(self, username: str, claim_data: dict, jira_claim_number: int):
        user_id = self.get_user_id_by_username(username)
        data = {
            self.field_claims_user_id : user_id,
            self.field_claims_text: claim_data["text"],
            self.field_claims_theme: claim_data["theme"],
            self.field_claims_priority: claim_data["priority"],
            self.field_claims_number_in_jira: jira_claim_number
        }
        print(data)
        try:
            response = self.client.table(self.table_claims).insert(data).execute()
            return response.data
        except Exception as e:
            print(f"Error creating claim for user '{username}': {str(e)}")
            return None

    def get_claims_numbers_and_themes(self, username: int):
        if self.check_user(username):
            user_id = self.get_user_id_by_username(username) # находим user_id
            try:
                response = self.client.table(self.table_claims).select(self.field_claims_number_in_jira).eq(self.field_claims_user_id, user_id).execute() # поиск всех заявок
                # response = self.client.table(self.table_claims).select(self.field_claims_status).eq(self.field_claims_user_id, user_id).execute()
                data = response.data
                claim_numbers = [claim.get(self.field_claims_number_in_jira) for claim in data]
                return claim_numbers
            except Exception as e:
                print(f"Error get claim numbers for user '{username}': {str(e)}")
                return False
        return False

    def delete_user(self, username: int):
        try:
            response = self.client.table("users") \
                .delete(returning="representation") \
                .eq("user_tg", username) \
                .execute()
            return response.data
        except Exception as e:
            print(f"Ошибка удаления пользователя {username}: {e}")
            return None

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

    # Получить данные из таблицы до аутентификации
    response = supabase_client.get_data("users").data
    print("Данные из таблицы (без аутентификации): ", response)

    # Выполнить аутентификацию пользователя
    auth_response = supabase_client.sign_in()
    print("Результат аутентификации:", auth_response)

    # Получить данные из таблицы после аутентификации
    response = supabase_client.get_data("sample_table").data
    print("Данные из таблицы (после аутентификации):", response)

    # Проверка на наличие пользователя в БД
    response_check_user = supabase_client.check_user("user2")
    print("Проверка наличия пользователя:", response_check_user)

    # # Проверка на вставку данных в БД
    # response_insert_data = supabase_client.add_user("tgname2")
    # print("Проверка вставки данных:", response_insert_data)

    # Проверка на создание заявки
    claim_data = {'priority': 'low', 'theme': 'Всё плохо', 'text': 'Все очень плохо'}
    response_add_claim = supabase_client.create_claim("@tgname", claim_data)
    print("Проверка на создание заявки:", response_add_claim)

    # Проверка номеров заявок
    response_get_claim_numbers = supabase_client.get_claims_numbers("user1")
    print("У пользователя есть заявки:", response_get_claim_numbers)