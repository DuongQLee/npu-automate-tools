import re
import time
import urllib.parse

import config
import requests

GLOBAL_PR_MAP = {}


def preload_github_prs(all_issues):
    global GLOBAL_PR_MAP
    if not config.GITHUB_TOKEN or not config.GITHUB_REPO:
        print("⚠️ GitHub Token/Repo missing. Skipping PR integration.")
        return

    unique_keys = list(set([issue["key"] for issue in all_issues]))
    if not unique_keys:
        return

    print(f"🐙 Searching GitHub for {len(unique_keys)} linked Jira tickets...")
    gh_headers = {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    search_url = "https://api.github.com/search/issues"

    for i in range(0, len(unique_keys), 5):
        chunk = unique_keys[i : i + 5]
        query_str = " OR ".join([f'"{k}"' for k in chunk])
        params = {"q": f"repo:{config.GITHUB_REPO} is:pr {query_str}", "per_page": 100}

        if config.DEBUG:
            full_search_url = f"{search_url}?{urllib.parse.urlencode(params)}"
            print(f"[DEBUG] GET: {full_search_url}")

        res = requests.get(search_url, headers=gh_headers, params=params)

        if res.status_code == 403:
            print("⚠️ GitHub Rate Limit. Pausing 3 seconds...")
            time.sleep(3)

            if config.DEBUG:
                print(f"[DEBUG] GET (Retry): {full_search_url}")

            res = requests.get(search_url, headers=gh_headers, params=params)

        if res.status_code == 200:
            for item in res.json().get("items", []):
                pr_url = item.get("pull_request", {}).get("url")
                if not pr_url:
                    continue

                if config.DEBUG:
                    print(f"[DEBUG] GET: {pr_url}")

                pr_res = requests.get(pr_url, headers=gh_headers)
                if pr_res.status_code == 200:
                    pr_data = pr_res.json()
                    reviews_url = f"{pr_url}/reviews"

                    if config.DEBUG:
                        print(f"[DEBUG] GET: {reviews_url}")

                    reviews_res = requests.get(reviews_url, headers=gh_headers)
                    if reviews_res.status_code == 200:
                        pr_data["reviews"] = reviews_res.json()
                    else:
                        pr_data["reviews"] = []
                    search_text = f"{pr_data.get('title','')} {pr_data.get('body','')} {pr_data.get('head',{}).get('ref','')}"
                    matches = set(re.findall(r"(MV-\d+)", search_text, re.IGNORECASE))

                    for match in matches:
                        key = match.upper()
                        if key in chunk:
                            if key not in GLOBAL_PR_MAP:
                                GLOBAL_PR_MAP[key] = []
                            if not any(
                                p["id"] == pr_data["id"] for p in GLOBAL_PR_MAP[key]
                            ):
                                GLOBAL_PR_MAP[key].append(pr_data)
        time.sleep(0.5)


def get_prs_for_issue(issue_key):
    return GLOBAL_PR_MAP.get(issue_key, [])
