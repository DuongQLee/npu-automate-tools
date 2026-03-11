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
# Force the script to read your specific local .env file!
load_dotenv("/home/moreh/npu-automate-tools/.env")

ATLASSIAN_DOMAIN = "moreh.atlassian.net"
ATLASSIAN_EMAIL = "duong.le@moreh.com.vn".strip()
ATLASSIAN_API_TOKEN = os.getenv("API_TOKEN", "").strip()

# Set the result folder (Defaults to ./mv-npu_daily_report)
RESULT_FOLDER = os.getenv("RESULT_FOLDER", "./mv-npu_daily_report")

DATE = None  # None (Today), -1 (Yesterday), or "YYYY-MM-DD"
MAX_HISTORY_COMMENTS = 20  # Max number of historical comments to show per task

CORE_JQL = 'component = "MV-NPU"'
# ==============================================================================

auth = HTTPBasicAuth(ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)
headers = {"Accept": "application/json"}
jira_base_url = f"https://{ATLASSIAN_DOMAIN}/rest/api/3"

# ==============================================================================
# 🧠 2. PARSERS & CONVERTERS
# ==============================================================================

def convert_adf_to_html(node, attachment_map):
    """Converts Jira's Atlassian Document Format (JSON) into clean HTML."""
    if not isinstance(node, dict): return ""
    node_type = node.get("type")

    if node_type == "text":
        text = node.get("text", "")
        for mark in node.get("marks", []):
            m_type = mark.get("type")
            if m_type == "strong": text = f"<strong>{text}</strong>"
            elif m_type == "em": text = f"<em>{text}</em>"
            elif m_type == "code": text = f"<code>{text}</code>"
            elif m_type == "link":
                href = mark.get("attrs", {}).get("href", "#")
                text = f'<a href="{href}" target="_blank">{text}</a>'
        return text

    if node_type == "hardBreak": return "<br>"
    if node_type == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        return f'<a href="{url}" target="_blank">{url}</a>'

    inner_html = "".join([convert_adf_to_html(child, attachment_map) for child in node.get("content", [])])

    if node_type == "doc": return inner_html
    elif node_type == "paragraph": return f"<p style='margin: 5px 0;'>{inner_html}</p>"
    elif node_type == "codeBlock": return f'<pre style="background: #f4f5f7; padding: 12px; border-radius: 4px; overflow-x: auto; font-family: monospace;"><code>{inner_html}</code></pre>'
    elif node_type == "bulletList": return f"<ul style='margin-top: 5px;'>{inner_html}</ul>"
    elif node_type == "orderedList": return f"<ol style='margin-top: 5px;'>{inner_html}</ol>"
    elif node_type == "listItem": return f"<li>{inner_html}</li>"
    elif node_type in ["mediaSingle", "mediaGroup"]: return f'<div style="margin: 15px 0;">{inner_html}</div>'
    elif node_type == "media":
        attrs = node.get("attrs", {})
        alt_text = attrs.get("alt", "")
        if alt_text and alt_text in attachment_map:
            return f'<div style="border: 1px solid #dfe1e6; padding: 10px; background: #fafbfc; border-radius: 4px; display: inline-block; margin: 5px;">🖼️ <strong>Attached Media:</strong> {alt_text} <br><img src="{attachment_map[alt_text]}" alt="{alt_text}" style="max-width: 100%; margin-top: 10px; border: 1px solid #ccc;"/></div>'
        else:
            return f'<div style="border: 1px solid #dfe1e6; padding: 10px; background: #f4f5f7; border-radius: 4px; display: inline-block; margin: 5px;">📎 <strong>{alt_text or "Unnamed File"}</strong><br><span style="font-size: 0.8em; color: #666;">(UUID: {attrs.get("id", "Unknown")} - View in Jira)</span></div>'
    return inner_html

