import argparse
import os
from datetime import datetime, timedelta

import config
import github_client
import html_generator
import jira_client


def resolve_dates(user_date):
    if user_date is None:
        target = datetime.now(config.VN_TZ)
    elif isinstance(user_date, int):
        target = datetime.now(config.VN_TZ) + timedelta(days=user_date)
    elif isinstance(user_date, str):
        target = datetime.strptime(user_date, "%Y-%m-%d").replace(tzinfo=config.VN_TZ)
    else:
        raise ValueError("Invalid DATE format.")

    return (
        target.strftime("%Y-%m-%d"),
        (target - timedelta(days=1)).strftime("%Y-%m-%d"),
        (target + timedelta(days=1)).strftime("%Y-%m-%d"),
    )


def run_daily_snapshot(target_user_date):
    today_str, yesterday_str, next_str = resolve_dates(target_user_date)
    print(
        f"🗓️  Generating HTML Snapshot | Target (Vietnam): {today_str} | Target Yesterday (Vietnam): {yesterday_str}\n"
        + "-" * 60
    )

    actual_system_today = datetime.now(config.VN_TZ).strftime("%Y-%m-%d")
    is_actual_today = today_str == actual_system_today
    done_jql_today = f'(status changed to "Done" on "{today_str}" OR status changed to "Closed" on "{today_str}")'

    # 1. Fetch Jira Data
    active_epics = jira_client.fetch_issues(
        f"{config.CORE_JQL} AND issuetype = Epic AND (status IN ({config.ACTIVE_STATUSES}) OR {done_jql_today})"
    )
    active_tasks = jira_client.fetch_issues(
        f"{config.CORE_JQL} AND issuetype != Epic AND (status IN ({config.ACTIVE_STATUSES}) OR {done_jql_today})"
    )
    yesterday_epics = jira_client.fetch_issues(
        f'{config.CORE_JQL} AND issuetype = Epic AND status WAS IN ({config.ACTIVE_STATUSES}) ON "{yesterday_str}"'
    )
    yesterday_tasks = jira_client.fetch_issues(
        f'{config.CORE_JQL} AND issuetype != Epic AND status WAS IN ({config.ACTIVE_STATUSES}) ON "{yesterday_str}"'
    )
    pending_epics = jira_client.fetch_issues(
        f"{config.CORE_JQL} AND issuetype = Epic AND status IN ({config.PENDING_STATUSES})"
    )

    # 2. Map GitHub PRs
    all_issues = (
        active_epics + active_tasks + yesterday_epics + yesterday_tasks + pending_epics
    )
    github_client.preload_github_prs(all_issues)

    # 3. Process & Render HTML via Jinja2
    html = html_generator.generate_report(
        today_str,
        yesterday_str,
        next_str,
        active_epics,
        active_tasks,
        yesterday_epics,
        yesterday_tasks,
        pending_epics,
    )

    # 4. Save File
    if os.path.isabs(config.RESULT_FOLDER):
        save_dir = config.RESULT_FOLDER
    else:
        save_dir = os.path.normpath(
            os.path.join(config.script_dir, config.RESULT_FOLDER)
        )
    os.makedirs(save_dir, exist_ok=True)

    target_filename = f"MV-NPU_Daily_Report_{today_str}.html"
    file_path = os.path.join(save_dir, target_filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)

    print("-" * 60 + f"\n🏁 HTML Snapshot complete! Saved securely to:\n{file_path}")

    # 5. Update /today symlink
    if is_actual_today:
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
    parser = argparse.ArgumentParser(description="Jira Daily Report Generator")
    parser.add_argument(
        "-d",
        "--date",
        nargs="*",
        default=None,
        help="Dates to process: 0, -1, YYYY-MM-DD",
    )
    args = parser.parse_args()

    jira_client.verify_authentication()
    raw_dates = args.date if args.date else [None]
    processed_date_strings = set()

    for d in raw_dates:
        if d is not None:
            try:
                d = int(d)
            except ValueError:
                pass

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
