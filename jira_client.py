from dotenv import load_dotenv
import os
from jira import JIRA

import requests
import json

# author 10042
# status 10043
# theme 10044
# description 10045
# priority 10046

class JiraClient:
    def __init__(self):
        load_dotenv()
        self.domain = os.environ.get("GIRA_DOMAIN")
        self.email = os.environ.get("GIRA_EMAIL")
        self.token = os.environ.get("GIRA_TOKEN")
        self.project_key = os.environ.get("GIRA_PROJECT_KEY")

        jira_options = {'server': self.domain}
        # Авторизация с помощью Basic Auth (email и API токен, полученный в настройках Atlassian)
        self.jira = JIRA(options=jira_options, basic_auth=(self.email, self.token))

        # Пример получения информации о проекте
        # project = self.jira.project('PROJECT_KEY')
        # print(f"Project name: {project.name}")

    def add_claim(self, theme, description, priority, status):
        new_issue = self.jira.create_issue(
            project=self.project_key,
            summary=theme,
            description=description,
            customfield_10042='Автор, автор...',
            priority={"name": priority},
            issuetype={'name': 'Task'}  # можно указать тип задачи: Bug, Task, Story и т.д.
        )
        print(f"Задача создана: {new_issue.key}")


if __name__ == "__main__":
    jira_client = JiraClient()

    # Получить данные из таблицы до аутентификации
    response = jira_client.add_claim("theme", "description", "High", "Open")
    print("Загружены данные:", response)