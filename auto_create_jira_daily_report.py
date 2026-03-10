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
MAX_HISTORY_COMMENTS = 20  # Max number of historical comments to show per task

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
    """Converts Jira's Atlassian Document Format (JSON) into clean HTML."""
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
                text = f'<a href="{href}" target="_blank">{text}</a>'
        return text

    if node_type == "hardBreak":
        return "<br/>"
    if node_type == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        return f'<a href="{url}" target="_blank">{url}</a>'

    inner_html = "".join([convert_adf_to_html(child, attachment_map)
                         for child in node.get("content", [])])

    if node_type == "doc":
        return inner_html
    elif node_type == "paragraph":
        return f"<p style='margin: 5px 0;'>{inner_html}</p>"
    elif node_type == "codeBlock":
        return f'<pre style="background: #f4f5f7; padding: 12px; border-radius: 4px; overflow-x: auto; font-family: monospace;"><code>{inner_html}</code></pre>'
    elif node_type == "bulletList":
        return f"<ul>{inner_html}</ul>"
    elif node_type == "orderedList":
        return f"<ol>{inner_html}</ol>"
    elif node_type == "listItem":
        return f"<li>{inner_html}</li>"
    elif node_type in ["mediaSingle", "mediaGroup"]:
        return f'<div>{inner_html}</div>'
    elif node_type == "media":
        attrs = node.get("attrs", {})
        alt_text = attrs.get("alt", "Attachment")
        return f'<p>📎 <strong>{alt_text}</strong></p>'
    return inner_html


def extract_structured_comment(html_text):
    text = re.sub(r'<[^>]+>\s*(Summary|Tags|Body):\s*<[^>]+>',
                  r'\1:', html_text, flags=re.IGNORECASE)
    text = re.sub(r'<strong>\s*(Summary|Tags|Body):\s*</strong>',
                  r'\1:', text, flags=re.IGNORECASE)

    if "Summary:" not in text:
        return None, None, html_text

    sum_match = re.search(
        r'Summary:\s*(.*?)(?:<br>|</p>|<div|Tags:|Body:|$)', text, re.IGNORECASE)
    c_summary = re.sub(r'<[^>]+>', '', sum_match.group(1)
                       ).strip() if sum_match else "Update"
    tags_match = re.search(
        r'Tags:\s*(.*?)(?:<br>|</p>|<div|Body:|$)', text, re.IGNORECASE)
    c_tags = re.sub(r'<[^>]+>', '', tags_match.group(1)
                    ).strip() if tags_match else ""

    if "Body:" in text:
        body_match = re.search(
            r'Body:\s*(?:</p>|<br>|</div>)?(.*)', text, re.IGNORECASE | re.DOTALL)
        c_body = body_match.group(1).strip() if body_match else ""
    else:
        c_body = re.sub(r'^(?:<[^>]+>)*\s*Summary:.*?(?:<br>|</p>|</div>)',
                        '', html_text, count=1, flags=re.IGNORECASE)
        c_body = re.sub(r'^(?:<[^>]+>)*\s*Tags:.*?(?:<br>|</p>|</div>)',
                        '', c_body, count=1, flags=re.IGNORECASE)
        c_body = c_body.strip()

    return c_summary, c_tags, c_body


def build_comment_ui(author, dt_local, parsed_html, color_hex, is_history=False):
    c_summary, c_tags, c_body = extract_structured_comment(parsed_html)
    bg_color = "#ffffff" if is_history else "#f9fafb"

    html = f"<div style='margin-bottom: 15px; padding: 10px; border-left: 3px solid {
        color_hex}; background: {bg_color};'>"
    html += f"<strong>🗣️ {author}</strong> <span style='color: #666; font-size: 0.85em;'>({
        dt_local.strftime('%Y-%m-%d %H:%M')})</span>"
    if c_summary:
        tags_html = ""
        if c_tags:
            clean_tags_str = re.sub(r'<[^>]+>', '', c_tags)
            individual_tags = [tag.strip()
                               for tag in clean_tags_str.split(',')]
            for tag in individual_tags:
                if tag:
                    tags_html += f"<span style='color: #0052cc; font-size: 0.85em; font-family: monospace; background: #e9eaf0; padding: 2px 8px; border-radius: 12px; margin-left: 6px; white-space: nowrap;'>{
                        tag}</span>"

        html += f"<div style='margin-top: 10px; border: 1px solid #dfe1e6; border-radius: 4px; background: white;'>"
        html += f"<details><summary style='cursor: pointer; padding: 10px; outline: none; background: #f4f5f7;'>"
        html += f"<div style='display: inline-flex; justify-content: space-between; align-items: center; width: calc(100% - 20px); vertical-align: middle;'>"
        html += f"<span style='font-weight: 600; color: #172b4d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-right: 15px;'>{
            c_summary}</span>"
        html += f"<div style='flex-shrink: 0;'>{
            tags_html}</div></div></summary>"
        html += f"<div style='padding: 15px; border-top: 1px solid #dfe1e6;'>{
            c_body}</div></details></div>"
    else:
        html += f"<div style='margin-top: 5px;'>{c_body}</div>"

    html += f"</div>"
    return html

# ==============================================================================
# 🌐 3. CONFLUENCE API INTEGRATION
# ==============================================================================


def get_confluence_page_version(page_id):
    url = f"{confluence_base_url}/{page_id}?expand=version"
    resp = requests.get(url, headers=headers, auth=auth)
    if resp.status_code == 200:
        return resp.json().get("version", {}).get("number", 1)
    return 1


