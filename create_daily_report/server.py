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
                # 🌟 Safely call the actual UV command on the VM using absolute paths
                # Leveraging your config.py to ensure the server knows exactly where it is
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
# 🛠️ SYSTEMD SERVICE DEPLOYMENT GUIDE FOR ROCKY 9
# ==============================================================================
"""
To run this server professionally in the background on Rocky 9, follow these steps. 
By creating a Systemd service, your server will automatically restart if the VM reboots or if the script crashes.

STEP 1: Find your absolute paths
--------------------------------
Run these commands in your VM's terminal and copy the outputs:
1. `which uv`       -> (e.g., /home/your_user/.local/bin/uv)
2. `pwd`            -> (Navigate to your repo root first! e.g., /home/your_user/your_repo)
3. `whoami`         -> (e.g., your_user)

STEP 2: Create the Systemd Service File
---------------------------------------
Run this command to create the file:
sudo nano /etc/systemd/system/daily-report.service

Paste the following configuration into nano (REPLACE THE PLACEHOLDERS with outputs from Step 1):

[Unit]
Description=Daily Report Live Refresh Server
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/home/your_user/your_repo
# ⚠️ Make sure to use the absolute path to 'uv' from Step 1!
ExecStart=/home/your_user/.local/bin/uv run server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target

(Save and exit nano: Press CTRL+O, Enter, then CTRL+X)

STEP 3: Enable and Start the Service
------------------------------------
Run these commands to tell Rocky 9 to use your new service:
sudo systemctl daemon-reload
sudo systemctl enable daily-report.service
sudo systemctl start daily-report.service
sudo systemctl status daily-report.service  # Check if it says "active (running)"!

STEP 4: Open Firewall Port (Rocky 9 Default)
--------------------------------------------
Rocky 9 uses firewalld by default. To allow access to port 8000 from outside the VM:
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload

Troubleshooting:
----------------
If the refresh button throws an error, you can check the live Python logs with:
sudo journalctl -u daily-report.service -f
"""
