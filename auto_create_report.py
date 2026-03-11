import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

# ==============================================================================
# 🛠️ 1. CONFIGURATION
# ==============================================================================
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, ".env")
load_dotenv(env_path, override=True)

ATLASSIAN_DOMAIN = "moreh.atlassian.net"
ATLASSIAN_EMAIL = "duong.le@moreh.com.vn".strip()
ATLASSIAN_API_TOKEN = os.getenv("API_TOKEN", "").strip()

RESULT_FOLDER = os.getenv("RESULT_FOLDER", "./mv-npu_daily_report")
DATE = None
MAX_HISTORY_COMMENTS = 100

CORE_JQL = 'component = "MV-NPU"'

# 🚦 SMART STATUS BUCKETS
ACTIVE_STATUSES = '"In Progress", "Fixed/Review", "Blocked", "BLOCKED"'
PENDING_STATUSES = '"Open", "OPEN", "To Do", "TODO", "On Hold", "ON HOLD"'

# 🌍 Define Vietnam Timezone (UTC+7)
VN_TZ = timezone(timedelta(hours=7), name="ICT")

# ==============================================================================

auth = HTTPBasicAuth(ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)
headers = {"Accept": "application/json"}
jira_base_url = f"https://{ATLASSIAN_DOMAIN}/rest/api/3"

# ==============================================================================
# 🔐 2. AUTHENTICATION DIAGNOSTIC
# ==============================================================================


def verify_authentication():
    print("\n" + "=" * 60)
    print("🔐 VERIFYING JIRA AUTHENTICATION...")
    print("=" * 60)

    myself_url = f"{jira_base_url}/myself"
    response = requests.get(myself_url, headers=headers, auth=auth)

    if response.status_code == 200:
        user_data = response.json()
        print(f"✅ Auth SUCCESS!")
        print(f"👤 Logged in as : {user_data.get('displayName')}")
        print(f"📧 Email        : {user_data.get('emailAddress')}")
        print(f"✔️ Active       : {user_data.get('active')}")
        print("=" * 60 + "\n")
    else:
        print(f"❌ Auth FAILED!")
        print(f"⚠️ Status Code: {response.status_code}")
        print(f"⚠️ Response   : {response.text}")
        print("🚨 CRITICAL ERROR: Your API token or Email is invalid.")
        print("=" * 60 + "\n")
        sys.exit(1)


# ==============================================================================
# 🧠 3. PARSERS & CONVERTERS
# ==============================================================================


def convert_adf_to_html(node, attachment_map):
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
        return "<br>"
    if node_type == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        return f'<a href="{url}" target="_blank">{url}</a>'

    inner_html = "".join(
        [
            convert_adf_to_html(child, attachment_map)
            for child in node.get("content", [])
        ]
    )

    if node_type == "doc":
        return inner_html
    elif node_type == "paragraph":
        return f"<p style='margin: 5px 0;'>{inner_html}</p>"
    elif node_type == "codeBlock":
        return f'<pre style="background: #f4f5f7; padding: 12px; border-radius: 4px; overflow-x: auto; font-family: monospace; font-size: 0.9em;"><code>{inner_html}</code></pre>'
    elif node_type == "bulletList":
        return f"<ul style='margin-top: 5px; padding-left: 20px;'>{inner_html}</ul>"
    elif node_type == "orderedList":
        return f"<ol style='margin-top: 5px; padding-left: 20px;'>{inner_html}</ol>"
    elif node_type == "listItem":
        return f"<li>{inner_html}</li>"
    elif node_type in ["mediaSingle", "mediaGroup"]:
        return f'<div style="margin: 15px 0;">{inner_html}</div>'
    elif node_type == "media":
        attrs = node.get("attrs", {})
        alt_text = attrs.get("alt", "")
        if alt_text and alt_text in attachment_map:
            return f'<div style="border: 1px solid #dfe1e6; padding: 10px; background: #fafbfc; border-radius: 4px; display: inline-block; margin: 5px;">🖼️ <strong>Attached Media:</strong> {alt_text} <br><img src="{attachment_map[alt_text]}" alt="{alt_text}" style="max-width: 100%; margin-top: 10px; border: 1px solid #ccc;"/></div>'
        else:
            return f'<div style="border: 1px solid #dfe1e6; padding: 10px; background: #f4f5f7; border-radius: 4px; display: inline-block; margin: 5px;">📎 <strong>{alt_text or "Unnamed File"}</strong><br><span style="font-size: 0.8em; color: #666;">(UUID: {attrs.get("id", "Unknown")} - View in Jira)</span></div>'
    return inner_html