def update_confluence_page(page_id, title, html_content):
    version = get_confluence_page_version(page_id)
    url = f"{confluence_base_url}/{page_id}"
    payload = {
        "version": {"number": version + 1},
        "title": title,
        "type": "page",
        "body": {"storage": {"value": html_content, "representation": "storage"}}
    }
    resp = requests.put(url, json=payload, headers=headers, auth=auth)
    print(f"🔄 Confluence Update [{page_id}]: Status {resp.status_code}")


def create_confluence_child_page(space, parent_id, title, html_content):
    check_url = f"{confluence_base_url}?spaceKey={space}&title={title}"
    check_resp = requests.get(check_url, headers=headers, auth=auth)
    if check_resp.status_code == 200 and check_resp.json().get("results"):
        print(f"⚠️ Child page '{title}' already exists. Overwriting...")
        existing_id = check_resp.json()["results"][0]["id"]
        update_confluence_page(existing_id, title, html_content)
        return
    payload = {
        "type": "page", "title": title, "ancestors": [{"id": parent_id}],
        "space": {"key": space}, "body": {"storage": {"value": html_content, "representation": "storage"}}
    }
    resp = requests.post(confluence_base_url, json=payload,
                         headers=headers, auth=auth)
    print(f"✅ Confluence Create '{title}': Status {resp.status_code}")

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


def run_daily_snapshot():
    today_str, yesterday_str = resolve_dates(DATE)
    print(f"🗓️ Generating Snapshot | Today: {t
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

    # Build HTML
    html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Daily Sync Snapshot ({today_str})</title>
          <style>body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; line-height: 1.6; color: #333; }}
          .history-btn {{ background-color: #e9eaf0; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; font-size: 0.9em; font-weight: bold; color: #172b4d; margin-top: 10px; width: 100%; text-align: left; }}
          .desc-collapse {{ margin-bottom: 15px; border: 1px dashed #dfe1e6; border-radius: 4px; }}
          #searchInput {{ width: 100%; padding: 14px 20px; font-size: 16px; border: 2px solid #dfe1e6; border-radius: 8px; outline: none; background-color: #fafbfc; }}</style>
          </head><body><h1>🚀 Nested Daily Snapshot</h1><hr/>"""

    html += f"<h2 style='background: #0052cc; color: white; padding: 10px; border-radius: 4px;'>📅 TODAY ({t
                                                                                                          today_str})</h2>"
    for epic_key, epic_data in epics_map.items():
        if epic_key == "OTHER" and not epic_data["tasks"]:
            continue
        epic_link = f"<a href='https://{ATLASSIAN_DOMAIN}/browse/{
            epic_key}' target='_blank'>[{epic_key}]</a>" if epic_key != "OTHER" else "📌"        e_status = epic_data.get("status", "")
        e_sum_display = f"{epic_data['summary']} ✅" if e_status.lower(
        ) == "done" else epic_data['summary']

        html += f"<details open style='margin-bottom: 20px; border: 2px solid #0052cc; border-radius: 6px;'><summary style='padding: 15px; background-color: #deebff; font-weight: bold;'>🔷 {e
                                                                                                                                                                                             epic_link} {e_sum_display} ({len(epic_data['tasks'])} tasks)</summary><div style='padding: 15px;'>" if epic_key != "OTHER":
            parsed_epic_desc = convert_adf_to_html(epic_data["description"], {
            }) if epic_data["description"] else "<em>No description.</em>"
            html += f"<details><summary>📄 View Epic Description</summary><div>{
                parsed_epic_desc}</div></details>"
        for task in epic_data["tasks"]:
            t_key, t_sum = task["key"], task["fields"]["summary"]
            t_status = task["fields"].get("status", {}).get("name", "")
            t_sum_display = f"{
                t_sum} ✅" if t_status.lower() == "done" else t_sum
            html += f"<details style='margin-bottom: 10px; border: 1px solid #dfe1e6; border-radius: 4px;'><summary style='padding: 10px; background-color: #f4f5f7;'>🛠️ <a href='https://{
                ATLASSIAN_DOMAIN}/browse/{t_key}'>[{t_key}]</a> {t_sum_display}</summary><div style='padding: 10px;'>"            comments = fetch_comments(t_key)
            todays_comments = "".join([build_comment_ui(c["author"]["displayName"], datetime.strptime(c["created"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(), convert_adf_to_html(
                c["body"], {}), "#36b37e") for c in comments if datetime.strptime(c["created"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone().strftime('%Y-%m-%d') == today_str])
            html += todays_comments or "<p><em>No comments today.</em></p>"
            html += "</div></details>"
        html += "</div></details>"

    html += f"<h2 style='background: #6554c0; color: white; padding: 10px; border-radius: 4px; margin-top: 40px;'>⏪ YESTERDAY ({
        yesterday_str})</h2>"
    # ... (Yesterday logic follows same pattern) ...
    html += "</body></html>"

    # --- SAVE LOCAL FILE ---
    filename = f"MV-NPU_Daily_Report_{today_str}.html"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"🏁 Saved: {filename}")

    # --- PUSH TO CONFLUENCE ---
    # Strip dangerous tags for Confluence
    confluence_html = re.sub(
        r'<head>.*?</head>|<!DOCTYPE html>|<html>|</html>|<body>|</body>|<script.*?>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    update_confluence_page(CONFLUENCE_PARENT_ID,
                           "Daily Report", confluence_html)


if __name__ == "__main__":
    run_daily_snapshot()
        r'<head>.*?</head>|<!DOCTYPE html>|<html>|</html>|<body>|</body>|<script.*?>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    update_confluence_page(CONFLUENCE_PARENT_ID,
                           "Daily Report", confluence_html)


if __name__ == "__main__":
    run_daily_snapshot()