def extract_structured_comment(html_text):
    text = re.sub(r'<[^>]+>\s*(Summary|Tags|Body):\s*<[^>]+>', r'\1:', html_text, flags=re.IGNORECASE)
    text = re.sub(r'<strong>\s*(Summary|Tags|Body):\s*</strong>', r'\1:', text, flags=re.IGNORECASE)

    if "Summary:" not in text: return None, None, html_text

    sum_match = re.search(r'Summary:\s*(.*?)(?:<br>|</p>|<div|Tags:|Body:|$)', text, re.IGNORECASE)
    c_summary = re.sub(r'<[^>]+>', '', sum_match.group(1)).strip() if sum_match else "Update"

    tags_match = re.search(r'Tags:\s*(.*?)(?:<br>|</p>|<div|Body:|$)', text, re.IGNORECASE)
    c_tags = re.sub(r'<[^>]+>', '', tags_match.group(1)).strip() if tags_match else ""

    if "Body:" in text:
        body_match = re.search(r'Body:\s*(?:</p>|<br>|</div>)?(.*)', text, re.IGNORECASE | re.DOTALL)
        c_body = body_match.group(1).strip() if body_match else ""
    else:
        c_body = re.sub(r'^(?:<[^>]+>)*\s*Summary:.*?(?:<br>|</p>|</div>)', '', html_text, count=1, flags=re.IGNORECASE)
        c_body = re.sub(r'^(?:<[^>]+>)*\s*Tags:.*?(?:<br>|</p>|</div>)', '', c_body, count=1, flags=re.IGNORECASE)
        c_body = c_body.strip()

    return c_summary, c_tags, c_body

def build_comment_ui(author, dt_local, parsed_html, color_hex, is_history=False):
    c_summary, c_tags, c_body = extract_structured_comment(parsed_html)
    bg_color = "#ffffff" if is_history else "#f9fafb"

    html = f"<div style='margin-bottom: 15px; padding: 10px; border-left: 3px solid {color_hex}; background: {bg_color};'>"
    html += f"<strong>🗣️ {author}</strong> <span style='color: #666; font-size: 0.85em;'>({dt_local.strftime('%Y-%m-%d %H:%M')})</span>"

    if c_summary:
        tags_html = ""
        if c_tags:
            clean_tags_str = re.sub(r'<[^>]+>', '', c_tags)
            individual_tags = [tag.strip() for tag in clean_tags_str.split(',')]
            for tag in individual_tags:
                if tag: tags_html += f"<span style='color: #0052cc; font-size: 0.85em; font-family: monospace; background: #e9eaf0; padding: 2px 8px; border-radius: 12px; margin-left: 6px; white-space: nowrap;'>{tag}</span>"

        html += f"<div style='margin-top: 10px; border: 1px solid #dfe1e6; border-radius: 4px; background: white;'>"
        html += f"<details><summary style='cursor: pointer; padding: 10px; outline: none; background: #f4f5f7;'>"
        html += f"<div style='display: inline-flex; justify-content: space-between; align-items: center; width: calc(100% - 20px); vertical-align: middle;'>"
        html += f"<span style='font-weight: 600; color: #172b4d; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-right: 15px;'>{c_summary}</span>"
        html += f"<div style='flex-shrink: 0;'>{tags_html}</div></div></summary>"
        html += f"<div style='padding: 15px; border-top: 1px solid #dfe1e6;'>{c_body}</div></details></div>"
    else:
        html += f"<div style='margin-top: 5px;'>{c_body}</div>"

    html += f"</div>"
    return html

# ==============================================================================
# 🚀 3. HELPER FUNCTIONS WITH ENHANCED LOGGING
# ==============================================================================

def resolve_dates(user_date):
    if user_date is None: target = datetime.now()
    elif isinstance(user_date, int): target = datetime.now() + timedelta(days=user_date)
    elif isinstance(user_date, str): target = datetime.strptime(user_date, '%Y-%m-%d')
    else: raise ValueError("Invalid DATE format.")
    return target.strftime('%Y-%m-%d'), (target - timedelta(days=1)).strftime('%Y-%m-%d')

def fetch_issues(jql):
    search_url = f"{jira_base_url}/search/jql"
    print(f"Calling GET: {search_url} | JQL: {jql}")
    response = requests.get(search_url, headers=headers, auth=auth, params={"jql": jql, "fields": "summary,issuetype,attachment,parent,description,status", "maxResults": 100})
    
    if response.status_code == 200:
        print(f"  └─ Status: ✅ 200 OK")
        return response.json().get("issues", [])
    else:
        print(f"  └─ Status: ❌ {response.status_code} ERROR")
        print(f"  └─ Reason: {response.text}")
        return []

