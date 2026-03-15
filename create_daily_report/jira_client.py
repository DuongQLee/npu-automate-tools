import urllib.parse

import config
import requests
from requests.auth import HTTPBasicAuth

auth = HTTPBasicAuth(config.ATLASSIAN_EMAIL, config.ATLASSIAN_API_TOKEN)
headers = {"Accept": "application/json"}
jira_base_url = f"https://{config.ATLASSIAN_DOMAIN}/rest/api/3"

COMMENT_CACHE = {}


def verify_authentication():
    print("\n" + "=" * 60)
    print("🔐 VERIFYING JIRA AUTHENTICATION...")
    response = requests.get(f"{jira_base_url}/myself", headers=headers, auth=auth)
    if response.status_code == 200:
        print(f"✅ Auth SUCCESS! Logged in as : {response.json().get('displayName')}")
        print("=" * 60 + "\n")
    else:
        print(f"❌ Auth FAILED! Status: {response.status_code}\n{response.text}")
        exit(1)


def fetch_issues(jql):
    search_url = f"{jira_base_url}/search/jql"
    params = {
        "jql": jql,
        "fields": "summary,issuetype,attachment,parent,description,status",
        "expand": "renderedFields",  # 🌟 MAGIC: Jira returns HTML instead of ADF JSON
        "maxResults": 100,
    }

    print(f"Calling GET: {search_url} (JQL: {jql})")
    response = requests.get(search_url, headers=headers, auth=auth, params=params)

    if response.status_code == 200:
        issues = response.json().get("issues", [])
        print(f"  └─ ✅ OK (Returned {len(issues)} issues)")
        return issues
    print(f"  └─ ❌ ERROR {response.status_code}: {response.text}")
    return []


def fetch_comments(issue_key):
    if issue_key in COMMENT_CACHE:
        return COMMENT_CACHE[issue_key]

    comments_url = f"{jira_base_url}/issue/{issue_key}/comment"
    params = {"expand": "renderedBody"}  # 🌟 MAGIC: Jira returns HTML comments

    response = requests.get(comments_url, headers=headers, auth=auth, params=params)
    if response.status_code == 200:
        comments = response.json().get("comments", [])
        COMMENT_CACHE[issue_key] = comments
        return comments

    COMMENT_CACHE[issue_key] = []
    return []
