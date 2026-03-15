import html
import re
from datetime import datetime

import config
import github_client
import jira_client
import markdown
from jinja2 import Environment, FileSystemLoader


def get_status_badge(status_name):
    if not status_name:
        return ""
    s = status_name.lower()
    bg, text = "var(--badge-bg-default)", "var(--badge-text-default)"
    if s in ["done", "closed"]:
        bg, text = "var(--badge-bg-success)", "var(--badge-text-success)"
    elif s in ["in progress", "in review"]:
        bg, text = "var(--badge-bg-info)", "var(--badge-text-info)"
    elif s == "fixed/review":
        bg, text = "var(--badge-bg-purple)", "var(--badge-text-purple)"
    elif s == "blocked":
        bg, text = "var(--badge-bg-danger)", "var(--badge-text-danger)"
    elif s == "on hold":
        bg, text = "var(--badge-bg-warn)", "var(--badge-text-warn)"
    return f"<span class='status-badge' style='background: {bg}; color: {text};'>{status_name.upper()}</span>"


def parse_comment(html_text):
    text = re.sub(
        r"<(?:strong|b|em|i)[^>]*>\s*(Summary|Tags|Body)\s*</(?:strong|b|em|i)>\s*:",
        r"\1:",
        html_text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"<(?:strong|b|em|i)[^>]*>\s*(Summary|Tags|Body)\s*:\s*</(?:strong|b|em|i)>",
        r"\1:",
        text,
        flags=re.IGNORECASE,
    )

    sum_match = re.search(
        r"Summary:\s*(.*?)(?:<br[^>]*>|</p>|</div>|Tags:|Body:|$)", text, re.IGNORECASE
    )
    c_summary = (
        re.sub(r"<[^>]+>", "", sum_match.group(1)).strip() if sum_match else None
    )

    tags_match = re.search(
        r"Tags:\s*(.*?)(?:<br[^>]*>|</p>|</div>|Body:|$)", text, re.IGNORECASE
    )
    c_tags = re.sub(r"<[^>]+>", "", tags_match.group(1)).strip() if tags_match else ""
    tags_list = [t.strip() for t in c_tags.split(",") if t.strip()]

    if re.search(r"Body:", text, re.IGNORECASE):
        c_body = (
            re.search(
                r"Body:\s*(?:</p>|<br[^>]*>|</div>)?(.*)",
                text,
                re.IGNORECASE | re.DOTALL,
            )
            .group(1)
            .strip()
        )
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

    return c_summary, tags_list, c_body or "<em>No additional details provided.</em>"


def map_issue_data(issue, target_date_str):
    key = issue["key"]
    desc_html = (
        issue.get("renderedFields", {}).get("description")
        or "<em>No description provided.</em>"
    )

    # 🌟 NEW: Calculate a simple status color key for the templates
    status_name = issue["fields"].get("status", {}).get("name", "")
    status_raw = status_name.lower()
    if status_raw in ["done", "closed"]:
        status_key = "success"
    elif status_raw in ["in progress", "in review"]:
        status_key = "info"
    elif status_raw == "fixed/review":
        status_key = "purple"
    elif status_raw == "blocked":
        status_key = "danger"
    elif status_raw == "on hold":
        status_key = "warn"
    else:
        status_key = "default"

    target_comments, hist_comments = [], []
    for c in jira_client.fetch_comments(key):
        dt_vn = datetime.strptime(c["created"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(
            config.VN_TZ
        )
        c_sum, c_tags, c_body = parse_comment(c.get("renderedBody", ""))

        comment_obj = {
            "author": c["author"]["displayName"],
            "time_str": dt_vn.strftime("%b %d, %H:%M"),
            "summary": c_sum,
            "tags": c_tags,
            "body": c_body,
        }

        if dt_vn.strftime("%Y-%m-%d") == target_date_str:
            target_comments.append(comment_obj)
        elif dt_vn.strftime("%Y-%m-%d") < target_date_str:
            hist_comments.append(comment_obj)

    prs = []
    for pr in github_client.get_prs_for_issue(key):
        state = pr.get("state")
        state_str, text_color = (
            ("Merged", "var(--pr-merged)")
            if state == "closed" and pr.get("merged_at")
            else (
                ("Closed", "var(--pr-closed)")
                if state == "closed"
                else ("Open", "var(--pr-open)")
            )
        )
        clean_title = re.sub(
            r"\[?MV-\d+\]?\s*", "", pr.get("title", ""), flags=re.IGNORECASE
        ).strip()
        mergeable_state = pr.get("mergeable_state", "unknown")

        raw_body = pr.get("body") or "<em>No description provided.</em>"
        rendered_body = markdown.markdown(raw_body, extensions=["extra", "nl2br"])

        prs.append(
            {
                "url": pr.get("html_url"),
                "clean_title": clean_title,
                "author": pr.get("user", {}).get("login", "Unknown"),
                "state_str": state_str,
                "text_color": text_color,
                "changed_files": pr.get("changed_files", 0),
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "state_emoji": (
                    "⚠️"
                    if mergeable_state in ["dirty", "blocked", "unstable"]
                    else "✅"
                ),
                "mergeable_state": mergeable_state.capitalize(),
                "body": rendered_body,
            }
        )

    return {
        "key": key,
        "summary": issue["fields"]["summary"],
        "status_badge": get_status_badge(status_name),
        "status_key": status_key,
        "desc_html": desc_html,
        "updates": len(target_comments),
        "target_comments": target_comments,
        "hist_comments": hist_comments[-config.MAX_HISTORY_COMMENTS :],
        "prs": prs,
    }


def map_section_data(epics, tasks, target_date_str):
    emap = {}
    for e in epics:
        epic_data = map_issue_data(e, target_date_str)
        epic_data["tasks"] = []
        epic_data["epic_updates"] = 0
        emap[e["key"]] = epic_data

    emap["OTHER"] = {
        "key": "OTHER",
        "summary": "Standalone Issues (No Active Epic Parent)",
        "status_badge": "",
        "status_key": "default",
        "tasks": [],
        "epic_updates": 0,
    }

    for t in tasks:
        parent_key = t["fields"].get("parent", {}).get("key")
        task_data = map_issue_data(t, target_date_str)

        if parent_key and parent_key in emap:
            emap[parent_key]["tasks"].append(task_data)
            emap[parent_key]["epic_updates"] += task_data["updates"]
        else:
            emap["OTHER"]["tasks"].append(task_data)
            emap["OTHER"]["epic_updates"] += task_data["updates"]

    return [e for k, e in emap.items() if not (k == "OTHER" and not e["tasks"])]


def generate_report(
    today_str,
    yesterday_str,
    next_str,
    active_epics,
    active_tasks,
    yesterday_epics,
    yesterday_tasks,
    pending_epics,
):
    env = Environment(loader=FileSystemLoader(config.script_dir))
    template = env.get_template("report_template.html")

    context = {
        "domain": config.ATLASSIAN_DOMAIN,
        "today_str": today_str,
        "yesterday_str": yesterday_str,
        "next_str": next_str,
        "sections": [
            {
                "title": f"📅 Activity on {today_str}",
                "is_yesterday": False,
                "date_str": today_str,
                "epics": map_section_data(active_epics, active_tasks, today_str),
            },
            {
                "title": f"⏪ Previous Day ({yesterday_str})",
                "is_yesterday": True,
                "date_str": yesterday_str,
                "epics": map_section_data(
                    yesterday_epics, yesterday_tasks, yesterday_str
                ),
            },
        ],
        "pending_epics": [map_issue_data(e, today_str) for e in pending_epics],
    }

    return template.render(context)