def extract_structured_comment(html_text):
    text = html_text
    text = re.sub(
        r"<(?:strong|b|em|i)[^>]*>\s*(Summary|Tags|Body)\s*</(?:strong|b|em|i)>\s*:",
        r"\1:",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<(?:strong|b|em|i)[^>]*>\s*(Summary|Tags|Body)\s*:\s*</(?:strong|b|em|i)>",
        r"\1:",
        text,
        flags=re.IGNORECASE,
    )

    if "Summary:" not in text:
        return None, None, html_text

    sum_match = re.search(
        r"Summary:\s*(.*?)(?:<br[^>]*>|</p>|</div>|Tags:|Body:|$)", text, re.IGNORECASE
    )
    c_summary = (
        re.sub(r"<[^>]+>", "", sum_match.group(1)).strip() if sum_match else "Update"
    )

    tags_match = re.search(
        r"Tags:\s*(.*?)(?:<br[^>]*>|</p>|</div>|Body:|$)", text, re.IGNORECASE
    )
    c_tags = re.sub(r"<[^>]+>", "", tags_match.group(1)).strip() if tags_match else ""

    if re.search(r"Body:", text, re.IGNORECASE):
        body_match = re.search(
            r"Body:\s*(?:</p>|<br[^>]*>|</div>)?(.*)", text, re.IGNORECASE | re.DOTALL
        )
        c_body = body_match.group(1).strip() if body_match else ""
    else:
        c_body = text
        if sum_match:
            c_body = re.sub(
                r"(?:<p[^>]*>)?\s*Summary:\s*.*?(?:</p>|<br[^>]*>|</div>)",
                "",
                c_body,
                count=1,
                flags=re.IGNORECASE,
            )
        if tags_match:
            c_body = re.sub(
                r"(?:<p[^>]*>)?\s*Tags:\s*.*?(?:</p>|<br[^>]*>|</div>)",
                "",
                c_body,
                count=1,
                flags=re.IGNORECASE,
            )
        c_body = c_body.strip()

    if not c_body:
        c_body = "<em>No additional details provided.</em>"
    return c_summary, c_tags, c_body


def build_comment_ui(author, dt_local, parsed_html, color_hex, is_history=False):
    c_summary, c_tags, c_body = extract_structured_comment(parsed_html)
    bg_color = "#ffffff" if is_history else "#f9fafb"

    html = f"<div style='margin-bottom: 15px; padding: 12px; border-left: 4px solid {color_hex}; border-radius: 0 6px 6px 0; background: {bg_color}; box-shadow: 0 1px 2px rgba(0,0,0,0.05);'>"
    html += f"<strong>🗣️ {author}</strong> <span style='color: #6b778c; font-size: 0.85em; margin-left: 6px;'>{dt_local.strftime('%b %d, %H:%M')}</span>"

    if c_summary:
        tags_html = ""
        if c_tags:
            clean_tags_str = re.sub(r"<[^>]+>", "", c_tags)
            individual_tags = [tag.strip() for tag in clean_tags_str.split(",")]
            for tag in individual_tags:
                if tag:
                    tags_html += f"<span class='tag-pill'>{tag}</span>"

        html += f"<div class='comment-card'>"
        html += f"<details><summary class='comment-summary'>"
        html += f"<span class='comment-title'>{c_summary}</span>"
        html += f"<div style='flex-shrink: 0;'>{tags_html}</div></summary>"
        html += f"<div class='comment-body'>{c_body}</div></details></div>"
    else:
        html += f"<div style='margin-top: 8px;'>{c_body}</div>"

    html += f"</div>"
    return html


