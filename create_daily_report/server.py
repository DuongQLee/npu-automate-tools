import http.server
import json
import os
import socketserver
import subprocess

import config

PORT = 8000
DIRECTORY = config.RESULT_FOLDER


class ReportHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_POST(self):
        if self.path == "/api/refresh":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            target_date = data.get("date")
            print(f"🔄 Browser requested live refresh for date: {target_date}")

            try:
                # Safely call the actual UV command on the VM using absolute paths
                main_script = os.path.join(config.script_dir, "main.py")

                subprocess.run(
                    ["uv", "run", main_script, "--date", target_date],
                    check=True,
                    cwd=config.repo_root,  # Forces execution from the repo root
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
        print(f"🚀 Serving Daily Reports UI at http://localhost:{PORT}")
        print(f"🔄 Live API Engine listening at http://localhost:{PORT}/api/refresh")
        httpd.serve_forever()


# ==============================================================================
# 🛠️ SYSTEMD SERVICE DEPLOYMENT GUIDE FOR ROCKY 9 (SELINUX FIXES)
# ==============================================================================
"""
To run this server professionally in the background on Rocky 9 and avoid 203/EXEC 
permission errors caused by SELinux, follow these exact steps:

STEP 1: Fix Ownership & Permissions
-----------------------------------
Run these commands in your VM terminal to ensure the system can execute your virtual environment:

# Ensure the moreh user owns the entire repository and virtual environment
sudo chown -R moreh:moreh /home/moreh/npu-automate-tools

# Ensure the python binary is explicitly marked as executable
sudo chmod +x /home/moreh/npu-automate-tools/.venv/bin/python

# Fix SELinux contexts (allows systemd to execute binaries in the home directory)
sudo chcon -Rt bin_t /home/moreh/npu-automate-tools/.venv/bin/


STEP 2: Update the Systemd Service File
---------------------------------------
Run: sudo nvim /etc/systemd/system/daily-report.service

Paste the following configuration:

[Unit]
Description=Daily Report Live Refresh Server
After=network.target

[Service]
Type=simple
User=moreh
WorkingDirectory=/home/moreh/npu-automate-tools

# 🌟 We use bash to wrap the execution, bypassing strict SELinux direct-execution blocks
ExecStart=/bin/bash -c '/home/moreh/npu-automate-tools/.venv/bin/python create_daily_report/server.py'

Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target


STEP 3: Reload and Start
------------------------------------
Apply the changes and start the server:

sudo systemctl daemon-reload
sudo systemctl restart daily-report.service
sudo systemctl status daily-report.service  # It should now say "active (running)"
"""
