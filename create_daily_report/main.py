import argparse
import json
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

    def get_prev_workday(dt):
        if dt.weekday() == 0:  # Monday -> Friday
            return dt - timedelta(days=3)
        elif dt.weekday() == 6:  # Sunday -> Friday
            return dt - timedelta(days=2)
        return dt - timedelta(days=1)

    def get_next_workday(dt):
        if dt.weekday() == 4:  # Friday -> Monday
            return dt + timedelta(days=3)
        elif dt.weekday() == 5:  # Saturday -> Monday
            return dt + timedelta(days=2)
        return dt + timedelta(days=1)

    return (
        target.strftime("%Y-%m-%d"),
        get_prev_workday(target).strftime("%Y-%m-%d"),
        get_next_workday(target).strftime("%Y-%m-%d"),
    )


def run_daily_snapshot(target_user_date):
    today_str, yesterday_str, next_str = resolve_dates(target_user_date)
    print(
        f"🗓️  Generating JSON Snapshot | Target (Vietnam): {today_str} | Target Yesterday: {yesterday_str}\n"
        + "-" * 60
    )

    def build_history_jql(date_str, statuses):
        # A ticket belongs in the snapshot if it WAS IN the active statuses ON the date,
        # or if it was explicitly resolved ON the date.
        return f'{config.CORE_JQL} AND (status WAS IN ({statuses}) ON "{date_str}" OR status changed TO ("Done", "Closed") ON "{date_str}")'

    # 1. Fetch Jira Data using strict historical queries for BOTH today and yesterday
    active_epics = jira_client.fetch_issues(
        f"{build_history_jql(today_str, config.ACTIVE_STATUSES)} AND issuetype = Epic"
    )
    active_tasks = jira_client.fetch_issues(
        f"{build_history_jql(today_str, config.ACTIVE_STATUSES)} AND issuetype != Epic"
    )

    yesterday_epics = jira_client.fetch_issues(
        f"{build_history_jql(yesterday_str, config.ACTIVE_STATUSES)} AND issuetype = Epic"
    )
    yesterday_tasks = jira_client.fetch_issues(
        f"{build_history_jql(yesterday_str, config.ACTIVE_STATUSES)} AND issuetype != Epic"
    )

    pending_epics = jira_client.fetch_issues(
        f'{config.CORE_JQL} AND issuetype = Epic AND status WAS IN ({config.PENDING_STATUSES}) ON "{today_str}"'
    )
    # 2. Map GitHub PRs
    all_issues = (
        active_epics + active_tasks + yesterday_epics + yesterday_tasks + pending_epics
    )
    github_client.preload_github_prs(all_issues)

    # 3. Process & Build JSON Context
    context = html_generator.build_context(
        today_str,
        yesterday_str,
        next_str,
        active_epics,
        active_tasks,
        yesterday_epics,
        yesterday_tasks,
        pending_epics,
    )

    # 4. Save JSON File
    if os.path.isabs(config.RESULT_FOLDER):
        save_dir = config.RESULT_FOLDER
    else:
        save_dir = os.path.normpath(
            os.path.join(config.script_dir, config.RESULT_FOLDER)
        )
    os.makedirs(save_dir, exist_ok=True)

    target_filename = f"{today_str}.json"
    file_path = os.path.join(save_dir, target_filename)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

    print("-" * 60 + f"\n🏁 JSON Snapshot complete! Saved securely to:\n{file_path}")


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