# 🎨 DYNAMIC STATUS BADGE GENERATOR
def get_status_html(status_name):
    if not status_name:
        return ""
    s = status_name.lower()
    bg, text = "#dfe1e6", "#42526e"  # Default Gray for Pending/Open

    if s in ["done", "closed"]:
        bg, text = "#e3fcef", "#066637"  # Green
    elif s == "in progress":
        bg, text = "#deebff", "#0052cc"  # Blue
    elif s == "fixed/review":
        bg, text = "#eae6ff", "#403294"  # Purple
    elif s == "blocked":
        bg, text = "#ffebe6", "#bf2600"  # Red
    elif s == "on hold":
        bg, text = "#fffae6", "#ff8b00"  # Yellow/Orange

    return f"<span style='padding: 3px 8px; border-radius: 12px; font-size: 0.75em; font-weight: bold; margin-left: 8px; background: {bg}; color: {text}; white-space: nowrap;'>{status_name.upper()}</span>"


# ==============================================================================
# 🚀 4. HELPER FUNCTIONS
# ==============================================================================


def resolve_dates(user_date):
    if user_date is None:
        target = datetime.now(VN_TZ)
    elif isinstance(user_date, int):
        target = datetime.now(VN_TZ) + timedelta(days=user_date)
    elif isinstance(user_date, str):
        target = datetime.strptime(user_date, "%Y-%m-%d").replace(tzinfo=VN_TZ)
    else:
        raise ValueError("Invalid DATE format.")

    return (
        target.strftime("%Y-%m-%d"),
        (target - timedelta(days=1)).strftime("%Y-%m-%d"),
        (target + timedelta(days=1)).strftime("%Y-%m-%d"),
    )


def fetch_issues(jql):
    search_url = f"{jira_base_url}/search/jql"
    params = {
        "jql": jql,
        "fields": "summary,issuetype,attachment,parent,description,status",
        "maxResults": 100,
    }

    query_string = urllib.parse.urlencode(params)
    full_url = f"{search_url}?{query_string}"
    print(f"Calling GET: {full_url}")

    response = requests.get(search_url, headers=headers, auth=auth, params=params)

    if response.status_code == 200:
        data = response.json()
        issues = data.get("issues", [])
        total = data.get("total", 0)

        print(
            f"  └─ Status: ✅ 200 OK (Returned {len(issues)} issues. Total available: {total})"
        )
        if len(issues) == 0:
            print(
                f"  └─ ⚠️ WARNING: 0 issues found! Check JQL syntax, permissions, or Jira dates."
            )

        return issues
    else:
        print(f"  └─ Status: ❌ {response.status_code} ERROR")
        print(f"  └─ Reason: {response.text}")
        return []


COMMENT_CACHE = {}


def fetch_comments(issue_key):
    if issue_key in COMMENT_CACHE:
        return COMMENT_CACHE[issue_key]
    comments_url = f"{jira_base_url}/issue/{issue_key}/comment"

    response = requests.get(comments_url, headers=headers, auth=auth)

    if response.status_code == 200:
        data = response.json()
        comments = data.get("comments", [])
        COMMENT_CACHE[issue_key] = comments
        return comments
    else:
        COMMENT_CACHE[issue_key] = []
        return []


# ==============================================================================
# 🎯 5. MAIN EXECUTION
# ==============================================================================