COMMENT_CACHE = {}
def fetch_comments(issue_key):
    if issue_key in COMMENT_CACHE: return COMMENT_CACHE[issue_key]
    comments_url = f"{jira_base_url}/issue/{issue_key}/comment"
    print(f"Calling GET: {comments_url}")
    response = requests.get(comments_url, headers=headers, auth=auth)
    
    if response.status_code == 200:
        print(f"  └─ Status: ✅ 200 OK")
        comments = response.json().get("comments", [])
    else:
        print(f"  └─ Status: ❌ {response.status_code} ERROR")
        print(f"  └─ Reason: {response.text}")
        comments = []
        
    COMMENT_CACHE[issue_key] = comments
    return comments

# ==============================================================================
# 🎯 4. MAIN EXECUTION
# ==============================================================================

def run_daily_snapshot():
    today_str, yesterday_str = resolve_dates(DATE)
    print(f"🗓️  Generating HTML Snapshot | Today: {today_str} | Yesterday: {yesterday_str}\n" + "-"*60)

    active_epics = fetch_issues(f'{CORE_JQL} AND issuetype = Epic AND (status = "In Progress" OR status changed to "Done" on "{today_str}")')
    active_tasks = fetch_issues(f'{CORE_JQL} AND issuetype != Epic AND (status = "In Progress" OR status changed to "Done" on "{today_str}")')

    yesterday_epics = fetch_issues(f'{CORE_JQL} AND issuetype = Epic AND status WAS "In Progress" ON "{yesterday_str}"')
    yesterday_tasks = fetch_issues(f'{CORE_JQL} AND issuetype != Epic AND status WAS "In Progress" ON "{yesterday_str}"')

    def build_epic_map(epics, tasks):
        emap = {}
        for e in epics:
            emap[e["key"]] = {"summary": e["fields"]["summary"], "status": e["fields"].get("status", {}).get("name", ""), "description": e["fields"].get("description"), "attachments": e["fields"].get("attachment", []), "tasks": []}
        emap["OTHER"] = {"summary": "Standalone Tasks (No Active Epic Parent)", "status": "", "description": None, "attachments": [], "tasks": []}

        for t in tasks:
            parent_key = t["fields"].get("parent", {}).get("key")
            if parent_key and parent_key in emap: emap[parent_key]["tasks"].append(t)
            else: emap["OTHER"]["tasks"].append(t)
        return emap

    epics_map = build_epic_map(active_epics, active_tasks)
    yest_epics_map = build_epic_map(yesterday_epics, yesterday_tasks)

    html = f"""
      <!DOCTYPE html>
      <html>
      <head>
          <meta charset="UTF-8">
          <title>Daily Sync Snapshot ({today_str})</title>
          <style>
          body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; line-height: 1.6; color: #333; }}
              .history-btn {{ background-color: #e9eaf0; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; font-size: 0.9em; font-weight: bold; color: #172b4d; margin-top: 10px; width: 100%; text-align: left; }}
              .history-btn:hover {{ background-color: #dfe1e6; }}
              .desc-collapse summary {{ cursor: pointer; padding: 8px 10px; background-color: #fafbfc; font-size: 0.9em; outline: none; border-bottom: 1px dashed #dfe1e6; color: #505f79; }}
              .desc-collapse {{ margin-bottom: 15px; border: 1px dashed #dfe1e6; border-radius: 4px; }}
              #searchInput {{ width: 100%; padding: 14px 20px; font-size: 16px; border: 2px solid #dfe1e6; border-radius: 8px; outline: none; box-sizing: border-box; background-color: #fafbfc; color: #172b4d; transition: all 0.2s ease; }}
              #searchInput:focus {{ border-color: #0052cc; background-color: #fff; box-shadow: 0 0 0 3px rgba(0,82,204,0.1); }}
          </style>
          <script>
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
                      const summaryText = epic.querySelector('summary').textContent.toLowerCase();
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
          <h1>🚀 Nested Daily Snapshot</h1>
          <div style="margin: 20px 0 30px 0; position: sticky; top: 10px; z-index: 100;">
              <input type="text" id="searchInput" onkeyup="filterReport()" placeholder="🔍 Search tags, authors, tickets, or comments..." autocomplete="off">
          </div>
          <hr/>
      """

    def generate_section(title_html, epics_data, target_date_str, is_yesterday=False):
        nonlocal html
        html += title_html

        if not epics_data or (len(epics_data) == 1 and not epics_data.get("OTHER", {}).get("tasks")):
            html += f"<p><em>No active items found.</em></p>"
            return

        for epic_key, epic_data in epics_data.items():
            if epic_key == "OTHER" and not epic_data["tasks"]: continue

            epic_link = f"<a href='https://{ATLASSIAN_DOMAIN}/browse/{epic_key}' target='_blank'>[{epic_key}]</a>" if epic_key != "OTHER" else "📌"
            e_status = epic_data.get("status", "")
            e_sum_display = f"{epic_data['summary']} ✅" if e_status.lower() == "done" else epic_data['summary']

            border_color = "#6554c0" if is_yesterday else "#0052cc"
            bg_color = "#eae6ff" if is_yesterday else "#deebff"
            html += f"<details {'open' if not is_yesterday else ''} class='epic-block' style='margin-bottom: 20px; border: 2px solid {border_color}; border-radius: 6px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);'>"
            html += f"<summary style='cursor: pointer; padding: 15px; background-color: {bg_color}; font-weight: bold; font-size: 1.2em; border-bottom: 1px solid {border_color}; outline: none;'>"
            html += f"🔷 {epic_link} {e_sum_display} <span style='font-weight: normal; font-size: 0.8em; color: {border_color};'>({len(epic_data['tasks'])} tasks)</span></summary>"
            html += f"<div style='padding: 15px; background-color: #ffffff;'>"

            if epic_key != "OTHER":
                epic_att_map = {att["filename"]: att["content"] for att in epic_data["attachments"]}
                parsed_epic_desc = convert_adf_to_html(epic_data["description"], epic_att_map) if epic_data["description"] else "<em>No description provided.</em>"
                html += f"<details class='desc-collapse epic-desc'><summary>📄 View Epic Description</summary><div style='padding: 10px 15px; background-color: #ffffff; font-size: 0.95em;'>{parsed_epic_desc}</div></details>"

            if not epic_data["tasks"]: html += "<p style='color: #7a869a;'><em>No active tasks currently linked to this Epic.</em></p>"

            for task in epic_data["tasks"]:
                t_key, t_sum = task["key"], task["fields"]["summary"]
                t_status = task["fields"].get("status", {}).get("name", "")
                t_sum_display = f"{t_sum} ✅" if t_status.lower() == "done" else t_sum

                html += f"<details class='task-block' style='margin-bottom: 15px; border: 1px solid #dfe1e6; border-radius: 4px;'>"
                html += f"<summary style='cursor: pointer; padding: 10px; background-color: #f4f5f7; font-weight: bold; font-size: 1.0em; outline: none;'>🛠️ <a href='https://{ATLASSIAN_DOMAIN}/browse/{t_key}' target='_blank'>[{t_key}]</a> {t_sum_display}</summary>"
                html += f"<div style='padding: 15px; background-color: #ffffff;'>"

                att_map = {att["filename"]: att["content"] for att in task["fields"].get("attachment", [])}
                task_desc_adf = task["fields"].get("description")
                parsed_task_desc = convert_adf_to_html(task_desc_adf, att_map) if task_desc_adf else "<em>No description provided.</em>"
                html += f"<details class='desc-collapse'><summary>📄 View Task Description</summary><div style='padding: 10px 15px; background-color: #ffffff; font-size: 0.95em;'>{parsed_task_desc}</div></details>"

                comments = fetch_comments(t_key)
                target_comments_html, hist_comments_list = "", []

                for comment in comments:
                    dt_local = datetime.strptime(comment["created"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone()
                    parsed_body = convert_adf_to_html(comment["body"], att_map)

                    if dt_local.strftime('%Y-%m-%d') == target_date_str:
                        target_comments_html += build_comment_ui(comment["author"]["displayName"], dt_local, parsed_body, border_color, is_history=False)
                    elif dt_local.strftime('%Y-%m-%d') < target_date_str:
                        hist_comments_list.append((comment["author"]["displayName"], dt_local, parsed_body))

                label = "Today's Updates" if not is_yesterday else "Yesterday's Updates"
                if target_comments_html: html += f"<h4 style='margin-top: 0; color: {border_color};'>{label}</h4>{target_comments_html}"
                else: html += f"<p style='margin-top: 0; color: #7a869a; font-size: 0.9em;'><em>No comments made.</em></p>"

                if hist_comments_list:
                    hist_comments_list = hist_comments_list[-MAX_HISTORY_COMMENTS:]
                    final_hist_html = "".join([build_comment_ui(a, d, p, "#7a869a", True) for a, d, p in hist_comments_list])
                    hist_div_id = f"hist-{'yest' if is_yesterday else 'today'}-{t_key}"
                    html += f"<button id='btn-{hist_div_id}' class='history-btn' onclick=\"toggleHistory('{hist_div_id}')\">▶️ Show Historical Comments (Last {len(hist_comments_list)})</button>"
                    html += f"<div id='{hist_div_id}' style='display: none; margin-top: 15px; padding-top: 15px; border-top: 1px dashed #dfe1e6;'>{final_hist_html}</div>"

                html += "</div></details>"
            html += "</div></details>"

    # 1. TODAY
    generate_section(f"<h2 style='background: #0052cc; color: white; padding: 10px; border-radius: 4px;'>📅 TODAY ({today_str})</h2>", epics_map, today_str, False)

    # 2. YESTERDAY
    generate_section(f"<h2 style='background: #6554c0; color: white; padding: 10px; border-radius: 4px; margin-top: 40px;'>⏪ YESTERDAY ({yesterday_str})</h2>", yest_epics_map, yesterday_str, True)

    # 3. UPCOMING
    html += f"<h2 style='background: #ff991f; color: white; padding: 10px; border-radius: 4px; margin-top: 40px;'>⏸️ UPCOMING & ON HOLD EPICS</h2>"
    pending_epics = fetch_issues(f'{CORE_JQL} AND issuetype = Epic AND status IN ("To Do", "On Hold")')
    if pending_epics:
        for epic in pending_epics:
            e_key, e_sum = epic["key"], epic["fields"]["summary"]
            html += f"<details class='epic-block' style='margin-bottom: 10px; border: 1px solid #dfe1e6; border-radius: 4px;'>"
            html += f"<summary style='cursor: pointer; padding: 10px; background-color: #fff0b3; font-weight: bold; outline: none;'>⏳ <a href='https://{ATLASSIAN_DOMAIN}/browse/{e_key}' target='_blank'>[{e_key}]</a> {e_sum}</summary>"
            html += f"<div style='padding: 15px; background-color: #ffffff;'>"
            att_map = {att["filename"]: att["content"] for att in epic["fields"].get("attachment", [])}
            epic_desc_adf = epic["fields"].get("description")
            parsed_epic_desc = convert_adf_to_html(epic_desc_adf, att_map) if epic_desc_adf else "<em>No description provided.</em>"
            html += f"<details class='desc-collapse epic-desc'><summary>📄 View Epic Description</summary><div style='padding: 10px 15px; background-color: #ffffff; font-size: 0.95em;'>{parsed_epic_desc}</div></details></div></details>"
    else:
        html += "<p><em>No Epics are currently To Do or On Hold.</em></p>"

    html += "</body></html>"

    # --- SAVE ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if os.path.isabs(RESULT_FOLDER):
        save_dir = RESULT_FOLDER
    else:
        save_dir = os.path.normpath(os.path.join(script_dir, RESULT_FOLDER))

    os.makedirs(save_dir, exist_ok=True)

    # 1. Save the actual daily file
    target_filename = f"MV-NPU_Daily_Report_{today_str}.html"
    file_path = os.path.join(save_dir, target_filename)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    # 2. Create a folder named 'today'
    today_dir = os.path.join(save_dir, "today")
    os.makedirs(today_dir, exist_ok=True)
    
    # 3. Create an 'index.html' symlink inside the 'today' folder
    symlink_path = os.path.join(today_dir, "index.html")
    
    if os.path.exists(symlink_path) or os.path.islink(symlink_path):
        os.remove(symlink_path)
        
    os.symlink(f"../{target_filename}", symlink_path)
    
    print("-" * 60 + f"\n🏁 HTML Snapshot complete! Saved securely to:\n{file_path}")
    print(f"🔗 Clean URL active: /today -> {target_filename}")

if __name__ == "__main__":
    run_daily_snapshot()
