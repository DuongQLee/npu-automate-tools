import json
import os
import re
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

# ==============================================================================
# 🛠️ 1. CONFIGURATION
# ==============================================================================
load_dotenv()
ATLASSIAN_DOMAIN = "moreh.atlassian.net"
ATLASSIAN_EMAIL = "duong.le@moreh.com.vn"
ATLASSIAN_API_TOKEN = os.getenv("API_TOKEN")

# Confluence Configuration
CONFLUENCE_SPACE = "MV"
CONFLUENCE_PARENT_ID = "2282618932"

DATE = None  # None (Today), -1 (Yesterday), or "YYYY-MM-DD"
MAX_HISTORY_COMMENTS = 20

CORE_JQL = 'component = "MV-NPU"'
# ==============================================================================

auth = HTTPBasicAuth(ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)
headers = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}
jira_base_url = f"https://{ATLASSIAN_DOMAIN}/rest/api/3"
confluence_base_url = f"https://{ATLASSIAN_DOMAIN}/wiki/rest/api/content"

# ==============================================================================
# 🧠 2. PARSERS & CONVERTERS
# ==============================================================================


def convert_adf_to_html(node, attachment_map):
    """Converts Jira's Atlassian Document Format (JSON) into Atlassian XML."""
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")

    if node_type == "text":
        text = node.get("text", "")
        for mark in node.get("marks", []):
            m_type = mark.get("type")
            if m_type == "strong":
                text = f"<strong>{text}</strong>"
            elif m_type == "em":
                text = f"<em>{text}</em>"
            elif m_type == "code":
                text = f"<code>{text}</code>"
            elif m_type == "link":
                href = mark.get("attrs", {}).get("href", "#")
                text = f'<a href="{href}">{text}</a>'
        return text

    if node_type == "hardBreak":
        return "<br/>"
    if node_type == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        return f'<a href="{url}">{url}</a>'

    inner_html = "".join([convert_adf_to_html(child, attachment_map)
                         for child in node.get("content", [])])

    if node_type == "doc":
        return inner_html
    elif node_type == "paragraph":
        return f"<p>{inner_html}</p>"
    elif node_type == "codeBlock":
        return f"<pre><code>{inner_html}</code></pre>"
    elif node_type == "bulletList":
        return f"<ul>{inner_html}</ul>"
    elif node_type == "orderedList":
        return f"<ol>{inner_html}</ol>"
    elif node_type == "listItem":
        return f"<li>{inner_html}</li>"
    elif node_type in ["mediaSingle", "mediaGroup"]:
        return f"<div>{inner_html}</div>"
    elif node_type == "media":
        attrs = node.get("attrs", {})
        alt_text = attrs.get("alt", "Attachment")
        return f"<p>📎 <strong>{alt_text}</strong></p>"
    return inner_html


def extract_structured_comment(html_text):
    text = re.sub(r'<[^>]+>\s*(Summary|Tags|Body):\s*<[^>]+>',
                  r'\1:', html_text, flags=re.IGNORECASE)
    text = re.sub(r'<strong>\s*(Summary|Tags|Body):\s*</strong>',
                  r'\1:', text, flags=re.IGNORECASE)

    if "Summary:" not in text:
        return None, None, html_text

    sum_match = re.search(
        r'Summary:\s*(.*?)(?:<br/>|</p>|<div|Tags:|Body:|$)', text, re.IGNORECASE)
    c_summary = re.sub(r'<[^>]+>', '', sum_match.group(1)
                       ).strip() if sum_match else "Update"

    tags_match = re.search(
        r'Tags:\s*(.*?)(?:<br/>|</p>|<div|Body:|$)', text, re.IGNORECASE)
    c_tags = re.sub(r'<[^>]+>', '', tags_match.group(1)
                    ).strip() if tags_match else ""

    if "Body:" in text:
        body_match = re.search(
            r'Body:\s*(?:</p>|<br/>|</div>)?(.*)', text, re.IGNORECASE | re.DOTALL)
        c_body = body_match.group(1).strip() if body_match else ""
    else:
        c_body = re.sub(r'^(?:<[^>]+>)*\s*Summary:.*?(?:<br/>|</p>|</div>)',
                        '', html_text, count=1, flags=re.IGNORECASE)
        c_body = re.sub(r'^(?:<[^>]+>)*\s*Tags:.*?(?:<br/>|</p>|</div>)',
                        '', c_body, count=1, flags=re.IGNORECASE)
        c_body = c_body.strip()

    return c_summary, c_tags, c_body

