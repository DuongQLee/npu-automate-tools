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
        "generation_time_iso": datetime.now(
            config.VN_TZ
        ).isoformat(),  # 🌟 NEW: Added exact build time
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
