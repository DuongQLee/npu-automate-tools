import html
import re
from datetime import datetime, timezone

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


def calculate_days_ago(date_str, is_github=False):
    if not date_str:
        return 0
    try:
        if is_github:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        else:
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f%z")
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 0


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
    fields = issue.get("fields", {})
    desc_html = (
        issue.get("renderedFields", {}).get("description")
        or "<em>No description provided.</em>"
    )

    status_name = fields.get("status", {}).get("name", "")
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
        status_key = "todo"

    assignee = fields.get("assignee")
    assignee_name = assignee["displayName"] if assignee else "Unassigned"
    assignee_avatar = (
        assignee.get("avatarUrls", {}).get("48x48", "") if assignee else ""
    )
    priority = fields.get("priority", {}).get("name", "")

    created_at = fields.get("created")
    updated_at = fields.get("updated")

    cycle_days = max(1, calculate_days_ago(created_at))
    is_blocker = status_key == "danger" or priority in ["Highest", "High"]

    target_comments, hist_comments = [], []
    for c in jira_client.fetch_comments(key):
        dt_vn = datetime.strptime(c["created"], "%Y-%m-%dT%H:%M:%S.%f%z").astimezone(
            config.VN_TZ
        )
        c_sum, c_tags, c_body = parse_comment(c.get("renderedBody", ""))
        avatar_url = c.get("author", {}).get("avatarUrls", {}).get("48x48", "")

        comment_obj = {
            "author": c["author"]["displayName"],
            "avatar_url": avatar_url,
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
    pr_is_active = False

    for pr in github_client.get_prs_for_issue(key):
        state = pr.get("state")
        merged_at = pr.get("merged_at")
        pr_updated_at = pr.get(
            "updated_at"
        )  # Auto-bumps on GitHub for commits, comments, reviews
        closed_at = pr.get("closed_at")
        pr_created_at = pr.get("created_at")
        is_draft = pr.get("draft", False)

        pr_stale = (
            calculate_days_ago(pr_updated_at, is_github=True) >= 3 and state == "open"
        )
        if state == "open" and not pr_stale:
            pr_is_active = True

        if state == "closed" and merged_at:
            state_str, text_color, icon = "Merged", "var(--pr-merged)", "icon-git-merge"
            ts = datetime.strptime(merged_at, "%Y-%m-%dT%H:%M:%SZ").strftime(
                "%b %d, %H:%M"
            )
            time_str = f"Merged {ts}"
            cycle = max(
                1,
                (
                    datetime.strptime(merged_at, "%Y-%m-%dT%H:%M:%SZ")
                    - datetime.strptime(pr_created_at, "%Y-%m-%dT%H:%M:%SZ")
                ).days,
            )
        elif state == "closed":
            state_str, text_color, icon = "Closed", "var(--pr-closed)", "icon-git-pr"
            ts = datetime.strptime(
                closed_at or pr_updated_at, "%Y-%m-%dT%H:%M:%SZ"
            ).strftime("%b %d, %H:%M")
            time_str = f"Closed {ts}"
            cycle = max(1, calculate_days_ago(pr_created_at, is_github=True))
        else:
            state_str, text_color, icon = (
                "Draft" if is_draft else "Open",
                "var(--text-muted)" if is_draft else "var(--pr-open)",
                "icon-git-pr",
            )
            ts = datetime.strptime(pr_updated_at, "%Y-%m-%dT%H:%M:%SZ").strftime(
                "%b %d, %H:%M"
            )
            time_str = f"Updated {ts}"
            cycle = max(1, calculate_days_ago(pr_created_at, is_github=True))

        pr_review_alert = (
            state == "open"
            and not is_draft
            and calculate_days_ago(pr_created_at, is_github=True) >= 2
        )
        requested_reviewers = [r["login"] for r in pr.get("requested_reviewers", [])]

        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        total_lines = additions + deletions
        complexity_badge = (
            "🚨 Alert: Massive PR"
            if total_lines > 1000
            else ("⚠️ Warning: Large PR" if total_lines > 500 else "")
        )

        clean_title = re.sub(
            r"\[?MV-\d+\]?\s*", "", pr.get("title", ""), flags=re.IGNORECASE
        ).strip()
        raw_body = pr.get("body") or "<em>No description provided.</em>"

        prs.append(
            {
                "url": pr.get("html_url"),
                "clean_title": clean_title,
                "author": pr.get("user", {}).get("login", "Unknown"),
                "avatar_url": pr.get("user", {}).get("avatar_url", ""),
                "state_str": state_str,
                "text_color": text_color,
                "icon": icon,
                "additions": additions,
                "deletions": deletions,
                "time_str": time_str,
                "cycle_days": cycle,
                "is_draft": is_draft,
                "pr_stale": pr_stale,
                "pr_review_alert": pr_review_alert,
                "requested_reviewers": requested_reviewers,
                "complexity_badge": complexity_badge,
                "body": markdown.markdown(raw_body, extensions=["extra", "nl2br"]),
            }
        )

    # Issue staleness relies on Jira updates OR active PRs
    is_stale = (
        calculate_days_ago(updated_at) >= 3
        and not pr_is_active
        and len(target_comments) == 0
        and status_key in ["info", "todo", "purple"]
    )

    return {
        "key": key,
        "summary": issue["fields"]["summary"],
        "status_badge": get_status_badge(status_name),
        "status_key": status_key,
        "assignee": assignee_name,
        "assignee_avatar": assignee_avatar,
        "is_stale": is_stale,
        "cycle_days": cycle_days,
        "is_blocker": is_blocker,
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
        "status_key": "todo",
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

    for epic_data in emap.values():
        if epic_data["key"] == "OTHER":
            continue
        has_active_task = any(not t["is_stale"] for t in epic_data["tasks"])
        if epic_data["epic_updates"] > 0 or has_active_task:
            epic_data["is_stale"] = False

    return [e for k, e in emap.items() if not (k == "OTHER" and not e["tasks"])]


def calculate_metrics(epics):
    metrics = {
        "tasks_updated": 0,
        "comments_added": 0,
        "prs_merged": 0,
        "prs_open": 0,
        "stale_items": 0,
        "workload": {},
    }
    for e in epics:
        if e.get("is_stale"):
            metrics["stale_items"] += 1

        for t in e.get("tasks", []):
            if t["updates"] > 0:
                metrics["tasks_updated"] += 1
            metrics["comments_added"] += t["updates"]

            if t.get("is_stale"):
                metrics["stale_items"] += 1

            assignee = t.get("assignee", "Unassigned")
            assignee_avatar = t.get("assignee_avatar", "")

            if assignee not in metrics["workload"]:
                metrics["workload"][assignee] = {
                    "active": 0,
                    "prs_open": 0,
                    "prs_merged": 0,
                    "comments": 0,
                    "has_stale": False,
                    "avatar_url": assignee_avatar,
                }

            if t["status_key"] in ["info", "purple"]:
                metrics["workload"][assignee]["active"] += 1

            metrics["workload"][assignee]["comments"] += t["updates"]

            if t.get("is_stale"):
                metrics["workload"][assignee]["has_stale"] = True

            for pr in t.get("prs", []):
                if pr.get("pr_stale"):
                    metrics["stale_items"] += 1
                    metrics["workload"][assignee]["has_stale"] = True

                if pr["state_str"] == "Merged":
                    metrics["prs_merged"] += 1
                    metrics["workload"][assignee]["prs_merged"] += 1
                elif pr["state_str"] == "Open":
                    metrics["prs_open"] += 1
                    metrics["workload"][assignee]["prs_open"] += 1

    return metrics


def extract_blockers(data_sections):
    blockers = {}
    for section in data_sections:
        if section.get("is_blocker"):
            blockers[section["key"]] = section
        for t in section.get("tasks", []):
            if t.get("is_blocker"):
                blockers[t["key"]] = t
    return list(blockers.values())


def build_context(
    today_str,
    yesterday_str,
    next_str,
    active_epics,
    active_tasks,
    yesterday_epics,
    yesterday_tasks,
    pending_epics,
):
    today_data = map_section_data(active_epics, active_tasks, today_str)
    yesterday_data = map_section_data(yesterday_epics, yesterday_tasks, yesterday_str)

    active_blockers = extract_blockers(today_data + yesterday_data)

    context = {
        "domain": config.ATLASSIAN_DOMAIN,
        "today_str": today_str,
        "yesterday_str": yesterday_str,
        "next_str": next_str,
        "generation_time_iso": datetime.now(config.VN_TZ).isoformat(),
        "today_metrics": calculate_metrics(today_data),
        "yesterday_metrics": calculate_metrics(yesterday_data),
        "active_blockers": active_blockers,
        "sections": [
            {
                "title": f"📅 Activity on {today_str}",
                "is_yesterday": False,
                "date_str": today_str,
                "epics": today_data,
            },
            {
                "title": f"⏪ Previous Day ({yesterday_str})",
                "is_yesterday": True,
                "date_str": yesterday_str,
                "epics": yesterday_data,
            },
        ],
        "pending_epics": [map_issue_data(e, today_str) for e in pending_epics],
    }
    return context


def render_html(context):
    env = Environment(loader=FileSystemLoader(config.script_dir))
    template = env.get_template("report_template.html")
    return template.render(context)
