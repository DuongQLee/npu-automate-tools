import http.server
import json
import os
import re
import socketserver
import subprocess
from datetime import datetime, timezone

import config
import html_generator

PORT = 8000
DIRECTORY = config.RESULT_FOLDER


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        path = self.path.strip("/")

        # --- API: AVAILABLE DATES ---
        if path == "api/available_dates":
            try:
                files = [
                    f.replace(".json", "")
                    for f in os.listdir(DIRECTORY)
                    if f.endswith(".json")
                ]
                files.sort(reverse=True)
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(files).encode("utf-8"))
            except Exception:
                self.send_response(500)
                self.end_headers()
            return

        # --- VIEW: MONTHLY TIMELINE HTML ---
        if path.startswith("month/"):
            month_prefix = path.split("/")[-1]
            template_path = os.path.join(config.script_dir, "monthly_template.html")
            if os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8") as f:
                    html_content = f.read().replace("{{ month_str }}", month_prefix)
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html_content.encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(
                    b"<h1>Error</h1><p>monthly_template.html not found.</p>"
                )
            return

        # --- API: MONTHLY TIMELINE DATA ---
        if path.startswith("api/month/"):
            month_prefix = path.split("/")[-1]
            files = [
                f
                for f in os.listdir(DIRECTORY)
                if f.startswith(month_prefix) and f.endswith(".json")
            ]
            files.sort()

            month_data = []

            # Master Aggregators
            total_prs_merged = 0
            total_pr_size = 0
            unique_authors = set()
            total_pickup_hours = 0
            pickup_count = 0
            total_review_hours = 0
            review_count = 0
            total_pr_cycle_days = 0
            merged_pr_count = 0
            total_cycle_days = 0
            closed_ticket_count = 0

            seen_done_tickets = set()
            seen_closed_prs = set()

            trend_dates = []
            trend_prs_merged = []
            trend_prs_opened = []
            trend_pr_cycle_time = []

            for f in files:
                with open(os.path.join(DIRECTORY, f), "r", encoding="utf-8") as jf:
                    try:
                        data = json.load(jf)
                    except Exception:
                        continue

                    day_date = data.get("today_str")
                    today_metrics = data.get("today_metrics", {})

                    day_prs_merged = today_metrics.get("prs_merged", 0)
                    day_prs_opened = today_metrics.get("prs_open", 0)

                    active, done = [], []
                    day_prs_closed_tracked = 0
                    day_pr_cycle_sum = 0
                    day_tickets_closed = 0
                    day_cycle_sum = 0

                    today_section = next(
                        (
                            s
                            for s in data.get("sections", [])
                            if not s.get("is_yesterday")
                        ),
                        None,
                    )

                    if today_section:
                        for epic in today_section.get("epics", []):
                            if epic["key"] != "OTHER":
                                item = {
                                    "key": epic["key"],
                                    "summary": epic["summary"],
                                    "type": "Epic",
                                    "status_key": epic.get("status_key"),
                                    "desc_html": epic.get("desc_html", ""),
                                    "target_comments": epic.get("target_comments", []),
                                    "prs": epic.get("prs", []),
                                }
                                if epic.get("status_key") == "success":
                                    done.append(item)
                                    if epic["key"] not in seen_done_tickets:
                                        seen_done_tickets.add(epic["key"])
                                        day_tickets_closed += 1
                                        total_cycle_days += epic.get("cycle_days", 1)
                                        closed_ticket_count += 1
                                        day_cycle_sum += epic.get("cycle_days", 1)
                                else:
                                    active.append(item)

                            for task in epic.get("tasks", []):
                                item = {
                                    "key": task["key"],
                                    "summary": task["summary"],
                                    "type": "Task",
                                    "status_key": task.get("status_key"),
                                    "desc_html": task.get("desc_html", ""),
                                    "target_comments": task.get("target_comments", []),
                                    "prs": task.get("prs", []),
                                }
                                if task.get("status_key") == "success":
                                    done.append(item)
                                    if task["key"] not in seen_done_tickets:
                                        seen_done_tickets.add(task["key"])
                                        day_tickets_closed += 1
                                        total_cycle_days += task.get("cycle_days", 1)
                                        closed_ticket_count += 1
                                        day_cycle_sum += task.get("cycle_days", 1)
                                else:
                                    active.append(item)

                                for pr in task.get("prs", []):
                                    if pr.get("state_str") == "Merged":
                                        pr_url = pr.get("url")
                                        if pr_url and pr_url not in seen_closed_prs:
                                            seen_closed_prs.add(pr_url)
                                            total_prs_merged += 1
                                            day_prs_closed_tracked += 1
                                            total_pr_size += pr.get(
                                                "additions", 0
                                            ) + pr.get("deletions", 0)

                                            author = pr.get("author")
                                            if author and author != "Unknown":
                                                unique_authors.add(author)

                                            c_raw = pr.get("raw_created_at")
                                            m_raw = pr.get("raw_merged_at")
                                            r_raw = pr.get("raw_first_review_at")

                                            def to_dt(s):
                                                if not s:
                                                    return None
                                                return datetime.strptime(
                                                    s, "%Y-%m-%dT%H:%M:%SZ"
                                                ).replace(tzinfo=timezone.utc)

                                            c_dt, m_dt, r_dt = (
                                                to_dt(c_raw),
                                                to_dt(m_raw),
                                                to_dt(r_raw),
                                            )

                                            if c_dt and m_dt:
                                                cycle_d = (
                                                    m_dt - c_dt
                                                ).total_seconds() / 86400.0
                                                total_pr_cycle_days += cycle_d
                                                day_pr_cycle_sum += cycle_d
                                                merged_pr_count += 1

                                            if c_dt and r_dt:
                                                pickup_h = (
                                                    r_dt - c_dt
                                                ).total_seconds() / 3600.0
                                                if pickup_h >= 0:
                                                    total_pickup_hours += pickup_h
                                                    pickup_count += 1

                                            if r_dt and m_dt:
                                                review_h = (
                                                    m_dt - r_dt
                                                ).total_seconds() / 3600.0
                                                if review_h >= 0:
                                                    total_review_hours += review_h
                                                    review_count += 1

                    month_data.append(
                        {"date": day_date, "active": active, "done": done}
                    )
                    if day_date:
                        trend_dates.append(day_date[-2:])
                    trend_prs_merged.append(day_prs_merged)
                    trend_prs_opened.append(day_prs_opened)
                    trend_pr_cycle_time.append(
                        round(day_pr_cycle_sum / day_prs_closed_tracked, 1)
                        if day_prs_closed_tracked > 0
                        else None
                    )

            # --- CALCULATIONS: ELITE MONTHLY AVERAGES ---
            active_devs = len(unique_authors) if len(unique_authors) > 0 else 1
            working_weeks = max(1.0, len(files) / 5.0)

            response_data = {
                "rollup": {
                    "merge_frequency": round(
                        total_prs_merged / active_devs / working_weeks, 1
                    ),
                    "pr_size": (
                        round(total_pr_size / total_prs_merged)
                        if total_prs_merged > 0
                        else 0
                    ),
                    "cycle_time": (
                        round(total_pr_cycle_days / merged_pr_count, 1)
                        if merged_pr_count > 0
                        else 0
                    ),
                    "pickup_time": (
                        round(total_pickup_hours / pickup_count, 1)
                        if pickup_count > 0
                        else 0
                    ),
                    "review_time": (
                        round(total_review_hours / review_count, 1)
                        if review_count > 0
                        else 0
                    ),
                },
                "trends": {
                    "dates": trend_dates,
                    "prs_merged": trend_prs_merged,
                    "prs_opened": trend_prs_opened,
                    "pr_cycle_time": trend_pr_cycle_time,
                },
                "days": month_data,
            }

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
            return

        # --- VIEW: DAILY HTML PAGE ---
        if path == "" or path == "today":
            target_date = datetime.now(config.VN_TZ).strftime("%Y-%m-%d")
        else:
            match = re.search(r"(\d{4}-\d{2}-\d{2})", path)
            if match:
                target_date = match.group(1)
            else:
                return super().do_GET()

        json_filename = f"{target_date}.json"
        json_path = os.path.join(DIRECTORY, json_filename)

        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                context = json.load(f)

            html_output = html_generator.render_html(context)
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_output.encode("utf-8"))
        else:
            self.send_response(404)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            error_html = f"<h1>404 Not Found</h1><p>No JSON API data found for {target_date}.</p>"
            self.wfile.write(error_html.encode("utf-8"))

    def do_POST(self):
        # --- API: LIVE REFRESH ---
        if self.path == "/api/refresh":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            target_date = data.get("date")
            print(f"🔄 Browser requested live refresh for date: {target_date}")

            try:
                python_bin = os.path.join(config.repo_root, ".venv", "bin", "python")
                main_script = os.path.join(config.script_dir, "main.py")

                subprocess.run(
                    [python_bin, main_script, "--date", target_date],
                    check=True,
                    cwd=config.repo_root,
                )

                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode("utf-8"))
            except Exception as e:
                print(f"❌ Error running refresh script: {e}")
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"status": "error", "message": str(e)}).encode("utf-8")
                )
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    os.makedirs(DIRECTORY, exist_ok=True)
    with socketserver.TCPServer(("", PORT), ReportHandler) as httpd:
        print(
            f"🚀 Serving Live Reports via JSON Engine at http://localhost:{PORT}/today"
        )
        httpd.serve_forever()
