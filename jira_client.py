from dotenv import load_dotenv
import os
from jira import JIRA
from jira.exceptions import JIRAError

# author 10042
# status 10043
# theme 10044
# description 10045

class JiraClient:
    def __init__(self):
        load_dotenv()
        self.domain = os.environ.get("GIRA_DOMAIN")
        self.email = os.environ.get("GIRA_EMAIL")
        self.token = os.environ.get("GIRA_TOKEN")
        self.project_key = os.environ.get("GIRA_PROJECT_KEY")
        self.author_field = os.environ.get("GIRA_AUTHOR_FIELD")
        self.typetask_field = os.environ.get("GIRA_TYPETASK_FIELD")

        jira_options = {'server': self.domain}
        # Авторизация с помощью Basic Auth (email и API токен, полученный в настройках Atlassian)
        self.jira = JIRA(options=jira_options, basic_auth=(self.email, self.token))

    def create_claim(self, username, claim_data): # status):
        data = {
            'project': self.project_key,
            'summary': claim_data['theme'],
            'description': claim_data['text'],
            self.author_field: username,
            'priority': {"name": claim_data['priority']},
            'issuetype': {'name': self.typetask_field}  # можно указать тип задачи: Bug, Task, Story и т.д.
        }
        try:
            new_issue = self.jira.create_issue(data)
            print(f"Create claim: {new_issue.key}, link: \n{new_issue.permalink()}")
            return new_issue
        except Exception as e:
            print(f"Error creating claim for user '{username}': {str(e)}")
            return None

    def check_claim_status(self, claim_number, username):
        try:
            issue = self.jira.issue(self.project_key+'-'+str(claim_number))
            value_author = getattr(issue.fields, self.author_field, 'Поле не найдено')
            if value_author == username:
                claim_info = {}
                claim_info['status'] = issue.fields.status.name
                claim_info['summary'] = issue.fields.summary
                claim_info['description'] = issue.fields.description
                return claim_info
            else:
                # print('Не ваша заявка')
                return None
        except JIRAError as e:
            return None


if __name__ == "__main__":
    jira_client = JiraClient()

    # Получить данные из таблицы до аутентификации
    # claim_data = {'theme': 'theme', 'text': 'description', 'priority': 'High'}
    # response = jira_client.create_claim('user1', claim_data)
    # print("Загружены данные: ", response)

    print(jira_client.check_claim_status(30))
    print('---')