from dotenv import load_dotenv
from datetime import datetime
import os
from jira import JIRA
from jira.exceptions import JIRAError
import requests
import mimetypes
from requests.auth import HTTPBasicAuth

class JiraClient():
    def __init__(self, token):
        load_dotenv()
        self.headers = {
            "X-Atlassian-Token": "no-check",
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }
        self.domain = os.environ.get("GIRA_DOMAIN")
        self.project_key = os.environ.get("GIRA_PROJECT_KEY")
        self.author_field = os.environ.get("GIRA_AUTHOR_FIELD")
        self.typetask_field_1 = os.environ.get("GIRA_TYPETASK_FIELD_1")
        self.typetask_field_2 = os.environ.get("GIRA_TYPETASK_FIELD_2")
        self.jira_name_prefix = os.environ.get("GIRA_NAME_PREFIX")
        jira_options = {'server': self.domain}
        # Авторизация с помощью Basic Auth (email и API токен, полученный в настройках Atlassian)
        self.jira = JIRA(options=jira_options, token_auth=token)  # basic_auth=(self.email, token))

    def create_claim(self, username, claim_data): # status):
        url = f"{self.domain}rest/servicedeskapi/request"
        # получение serviceDeskId
        serviceDeskId = self.get_servicedesk_number()
        if claim_data.get('text') and claim_data['type'] == self.typetask_field_1:
            data = {
            # #     'project': self.project_key,
            # #     'summary': claim_data['theme'],
            # #     'description': claim_data['text'],
            # #     'priority': {"name": claim_data['priority']},
            # #     'issuetype': {'name': claim_data['type']}
            # # }
            'serviceDeskId': serviceDeskId, #self.service_desk_id,  # идентификатор сервис-деска
            'requestTypeId': self.get_request_type_id(claim_data['type'], serviceDeskId), #claim_data.get('request_type_id'),  # ID выбранного типа запроса
            'requestFieldValues': {
                'summary': claim_data['theme'],
                'description': claim_data['text'],
                'priority': {"name": claim_data['priority']}
                }
            }
        elif not claim_data.get('text') and claim_data['type'] == self.typetask_field_2:
            data = {
            'serviceDeskId': serviceDeskId, #self.service_desk_id,  # идентификатор сервис-деска
            'requestTypeId': self.get_request_type_id(claim_data['type'], serviceDeskId), #claim_data.get('request_type_id'),  # ID выбранного типа запроса
            'requestFieldValues': {
                'summary': claim_data['theme'],
                'priority': {"name": claim_data['priority']}
                }
            }

        try:
            response = requests.post(url, json=data, headers=self.headers)
            response.raise_for_status()
            new_issue = response.json()
            print(new_issue)

            # new_issue = self.jira.create_issue(data)
            # print(f"Create claim: {new_issue.key}, link: \n{new_issue.permalink()}")
            #print(f"Create claim: {new_issue['key']}, link: \n{new_issue['permalink']}")
            return new_issue
        except Exception as e:
            print(f"Error creating claim for user '{username}': {str(e)}")
            return None

    def get_request_type_id(self, request_type_name, serviceDeskId):
        url = f"{self.domain}rest/servicedeskapi/servicedesk/{serviceDeskId}/requesttype"
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        request_types = response.json()
        for rt in request_types.get("values", []):
            if rt.get("name") == request_type_name:
                print(rt.get("id"))
                return rt.get("id")
        return None

    def add_attachment_to_claim(self, claim_number: int, downloaded_file, filename):
        try:
            issue_key = self.jira.issue(self.project_key + '-' + str(claim_number))

            attach_url = f"{self.domain}rest/api/2/issue/{issue_key}/attachments"

            mime_type, _ = mimetypes.guess_type(filename)
            if not mime_type:
                mime_type = "application/octet-stream"

            files = {
                "file": (filename, downloaded_file, mime_type)
            }

            attach_response = requests.post(attach_url, headers=self.headers, files=files)
            attach_response.raise_for_status()
            attachments = attach_response.json()
            if not attachments:
                print("Вложение не загружено")
                return None
            # Берём первое вложение
            attachment = attachments[0]

            comment_text = f"[Вложение {attachment['filename']}|{attachment['content']}]"

            comment_url = f"{self.domain}rest/api/2/issue/{issue_key}/comment"
            comment_data = {"body": comment_text}

            comment_response = requests.post(comment_url, json=comment_data, headers=self.headers)
            comment_response.raise_for_status()
            return comment_response.json()
        except Exception as e:
            print(f"Ошибка при добавлении комментария с документом: {e}")
            return None

    def add_photo_to_claim(self, claim_number: int, downloaded_file, filename):
        try:
            files = {
                "file": ("photo.jpg", downloaded_file, "image/jpeg")
            }
            issue_key = self.jira.issue(self.project_key + '-' + str(claim_number))
            url = f"{self.domain}rest/api/2/issue/{issue_key}/attachments"
            response = requests.post(url, headers=self.headers, files=files)
            response.raise_for_status()
        #     return response.json()
        #     response = self.jira.add_attachment(issue=issue, attachment=downloaded_file, filename=filename)
        #     return response
            attachment = response.json()[0]
            print('attachment = ', attachment)

            comment_text = f"Вложенная фотография:\n\n!{attachment['filename']}!"
            print('comment_text = ', comment_text)

            comment_url = f"{self.domain}rest/api/2/issue/{issue_key}/comment"
            comment_data = {
                "body": comment_text
            }
            comment_response = requests.post(comment_url, json=comment_data, headers=self.headers)
            print('comment_response = ', comment_response)
            comment_response.raise_for_status()
            return comment_response.json()
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
                    last_comment_created = comments[-1].created #.split('.')[0]
                    last_comment_id = int(comments[-1].id)
                else:
                    last_comment = None
                    last_comment_author = None
                    last_comment_created = None
                    last_comment_id = 0
                print('Проверили статус заявки')
                return {
                    'status': issue.fields.status.name,
                    'last_update': issue.fields.updated, #.split('.')[0],
                    'summary': issue.fields.summary,
                    'description': issue.fields.description,
                    'last_comment': {
                        'text': last_comment,
                        'author': last_comment_author,
                        'created': last_comment_created,
                        'id': last_comment_id
                    } if last_comment else None
                }
            else:
                print('Не ваша заявка')
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

    # def get_claim_status_by_number(self, claim_number):
    #     return self.domain.rstrip("/") + '/browse/' + claim_number

    def get_servicedesk_number(self):
        response = requests.get(self.domain.rstrip("/") + '/rest/servicedeskapi/servicedesk', headers=self.headers)
        if response:
            data = response.json()
            for item in data['values']:
                if item.get('projectKey') == self.project_key:
                    return item.get('_links').get('portal').split('/')[-1]
            return None

    def get_claim_link_by_number(self, claim_number):
        servivedesk_number = self.get_servicedesk_number()
        if servivedesk_number:
            return self.domain.rstrip("/") + '/servicedesk/customer/portal/' + servivedesk_number + '/' + self.project_key + '-' + str(claim_number)
        else:
            return None

    def get_claim_by_number(self, claim_number):
        return self.jira.issue(claim_number)

    def get_user_id(self):
        try:
            return int(self.jira.myself().get("key").split(self.jira_name_prefix)[1])
        except JIRAError as e:
            print(e)
            return None

    def get_user_email(self):
        user = self.jira.myself()
        print("Email:", user.get('emailAddress'))
        return user.get('emailAddress')

    def clear_token(self):
        if hasattr(self.jira, '_session'):
            self.jira._session.headers.pop('Authorization', None)

    def logout(self):
        del self.headers
        self.clear_token()
        if hasattr(self.jira, '_session'):
            self.jira._session.close()

    def readable_time(self, original_time):
        return datetime.strptime(original_time, "%Y-%m-%dT%H:%M:%S.%f%z")
        # dt = datetime.strptime(original_time, "%Y-%m-%d %H:%M:%S.%f%z")
        # formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
        # return f"{formatted}"

    # def get_list_of_requests_types(self, token):
    #     url = f"{self.domain}rest/servicedeskapi/servicedesk/3/requesttype"
    #
    #     headers = {
    #         "Authorization": f"Bearer {token}",
    #         "Accept": "application/json"
    #     }
    #
    #     response = requests.get(url, headers=headers)
    #     response.raise_for_status()
    #     print(response)


if __name__ == "__main__":
    TOKEN = ''
    jira_client = JiraClient(TOKEN)
    # print(jira_client.get_claims_numbers())

    # # Получить данные из таблицы до аутентификации
    # claim_data = {'theme': 'theme', 'type': 'Incident', 'text': 'description', 'priority': 'P1 - High'}
    # response = jira_client.create_claim('user1', claim_data)
    # print("Загружены данные: ", response)

    # print(jira_client.check_claim_status('TISM-1730', 1))

    # print(jira_client.add_comment_to_claim(30, "Simm20", "Текст комментария"))
    # print('---')

    # print('get_user_email() = ', jira_client.get_user_email())
    # jira_client.get_list_of_requests_types(TOKEN)

    # print(jira_client.get_claim_link_by_number(1775))

    # print(jira_client.get_user_id())


