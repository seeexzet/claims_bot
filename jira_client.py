from dotenv import load_dotenv
import os
from jira import JIRA

class JiraClient:
    def __init__(self):
        load_dotenv()
        self.domain = os.environ.get("GIRA_DOMAIN")
        self.email = os.environ.get("GIRA_EMAIL")
        self.token = os.environ.get("GIRA_SERVER")
        self.project_key = os.environ.get("PROJECT_KEY")

    def connection(self, domain, email, token):
        jira_options = {'server': self.domain}

        # Авторизация с помощью Basic Auth (email и API токен, полученный в настройках Atlassian)
        jira = JIRA(options=jira_options, basic_auth=(self.email, self.token))

        # Пример получения информации о проекте
        project = jira.project('PROJECT_KEY')
        print(f"Project name: {project.name}")