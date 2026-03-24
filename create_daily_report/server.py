import http.server
import json
import os
import re
import socketserver
import subprocess
from datetime import datetime

import config
import html_generator

PORT = 8000
DIRECTORY = config.RESULT_FOLDER


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        path = self.path.strip("/")

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
            except Exception as e:
                self.send_response(500)
                self.end_headers()
            return

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

        if path.startswith("api/month/"):
            month_prefix = path.split("/")[-1]
            files = [
                f
                for f in os.listdir(DIRECTORY)
                if f.startswith(month_prefix) and f.endswith(".json")
            ]
            files.sort()

            month_data = []
            total_prs_merged = 0
            total_cycle_days = 0
            closed_ticket_count = 0
            seen_done_tickets = set()

            trend_dates = []
            trend_prs_merged = []
            trend_prs_opened = []
            trend_tickets_closed = []

            for f in files:
                with open(os.path.join(DIRECTORY, f), "r", encoding="utf-8") as jf:
                    try:
                        data = json.load(jf)
                    except:
                        continue

                    day_date = data.get("today_str")
                    today_metrics = data.get("today_metrics", {})

                    day_prs_merged = today_metrics.get("prs_merged", 0)
                    day_prs_opened = today_metrics.get("prs_open", 0)
                    total_prs_merged += day_prs_merged

                    active, done = [], []
                    day_tickets_closed = 0

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
                                }
                                if epic.get("status_key") == "success":
                                    done.append(item)
                                    if epic["key"] not in seen_done_tickets:
                                        seen_done_tickets.add(epic["key"])
                                        day_tickets_closed += 1
                                        total_cycle_days += epic.get("cycle_days", 1)
                                        closed_ticket_count += 1
                                else:
                                    active.append(item)

                            for task in epic.get("tasks", []):
                                item = {
                                    "key": task["key"],
                                    "summary": task["summary"],
                                    "type": "Task",
                                }
                                if task.get("status_key") == "success":
                                    done.append(item)
                                    if task["key"] not in seen_done_tickets:
                                        seen_done_tickets.add(task["key"])
                                        day_tickets_closed += 1
                                        total_cycle_days += task.get("cycle_days", 1)
                                        closed_ticket_count += 1
                                else:
                                    active.append(item)

                    month_data.append(
                        {"date": day_date, "active": active, "done": done}
                    )
                    trend_dates.append(
                        day_date[-2:]
                    )  # Just keep the 'DD' for the chart x-axis
                    trend_prs_merged.append(day_prs_merged)
                    trend_prs_opened.append(day_prs_opened)
                    trend_tickets_closed.append(day_tickets_closed)

            avg_cycle_time = (
                round(total_cycle_days / closed_ticket_count, 1)
                if closed_ticket_count > 0
                else 0
            )

            response_data = {
                "rollup": {
                    "total_prs_merged": total_prs_merged,
                    "avg_cycle_time": avg_cycle_time,
                    "total_tickets_closed": closed_ticket_count,
                },
                "trends": {
                    "dates": trend_dates,
                    "prs_merged": trend_prs_merged,
                    "prs_opened": trend_prs_opened,
                    "tickets_closed": trend_tickets_closed,
                },
                "days": month_data,
            }

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
            return

        # 1. Intercept /today or root requests
        if path == "" or path == "today":
            target_date = datetime.now(config.VN_TZ).strftime("%Y-%m-%d")
        else:
            # 2. Extract date for clean URLs (e.g., localhost:8000/2026-03-20)
            match = re.search(r"(\d{4}-\d{2}-\d{2})", path)
            if match:
                target_date = match.group(1)
            else:
                # Let standard handler serve it (for static assets)
                return super().do_GET()

        # Look for the simplified JSON filename
        json_filename = f"{target_date}.json"
        json_path = os.path.join(DIRECTORY, json_filename)

        if os.path.exists(json_path):
            # 3. Read the stored API data and generate HTML dynamically
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