# ==============================================================================
# 🌐 3. CONFLUENCE API INTEGRATION (Enhanced Error Logging)
# ==============================================================================


def update_confluence_page(page_id, xml_content):
    print(f"\n🔍 Fetching Confluence page info for ID: {page_id}...")
    url = f"{confluence_base_url}/{page_id}?expand=version"

    # 1. Test GET Request
    resp = requests.get(url, headers=headers, auth=auth)

    if resp.status_code != 200:
        print(f"❌ CONFLUENCE GET FAILED - Status {resp.status_code}")
        print(f"🛑 Reason: {resp.text}")
        return

    data = resp.json()
    current_version = data.get("version", {}).get("number", 1)
    current_title = data.get("title", "Daily Report")

    print(f"📄 Found page: '{
          current_title}' (Current Version: {current_version})")
    print(f"🚀 Pushing update as Version {current_version + 1}...")

    # 2. Test PUT Request
    payload = {
        "id": str(page_id),
        "type": "page",
        "title": current_title,
        "version": {"number": current_version + 1},
        "body": {"storage": {"value": xml_content, "representation": "storage"}}
    }

    put_resp = requests.put(
        f"{confluence_base_url}/{page_id}", json=payload, headers=headers, auth=auth)

    if put_resp.status_code == 200:
        print(f"✅ Successfully updated Confluence page!")
    else:
        print(f"❌ CONFLUENCE PUT FAILED - Status {put_resp.status_code}")
        print(f"🛑 Reason: {put_resp.text}")

# ==============================================================================
# 🚀 4. HELPER FUNCTIONS
# ==============================================================================


def resolve_dates(user_date):
    if user_date is None:
        target = datetime.now()
    elif isinstance(user_date, int):
        target = datetime.now() + timedelta(days=user_date)
    elif isinstance(user_date, str):
        target = datetime.strptime(user_date, '%Y-%m-%d')
    else:
        raise ValueError("Invalid DATE format.")
    return target.strftime('%Y-%m-%d'), (target - timedelta(days=1)).strftime('%Y-%m-%d')


def fetch_issues(jql):
    search_url = f"{jira_base_url}/search/jql"
    response = requests.get(search_url, headers=headers, auth=auth, params={
                            "jql": jql, "fields": "summary,issuetype,attachment,parent,description,status", "maxResults": 100})
    return response.json().get("issues", []) if response.status_code == 200 else []


COMMENT_CACHE = {}


def fetch_comments(issue_key):
    if issue_key in COMMENT_CACHE:
        return COMMENT_CACHE[issue_key]
    url = f"{jira_base_url}/issue/{issue_key}/comment"
    resp = requests.get(url, headers=headers, auth=auth)
    comments = resp.json().get("comments", []) if resp.status_code == 200 else []
    COMMENT_CACHE[issue_key] = comments
    return comments

# ==============================================================================
# 🎯 5. MAIN EXECUTION
# ==============================================================================


