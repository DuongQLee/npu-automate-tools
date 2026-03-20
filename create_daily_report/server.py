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

        # 1. Intercept /today or root requests
        if path == "" or path == "today":
            target_date = datetime.now(config.VN_TZ).strftime("%Y-%m-%d")
        else:
            # 2. Extract date if they request a specific file (e.g. MV-NPU_Daily_Report_2026-03-20.html)
            match = re.search(r"(\d{4}-\d{2}-\d{2})", path)
            if match:
                target_date = match.group(1)
            else:
                # Let standard handler serve it (e.g. if you request a raw static asset)
                return super().do_GET()

        json_filename = f"MV-NPU_Daily_Report_{target_date}.json"
        json_path = os.path.join(DIRECTORY, json_filename)

        if os.path.exists(json_path):
            # 3. Read the stored API data and generate HTML dynamically!
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
            error_html = f"<h1>404 Not Found</h1><p>No JSON API data found for {target_date}. The cron job has not generated it yet.</p>"
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
