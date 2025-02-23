from dotenv import load_dotenv
import os
from supabase import create_client, Client


class SupabaseClient:
    def __init__(self):
        load_dotenv()   # Загрузить переменные окружения из .env
        self.url: str = os.environ.get("SUPABASE_URL")
        self.anon_key: str = os.environ.get("SUPABASE_KEY")
        self.table_username = os.environ.get("TABLE_USERNAME")
        self.field_username = os.environ.get("FIELD_USERNAME")
        self.table_claims = os.environ.get("TABLE_CLAIM")
        self.field_claims_user_id = os.environ.get("FIELD_CLAIMS_USER_ID")
        self.field_claims_text = os.environ.get("FIELD_CLAIMS_TEXT")
        self.field_claims_status = os.environ.get("FIELD_CLAIMS_STATUS")
        self.field_claims_text_new_status = os.environ.get("FIELD_CLAIMS_TEXT_NEW_STATUS")
        # Создать клиента Supabase с использованием анонимного ключа
        self.client: Client = create_client(self.url, self.anon_key)
        self.user = None # для будущей аутентификации


    def sign_in(self, email: str = None, password: str = None):
        """
        Выполнить аутентификацию пользователя. Если email и password не переданы,
        они будут загружены из переменных окружения.
        """
        if email is None:
            email = os.environ.get("USER_MAIL")
        if password is None:
            password = os.environ.get("USER_PASS")

        auth_response = self.client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
        self.user = auth_response
        return auth_response


    def get_data(self, table_name: str):
        response = self.client.table(self.table_username).select("*").execute()
        return response


    def check_user(self, username: str) -> bool:
        response = self.client.table(self.table_username).select(self.field_username).eq(self.field_username, username).execute()
        data = response.data
        if data and len(data) > 0:
            return True
        return False


    def add_user(self, username: str):
        if not self.check_user(username):
            data = {
                self.field_username: username
            }
            print(data)
            response = self.client.table(self.table_username).insert(data).execute()
            return response.data # Ответ от Supabase.
        else:
            return None


    def get_user_id_by_username(self, username: str):
        if self.check_user(username):
            response = self.client.table(self.table_username).select("id").eq(self.field_username, username).execute()
            data = response.data
            if data and len(data) > 0:
                return data[0].get("id")
        return None


    def create_claim(self, username: str, claim_text: str, claim_status: str = "new"):
        user_id = self.get_user_id_by_username(username)
        claim_data = {
            self.field_claims_user_id : user_id,
            self.field_claims_text: claim_text,
            self.field_claims_status : claim_status
        }
        response = self.client.table(self.table_claims).insert(claim_data).execute()
        return response.data


    def check_claims_status(self, username: str):
        user_id = self.get_user_id_by_username(username)
        response = self.client.table(self.table_claims).select("*").eq(self.field_claims_user_id, user_id).execute()
        # response = self.client.table(self.table_claims).select(self.field_claims_status).eq(self.field_claims_user_id, user_id).execute()
        data = response.data
        return data


if __name__ == "__main__":
    supabase_client = SupabaseClient()

    # Получить данные из таблицы до аутентификации
    response = supabase_client.get_data("sample_table").data
    print("Данные из таблицы (без аутентификации):", response)

    # Выполнить аутентификацию пользователя
    auth_response = supabase_client.sign_in()
    print("Результат аутентификации:", auth_response)

    # Получить данные из таблицы после аутентификации
    response = supabase_client.get_data("sample_table").data
    print("Данные из таблицы (после аутентификации):", response)

    # Проверка на наличие пользователя в БД
    response_check_user = supabase_client.check_user("user1")
    print("Проверка наличия пользователя:", response_check_user)

    # Проверка на вставку данных в БД
    response_insert_data = supabase_client.add_user("tgname2")
    print("Проверка вставки данных:", response_insert_data)

    # Проверка на создание заявки
    response_add_claim = supabase_client.create_claim("@tgname", "not everything is bad")
    print("Проверка на создание заявки:", response_add_claim)

    # Проверка статуса заявок
    response_check_status = supabase_client.check_claims_status("@tgname")
    print("Проверка статуса заявок:", response_check_status)