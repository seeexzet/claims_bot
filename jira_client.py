from dotenv import load_dotenv
from datetime import datetime
import os
from jira import JIRA
from jira.exceptions import JIRAError
import requests
from requests.auth import HTTPBasicAuth
import json

class JiraClient():
    def __init__(self, token):
        load_dotenv()
        self.domain = os.environ.get("GIRA_DOMAIN")
        self.project_key = os.environ.get("GIRA_PROJECT_KEY")
        self.author_field = os.environ.get("GIRA_AUTHOR_FIELD")
        jira_options = {'server': self.domain}
        # Авторизация с помощью Basic Auth (email и API токен, полученный в настройках Atlassian)
        self.jira = JIRA(options=jira_options, token_auth=token)  # basic_auth=(self.email, token))

    def create_claim(self, username, claim_data): # status):
        data = {
            'project': self.project_key,
            'summary': claim_data['theme'],
            'description': claim_data['text'],
            'priority': {"name": claim_data['priority']},
            'issuetype': {'name': claim_data['type']}
        }
        try:
            new_issue = self.jira.create_issue(data)
            print(f"Create claim: {new_issue.key}, link: \n{new_issue.permalink()}")
            return new_issue
        except Exception as e:
            print(f"Error creating claim for user '{username}': {str(e)}")
            return None

    def add_attachment_to_claim(self, claim_number: int, downloaded_file, filename):
        try:
            # issue = self.jira.issue(self.project_key + '-' + str(claim_number))
            response = self.jira.add_attachment(issue=claim_number, attachment=downloaded_file, filename=filename)
            return response
        except Exception as e:
            print(f"Ошибка при загрузке файла в Jira: {e}")
            return None

    def check_claim_status(self, claim_number, username):
        try:
            issue = self.jira.issue(claim_number)
            if issue.fields.reporter.raw['key'] == self.jira.myself()['key']:     #self.jira.myself().get("accountId"):
                comments = issue.fields.comment.comments
                if comments:
                    last_comment = comments[-1].body
                    last_comment_author = comments[-1].author.displayName
                    last_comment_created = comments[-1].created
                else:
                    last_comment = None
                    last_comment_author = None
                    last_comment_created = None
                print('Проверили статус заявки')
                return {
                    'status': issue.fields.status.name,
                    'last_update': self.readable_time(issue.fields.updated),
                    'summary': issue.fields.summary,
                    'description': issue.fields.description,
                    'last_comment': {
                        'text': last_comment,
                        'author': last_comment_author,
                        'created': self.readable_time(last_comment_created)
                    } if last_comment else None
                }
            else:
                # print('Не ваша заявка')
                return None
        except JIRAError as e:
            return None

    def add_comment_to_claim(self, claim_number, username, comment_text):
        try:
            print('claim_number=', claim_number)
            issue = self.jira.issue(claim_number)

            if issue.fields.reporter.raw['key'] == self.jira.myself()['key']:
                return self.jira.add_comment(issue, comment_text)
            else:
                return None
        except JIRAError as e:
            print(e)
            return None

    def get_claims_numbers_and_themes(self):
        jql_query =  f"reporter = currentUser() AND project = {self.project_key}"
        issues = self.jira.search_issues(jql_query, maxResults=1000)
        claims = []
        for issue in issues:
            number = issue.key #int(issue.key.split('-')[1])
            theme = issue.fields.summary
            claims.append({'number': number, 'theme': theme})
        return list(reversed(claims))

    def get_theme_by_number(self, claim_number):
        try:
            issue = self.jira.issue(claim_number)
            theme = issue.fields.summary
            return theme
        except JIRAError as e:
            print(e)
            return None

    def get_claim_status_by_number(self, claim_number):
        return self.domain.rstrip("/") + '/browse/' + claim_number

    def get_claim_link_by_number(self, claim_number, token):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        response = requests.get(self.domain.rstrip("/") + '/rest/servicedeskapi/servicedesk', headers=headers)
        del token
        print('response get_claim_link_by_number = ', response)
        if response:
            data = response.json()
            portal_url = None
            print('data[values]', data['values'])
            for item in data['values']:
                if item.get('projectKey') == self.project_key:
                    print('Сейчас сформируем ссылку')
                    portal_url = self.domain.rstrip("/") + '/servicedesk/customer/portal/' + item.get('_links', {}).get('portal').split('/')[-1] + '/' + str(claim_number)
                    print('А вот и ссылка', portal_url)
                    break
            return portal_url

    def get_claim_by_number(self, claim_number):
        return self.jira.issue(claim_number)

    def get_user_email(self):
        user = self.jira.myself()
        print("Email:", user.get('emailAddress'))
        return user.get('emailAddress')

    def clear_token(self):
        if hasattr(self.jira, '_session'):
            self.jira._session.headers.pop('Authorization', None)

    def logout(self):
        self.clear_token()
        if hasattr(self.jira, '_session'):
            self.jira._session.close()

    def readable_time(self, original_time):
        return datetime.strptime(original_time, "%Y-%m-%dT%H:%M:%S.%f%z").strftime("%d.%m.%Y %H:%M:%S")


if __name__ == "__main__":
    TOKEN = ''
    jira_client = JiraClient(TOKEN)
    # print(jira_client.get_claims_numbers())

    # Получить данные из таблицы до аутентификации
    # claim_data = {'theme': 'theme', 'text': 'description', 'priority': 'High'}
    # response = jira_client.create_claim('user1', claim_data)
    # print("Загружены данные: ", response)

    # print(jira_client.check_claim_status(30, "Simm20"))
    #
    # print(jira_client.add_comment_to_claim(30, "Simm20", "Текст комментария"))
    # print('---')

    print('get_user_email() = ', jira_client.get_user_email())

