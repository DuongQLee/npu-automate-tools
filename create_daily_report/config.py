import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(script_dir)

env_path = os.path.join(repo_root, ".env")
load_dotenv(env_path, override=True)

ATLASSIAN_DOMAIN = "moreh.atlassian.net"
ATLASSIAN_EMAIL = "duong.le@moreh.com.vn".strip()
ATLASSIAN_API_TOKEN = os.getenv("API_TOKEN", "").strip()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()

RESULT_FOLDER = os.getenv(
    "RESULT_FOLDER", os.path.join(repo_root, "mv-npu_daily_report")
)
MAX_HISTORY_COMMENTS = 100

CORE_JQL = 'component = "MV-NPU"'
ACTIVE_STATUSES = '"In Progress", "Fixed/Review", "Blocked", "BLOCKED"'
PENDING_STATUSES = '"Open", "OPEN", "To Do", "TODO", "On Hold", "ON HOLD"'

VN_TZ = timezone(timedelta(hours=7), name="ICT")
DEBUG = False