def run_daily_snapshot(target_user_date):
    today_str, yesterday_str, next_str = resolve_dates(target_user_date)
    print(
        f"🗓️  Generating HTML Snapshot | Target (Vietnam): {today_str} | Target Yesterday (Vietnam): {yesterday_str}\n"
        + "-" * 60
    )

    actual_system_today = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    is_latest = today_str >= actual_system_today
    disabled_class = "disabled" if is_latest else ""
    disabled_attr = "disabled" if is_latest else ""

    # SAFE DONE JQL string construction to avoid parsing errors
    done_jql_today = f'(status changed to "Done" on "{today_str}" OR status changed to "Closed" on "{today_str}")'

    # QUERY: Active Today
    active_epics = fetch_issues(
        f"{CORE_JQL} AND issuetype = Epic AND (status IN ({ACTIVE_STATUSES}) OR {done_jql_today})"
    )
    active_tasks = fetch_issues(
        f"{CORE_JQL} AND issuetype != Epic AND (status IN ({ACTIVE_STATUSES}) OR {done_jql_today})"
    )

    # QUERY: Active Yesterday
    yesterday_epics = fetch_issues(
        f'{CORE_JQL} AND issuetype = Epic AND status WAS IN ({ACTIVE_STATUSES}) ON "{yesterday_str}"'
    )
    yesterday_tasks = fetch_issues(
        f'{CORE_JQL} AND issuetype != Epic AND status WAS IN ({ACTIVE_STATUSES}) ON "{yesterday_str}"'
    )

    def build_epic_map(epics, tasks):
        emap = {}
        for e in epics:
            emap[e["key"]] = {
                "summary": e["fields"]["summary"],
                "status": e["fields"].get("status", {}).get("name", ""),
                "description": e["fields"].get("description"),
                "attachments": e["fields"].get("attachment", []),
                "tasks": [],
            }
        emap["OTHER"] = {
            "summary": "Standalone Tasks (No Active Epic Parent)",
            "status": "",
            "description": None,
            "attachments": [],
            "tasks": [],
        }

        for t in tasks:
            parent_key = t["fields"].get("parent", {}).get("key")
            if parent_key and parent_key in emap:
                emap[parent_key]["tasks"].append(t)
            else:
                emap["OTHER"]["tasks"].append(t)
        return emap

    epics_map = build_epic_map(active_epics, active_tasks)
    yest_epics_map = build_epic_map(yesterday_epics, yesterday_tasks)

    html = f"""
      <!DOCTYPE html>
      <html lang="en">
      <head>
          <meta charset="UTF-8">
          <title>Daily Sync Snapshot ({today_str})</title>
          <style>
              /* 🌟 Modern CSS Reset & Basics */
              :root {{
                  --bg-body: #f4f5f7;
                  --text-main: #172b4d;
                  --text-muted: #5e6c84;
                  --border-color: #dfe1e6;
                  --epic-border-today: #0052cc;
                  --epic-bg-today: #ebf0f5;
                  --epic-border-yest: #6554c0;
                  --epic-bg-yest: #f0eff8;
              }}
              body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: var(--bg-body); color: var(--text-main); max-width: 1000px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }}
              a {{ color: #0052cc; text-decoration: none; }}
              a:hover {{ text-decoration: underline; }}
              
              /* 🎛️ Header Navigation */
              .header-container {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; padding-bottom: 20px; border-bottom: 2px solid var(--border-color); }}
              .nav-left, .nav-right {{ flex: 1; display: flex; }}
              .nav-left {{ justify-content: flex-start; }}
              .nav-right {{ justify-content: flex-end; }}
              .header-title {{ flex: 2; text-align: center; }}
              h1 {{ margin: 0; font-size: 1.8em; color: var(--text-main); }}
              
              .nav-btn {{ font-family: inherit; background: #ffffff; border: 1px solid var(--border-color); padding: 8px 16px; border-radius: 6px; font-weight: 600; font-size: 0.9em; box-shadow: 0 1px 3px rgba(0,0,0,0.05); transition: background 0.2s; color: var(--text-main); display: inline-flex; align-items: center; cursor: pointer; }}
              .nav-btn:hover:not(.disabled) {{ background: #f9fafb; }}
              .nav-btn.disabled {{ opacity: 0.4; cursor: not-allowed; background: #f4f5f7; border-color: #dfe1e6; box-shadow: none; }}

              /* 🔍 Search Bar */
              .search-container {{ margin-bottom: 30px; position: sticky; top: 10px; z-index: 100; }}
              #searchInput {{ width: 100%; padding: 14px 20px; font-size: 16px; border: 1px solid var(--border-color); border-radius: 8px; outline: none; box-sizing: border-box; background-color: #ffffff; box-shadow: 0 4px 6px rgba(0,0,0,0.05); transition: all 0.2s ease; }}
              #searchInput:focus {{ border-color: #0052cc; box-shadow: 0 0 0 3px rgba(0,82,204,0.15); }}

              /* 📦 Epic Blocks (Level 1) */
              .epic-block {{ margin-bottom: 24px; border-radius: 8px; background: #ffffff; box-shadow: 0 2px 8px rgba(9, 30, 66, 0.08); overflow: hidden; transition: all 0.2s; }}
              .epic-block[open] {{ box-shadow: 0 4px 12px rgba(9, 30, 66, 0.12); }}
              .epic-summary {{ padding: 16px 20px; font-weight: 600; font-size: 1.15em; cursor: pointer; user-select: none; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid transparent; }}
              .epic-block[open] .epic-summary {{ border-bottom: 1px solid var(--border-color); }}
              .epic-summary::-webkit-details-marker {{ display: none; }}
              .epic-content {{ padding: 20px; }}
              
              /* 📝 Task Blocks (Level 2) */
              .task-block {{ margin-bottom: 12px; border: 1px solid var(--border-color); border-radius: 6px; background: #ffffff; overflow: hidden; }}
              .task-summary {{ padding: 12px 16px; background: #fafbfc; font-weight: 500; font-size: 0.95em; cursor: pointer; user-select: none; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid transparent; transition: background 0.2s; }}
              .task-summary:hover {{ background: #f4f5f7; }}
              .task-block[open] .task-summary {{ border-bottom: 1px solid var(--border-color); background: #ffffff; }}
              .task-summary::-webkit-details-marker {{ display: none; }}
              .task-content {{ padding: 16px; background: #ffffff; }}

              /* 🏷️ Updates Badge */
              .update-badge {{ background: #e3fcef; color: #066637; padding: 4px 10px; border-radius: 12px; font-size: 0.85em; font-weight: bold; white-space: nowrap; }}
              .update-badge.zero {{ background: #f4f5f7; color: #5e6c84; font-weight: 500; }}
              .update-badge.purple {{ background: #eae6ff; color: #403294; }} 

              /* 💬 Comments Styling */
              .comment-card {{ margin-top: 10px; border: 1px solid var(--border-color); border-radius: 6px; background: #ffffff; }}
              .comment-summary {{ padding: 10px 14px; cursor: pointer; user-select: none; display: flex; justify-content: space-between; align-items: center; background: #fafbfc; border-radius: 6px; outline: none; }}
              .comment-summary::-webkit-details-marker {{ display: none; }}
              .comment-title {{ font-weight: 600; color: var(--text-main); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-right: 15px; }}
              .comment-body {{ padding: 15px; border-top: 1px solid var(--border-color); font-size: 0.95em; }}
              .tag-pill {{ color: #0052cc; font-size: 0.8em; font-family: monospace; background: #deebff; padding: 2px 8px; border-radius: 12px; margin-left: 6px; white-space: nowrap; font-weight: 600; }}

              /* ⚙️ Utility */
              .desc-collapse summary {{ cursor: pointer; padding: 8px 12px; background: #fafbfc; font-size: 0.9em; outline: none; border-bottom: 1px dashed var(--border-color); color: var(--text-muted); user-select: none; border-radius: 4px; }}
              .desc-collapse {{ margin-bottom: 20px; border: 1px dashed var(--border-color); border-radius: 4px; }}
              .history-btn {{ background-color: #fafbfc; border: 1px solid var(--border-color); padding: 8px 15px; border-radius: 6px; cursor: pointer; font-size: 0.9em; font-weight: 600; color: var(--text-muted); margin-top: 10px; width: 100%; text-align: left; transition: all 0.2s; }}
              .history-btn:hover {{ background-color: #f4f5f7; color: var(--text-main); }}
          </style>
          <script>
              function goToReport(dateStr) {{
                  let path = window.location.pathname;
                  if (path.match(/\\/today\\/?(index\\.html)?$/)) {{
                      window.location.href = '../MV-NPU_Daily_Report_' + dateStr + '.html';
                  }} else {{
                      window.location.href = 'MV-NPU_Daily_Report_' + dateStr + '.html';
                  }}
              }}

              function toggleHistory(id) {{
                  var el = document.getElementById(id);
                  var btn = document.getElementById('btn-' + id);
                  if (el.style.display === "none") {{
                      el.style.display = "block";
                      btn.innerHTML = "🔽 Hide Historical Comments";
                  }} else {{
                      el.style.display = "none";
                      btn.innerHTML = "▶️ Show Historical Comments";
                  }}
              }}

              function filterReport() {{
                  const query = document.getElementById('searchInput').value.toLowerCase();
                  const epics = document.querySelectorAll('.epic-block');
                  epics.forEach(epic => {{
                      const summaryText = epic.querySelector('.epic-summary').textContent.toLowerCase();
                      const descEl = epic.querySelector('.epic-desc');
                      const descText = descEl ? descEl.textContent.toLowerCase() : '';
                      const epicMatchesDirectly = summaryText.includes(query) || descText.includes(query);
                      const tasks = epic.querySelectorAll('.task-block');
                      let epicHasMatchingTask = false;
                      tasks.forEach(task => {{
                          const taskMatches = task.textContent.toLowerCase().includes(query);
                          if (taskMatches || epicMatchesDirectly) {{
                              task.style.display = 'block';
                              epicHasMatchingTask = true;
                              if (query !== '' && taskMatches) task.open = true;
                          }} else {{ task.style.display = 'none'; }}
                      }});
                      if (epicMatchesDirectly || epicHasMatchingTask || (tasks.length === 0 && epicMatchesDirectly)) {{
                          epic.style.display = 'block';
                          if (query !== '') epic.open = true;
                      }} else {{ epic.style.display = 'none'; }}
                  }});
              }}
          </script>
      </head>
      <body>
          <div class="header-container">
              <div class="nav-left">
                  <button onclick="goToReport('{yesterday_str}')" class="nav-btn">⬅️ Yesterday</button>
              </div>
              <div class="header-title">
                  <h1>MV-NPU Daily Report {today_str}</h1>
              </div>
              <div class="nav-right">
                  <button onclick="goToReport('{next_str}')" class="nav-btn {disabled_class}" {disabled_attr}>Next ➡️</button>
              </div>
          </div>
          
          <div class="search-container">
              <input type="text" id="searchInput" onkeyup="filterReport()" placeholder="🔍 Search tags, authors, tickets, or comments..." autocomplete="off">
          </div>
      """

    def generate_section(title_html, epics_data, target_date_str, is_yesterday=False):
        nonlocal html
        html += title_html

        if not epics_data or (
            len(epics_data) == 1 and not epics_data.get("OTHER", {}).get("tasks")
        ):
            html += f"<p style='color: #5e6c84;'><em>No active items found for this day.</em></p>"
            return

        for epic_key, epic_data in epics_data.items():
            if epic_key == "OTHER" and not epic_data["tasks"]:
                continue

            epic_link = (
                f"<a href='https://{ATLASSIAN_DOMAIN}/browse/{epic_key}' target='_blank'>[{epic_key}]</a>"
                if epic_key != "OTHER"
                else "📌"
            )

            # SMART STATUS DISPLAY FOR EPIC
            e_status = epic_data.get("status", "")
            e_sum_display = f"{epic_data['summary']} {get_status_html(e_status)}"

            border_color = (
                "var(--epic-border-yest)"
                if is_yesterday
                else "var(--epic-border-today)"
            )
            bg_color = "var(--epic-bg-yest)" if is_yesterday else "var(--epic-bg-today)"
            badge_color_class = "purple" if is_yesterday else ""

            epic_total_updates = 0
            for task in epic_data["tasks"]:
                comments = fetch_comments(task["key"])
                for comment in comments:
                    dt_jira = datetime.strptime(
                        comment["created"], "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    if (
                        dt_jira.astimezone(VN_TZ).strftime("%Y-%m-%d")
                        == target_date_str
                    ):
                        epic_total_updates += 1

            epic_badge_class = (
                f"update-badge {badge_color_class}"
                if epic_total_updates > 0
                else "update-badge zero"
            )
            epic_badge_text = (
                f"{epic_total_updates} Update{'s' if epic_total_updates != 1 else ''}"
            )

            html += f"<details {'open' if not is_yesterday else ''} class='epic-block' style='border-top: 4px solid {border_color};'>"
            html += f"<summary class='epic-summary' style='background: {bg_color};'>"
            html += f"<div style='display: flex; align-items: center;'>🔷&nbsp;{epic_link}&nbsp;{e_sum_display} <span style='font-weight: normal; font-size: 0.85em; color: var(--text-muted); margin-left: 8px;'>({len(epic_data['tasks'])} tasks)</span></div>"
            html += (
                f"<span class='{epic_badge_class}'>{epic_badge_text}</span></summary>"
            )
            html += f"<div class='epic-content'>"

            if epic_key != "OTHER":
                epic_att_map = {
                    att["filename"]: att["content"] for att in epic_data["attachments"]
                }
                parsed_epic_desc = (
                    convert_adf_to_html(epic_data["description"], epic_att_map)
                    if epic_data["description"]
                    else "<em>No description provided.</em>"
                )
                html += f"<details class='desc-collapse epic-desc'><summary>📄 View Epic Description</summary><div style='padding: 10px 15px; background-color: #ffffff; font-size: 0.95em;'>{parsed_epic_desc}</div></details>"

            if not epic_data["tasks"]:
                html += "<p style='color: var(--text-muted);'><em>No active tasks currently linked to this Epic.</em></p>"

            for task in epic_data["tasks"]:
                t_key, t_sum = task["key"], task["fields"]["summary"]

                # SMART STATUS DISPLAY FOR TASK
                t_status = task["fields"].get("status", {}).get("name", "")
                t_sum_display = f"{t_sum} {get_status_html(t_status)}"

                comments = fetch_comments(t_key)
                target_comments_data = []
                hist_comments_data = []

                for comment in comments:
                    dt_jira = datetime.strptime(
                        comment["created"], "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    dt_vn = dt_jira.astimezone(VN_TZ)

                    if dt_vn.strftime("%Y-%m-%d") == target_date_str:
                        target_comments_data.append((comment, dt_vn))
                    elif dt_vn.strftime("%Y-%m-%d") < target_date_str:
                        hist_comments_data.append((comment, dt_vn))

                update_count = len(target_comments_data)
                badge_class = (
                    f"update-badge {badge_color_class}"
                    if update_count > 0
                    else "update-badge zero"
                )
                badge_text = f"{update_count} Update{'s' if update_count != 1 else ''}"

                html += f"<details class='task-block'>"
                html += f"<summary class='task-summary'>"
                html += f"<div style='display: flex; align-items: center; gap: 8px;'>🛠️ <a href='https://{ATLASSIAN_DOMAIN}/browse/{t_key}' target='_blank'>[{t_key}]</a> {t_sum_display}</div>"
                html += f"<span class='{badge_class}'>{badge_text}</span></summary>"
                html += f"<div class='task-content'>"

                att_map = {
                    att["filename"]: att["content"]
                    for att in task["fields"].get("attachment", [])
                }
                task_desc_adf = task["fields"].get("description")
                parsed_task_desc = (
                    convert_adf_to_html(task_desc_adf, att_map)
                    if task_desc_adf
                    else "<em>No description provided.</em>"
                )
                html += f"<details class='desc-collapse'><summary>📄 View Task Description</summary><div style='padding: 10px 15px; background-color: #ffffff; font-size: 0.95em;'>{parsed_task_desc}</div></details>"

                target_comments_html = ""
                for c, dt_vn in target_comments_data:
                    parsed_body = convert_adf_to_html(c["body"], att_map)
                    target_comments_html += build_comment_ui(
                        c["author"]["displayName"],
                        dt_vn,
                        parsed_body,
                        border_color,
                        is_history=False,
                    )

                label = (
                    f"Updates on {target_date_str}"
                    if not is_yesterday
                    else f"Updates on {yesterday_str}"
                )
                if target_comments_html:
                    html += f"<h4 style='margin-top: 0; color: {border_color}; margin-bottom: 10px;'>{label}</h4>{target_comments_html}"
                else:
                    html += f"<p style='margin-top: 0; color: var(--text-muted); font-size: 0.9em;'><em>No comments made.</em></p>"

                if hist_comments_data:
                    hist_comments_data = hist_comments_data[-MAX_HISTORY_COMMENTS:]
                    final_hist_html = ""
                    for c, dt_vn in hist_comments_data:
                        parsed_body = convert_adf_to_html(c["body"], att_map)
                        final_hist_html += build_comment_ui(
                            c["author"]["displayName"],
                            dt_vn,
                            parsed_body,
                            "#a5adba",
                            True,
                        )

                    hist_div_id = f"hist-{'yest' if is_yesterday else 'today'}-{t_key}"
                    html += f"<button id='btn-{hist_div_id}' class='history-btn' onclick=\"toggleHistory('{hist_div_id}')\">▶️ Show Historical Comments (Last {len(hist_comments_data)})</button>"
                    html += f"<div id='{hist_div_id}' style='display: none; margin-top: 15px; padding-top: 15px; border-top: 1px dashed var(--border-color);'>{final_hist_html}</div>"

                html += "</div></details>"
            html += "</div></details>"

    generate_section(
        f"<h2 style='color: var(--text-main); margin-bottom: 15px;'>📅 Activity on {today_str}</h2>",
        epics_map,
        today_str,
        False,
    )
    generate_section(
        f"<h2 style='color: var(--text-main); margin-bottom: 15px; margin-top: 50px;'>⏪ Previous Day ({yesterday_str})</h2>",
        yest_epics_map,
        yesterday_str,
        True,
    )

    html += f"<h2 style='color: var(--text-main); margin-bottom: 15px; margin-top: 50px;'>⏸️ Upcoming & On Hold Epics</h2>"

    # QUERY: Pending Epics
    pending_epics = fetch_issues(
        f"{CORE_JQL} AND issuetype = Epic AND status IN ({PENDING_STATUSES})"
    )

    if pending_epics:
        for epic in pending_epics:
            e_key, e_sum = epic["key"], epic["fields"]["summary"]
            e_status = epic["fields"].get("status", {}).get("name", "")
            e_status_badge = get_status_html(e_status)

            html += f"<details class='epic-block' style='border-top: 4px solid #ff991f; margin-bottom: 10px;'>"
            html += f"<summary class='epic-summary' style='background: #fff4e5;'><div>⏳ <a href='https://{ATLASSIAN_DOMAIN}/browse/{e_key}' target='_blank'>[{e_key}]</a> <span style='margin-left:8px;'>{e_sum}</span> {e_status_badge}</div></summary>"
            html += f"<div class='epic-content'>"
            att_map = {
                att["filename"]: att["content"]
                for att in epic["fields"].get("attachment", [])
            }
            epic_desc_adf = epic["fields"].get("description")
            parsed_epic_desc = (
                convert_adf_to_html(epic_desc_adf, att_map)
                if epic_desc_adf
                else "<em>No description provided.</em>"
            )
            html += f"<details class='desc-collapse epic-desc'><summary>📄 View Epic Description</summary><div style='padding: 10px 15px; background-color: #ffffff; font-size: 0.95em;'>{parsed_epic_desc}</div></details></div></details>"
    else:
        html += "<p style='color: var(--text-muted);'><em>No Epics are currently pending or on hold.</em></p>"

    html += "</body></html>"

    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.isabs(RESULT_FOLDER):
        save_dir = RESULT_FOLDER
    else:
        save_dir = os.path.normpath(os.path.join(script_dir, RESULT_FOLDER))
    os.makedirs(save_dir, exist_ok=True)

    target_filename = f"MV-NPU_Daily_Report_{today_str}.html"
    file_path = os.path.join(save_dir, target_filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("-" * 60 + f"\n🏁 HTML Snapshot complete! Saved securely to:\n{file_path}")

    if is_latest:
        today_dir = os.path.join(save_dir, "today")
        os.makedirs(today_dir, exist_ok=True)
        symlink_path = os.path.join(today_dir, "index.html")
        if os.path.exists(symlink_path) or os.path.islink(symlink_path):
            os.remove(symlink_path)
        os.symlink(f"../{target_filename}", symlink_path)
        print(f"🔗 Clean URL active: /today -> {target_filename}")
    else:
        print(
            f"⏭️ Skipping symlink update. ({today_str} is not today's actual date: {actual_system_today})"
        )


if __name__ == "__main__":
    verify_authentication()

    dates_to_run = DATE if isinstance(DATE, list) else [DATE]
    processed_date_strings = set()

    for d in dates_to_run:
        try:
            target_str, _, _ = resolve_dates(d)
            if target_str not in processed_date_strings:
                run_daily_snapshot(d)
                processed_date_strings.add(target_str)
            else:
                print(
                    f"⏭️ Skipping {d} (Already processed as {target_str} in this run)"
                )
        except Exception as e:
            print(f"❌ Error processing date request '{d}': {e}")