def run_atlassian_snapshot():
    today_str, yesterday_str = resolve_dates(DATE)
    print(f"🗓️ Generating Atlassian XML Snapshot | Today: {
          today_str} | Yesterday: {yesterday_str}\n" + "-"*60)

    # Fetch Data
    active_epics = fetch_issues(
        f'{CORE_JQL} AND issuetype = Epic AND (status = "In Progress" OR status changed to "Done" on "{today_str}")')
    active_tasks = fetch_issues(
        f'{CORE_JQL} AND issuetype != Epic AND (status = "In Progress" OR status changed to "Done" on "{today_str}")')
    yesterday_epics = fetch_issues(
        f'{CORE_JQL} AND issuetype = Epic AND status WAS "In Progress" ON "{yesterday_str}"')
    yesterday_tasks = fetch_issues(
        f'{CORE_JQL} AND issuetype != Epic AND status WAS "In Progress" ON "{yesterday_str}"')

    def build_epic_map(epics, tasks):
        emap = {}
        for e in epics:
            emap[e["key"]] = {"summary": e["fields"]["summary"], "status": e["fields"].get("status", {}).get(
                "name", ""), "description": e["fields"].get("description"), "attachments": e["fields"].get("attachment", []), "tasks": []}
        emap["OTHER"] = {"summary": "Standalone Tasks", "status": "",
                         "description": None, "attachments": [], "tasks": []}
        for t in tasks:
            parent_key = t["fields"].get("parent", {}).get("key")
            if parent_key and parent_key in emap:
                emap[parent_key]["tasks"].append(t)
            else:
                emap["OTHER"]["tasks"].append(t)
        return emap

    epics_map = build_epic_map(active_epics, active_tasks)
    yest_epics_map = build_epic_map(yesterday_epics, yesterday_tasks)

    # ----------------------------------------------------------------------
    # GENERATE CONFLUENCE XML (Strict Atlassian Storage Format)
    # ----------------------------------------------------------------------
    def generate_confluence_xml(emap, target_date):
        xml = ""
        for epic_key, epic_data in emap.items():
            if epic_key == "OTHER" and not epic_data["tasks"]:
                continue
            e_sum = f"{epic_data['summary']} ✅" if epic_data.get(
                "status", "").lower() == "done" else epic_data['summary']
            epic_link = f'<a href="https://{ATLASSIAN_DOMAIN}/browse/{
                epic_key}">{epic_key}</a>' if epic_key != "OTHER" else "📌"

            xml += f"<h3>🔷 {epic_link} - {
                e_sum} ({len(epic_data['tasks'])} tasks)</h3>"

            if epic_key != "OTHER" and epic_data["description"]:
                parsed_desc = convert_adf_to_html(epic_data["description"], {})
                xml += f'<ac:structured-macro ac:name="expand"><ac:parameter ac:name="title">View Epic Description</ac:parameter><ac:rich-text-body>{
                    parsed_desc}</ac:rich-text-body></ac:structured-macro>'

            if epic_data["tasks"]:
                xml += "<ul>"
                for task in epic_data["tasks"]:
                    t_key, t_sum = task["key"], task["fields"]["summary"]
                    t_display = f"{t_sum} ✅" if task["fields"].get(
                        "status", {}).get("name", "").lower() == "done" else t_sum
                    xml += f"<li><strong><a href='https://{ATLASSIAN_DOMAIN}/browse/{
                        t_key}'>[{t_key}]</a> {t_display}</strong>"

                    comments = fetch_comments(t_key)
                    for c in comments:
                        dt_local = datetime.strptime(
                            c["created"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone()
                        if dt_local.strftime('%Y-%m-%d') == target_date:
                            c_sum, c_tags, c_body = extract_structured_comment(
                                convert_adf_to_html(c["body"], {}))
                            xml += f"<blockquote><strong>🗣️ {c['author']['displayName']}: {
                                c_sum or 'Update'}</strong><br/>{c_body}</blockquote>"
                    xml += "</li>"
                xml += "</ul>"
        return xml or "<p><em>No active items.</em></p>"

    confluence_xml = f"<h1>🚀 NPU Daily Sync Snapshot ({today_str})</h1><hr/>"
    confluence_xml += f"<h2>📅 TODAY ({today_str})</h2>" + \
        generate_confluence_xml(epics_map, today_str)
    confluence_xml += f"<h2>⏪ YESTERDAY ({yesterday_str})</h2>" + \
        generate_confluence_xml(yest_epics_map, yesterday_str)

    # Push to Confluence API
    update_confluence_page(CONFLUENCE_PARENT_ID, confluence_xml)


if __name__ == "__main__":
    run_atlassian_snapshot()
