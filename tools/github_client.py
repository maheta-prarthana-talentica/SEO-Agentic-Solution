"""GitHub client wrapper (Section 6). Thin httpx REST client.
Never merges PRs — merge is always a human action.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

API = "https://api.github.com"


@dataclass
class PRResult:
    branch_name: str
    pr_url: str | None
    pr_number: int | None
    commits: list[str]
    error: str | None = None


def normalize_github_token(token: str | None) -> str:
    """Strip whitespace / pasted 'Bearer '/'token ' prefixes so auth headers stay valid."""
    if not token:
        return ""
    t = token.strip().strip('"').strip("'")
    # Users sometimes paste the full Authorization value
    for prefix in ("Bearer ", "bearer ", "Token ", "token "):
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
    # Accidental newlines / zero-width chars from password managers
    t = re.sub(r"[\s\u200b\ufeff]+", "", t)
    return t


class GitHubClient:
    def __init__(self, token: str | None = None, repo: str | None = None) -> None:
        self.token = normalize_github_token(token or os.getenv("GITHUB_TOKEN") or "")
        self.repo = (repo or os.getenv("GITHUB_REPO") or "").strip().removesuffix(".git")
        self.bot = os.getenv("GITHUB_BOT_IDENTITY", "seo-agent-bot")
        self.enabled = bool(self.token and self.repo)

    def _headers(self) -> dict[str, str]:
        # GitHub accepts both schemes for PATs; Bearer is preferred for fine-grained tokens.
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self.bot,
        }

    def probe_access(self) -> str | None:
        """Return a human-readable auth/access error, or None if the token can see the repo."""
        if not self.enabled:
            return "GitHub token or repository was not configured."

        try:
            r = httpx.get(
                f"{API}/repos/{self.repo}",
                headers=self._headers(),
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            return f"Could not reach GitHub API: {exc}"

        if r.status_code == 200:
            return None
        return self._auth_error_message(r, action=f"access repo `{self.repo}`")

    def get_default_branch(self) -> str:
        if not self.enabled:
            return "main"
        r = httpx.get(f"{API}/repos/{self.repo}", headers=self._headers(), timeout=20.0)
        if r.status_code >= 400:
            raise PermissionError(self._auth_error_message(r, action=f"read repo `{self.repo}`"))
        return r.json().get("default_branch", "main")

    def get_ref_sha(self, branch: str) -> str:
        r = httpx.get(
            f"{API}/repos/{self.repo}/git/ref/heads/{branch}",
            headers=self._headers(),
            timeout=20.0,
        )
        if r.status_code >= 400:
            raise PermissionError(
                self._auth_error_message(r, action=f"read branch `{branch}` on `{self.repo}`")
            )
        return r.json()["object"]["sha"]

    def create_branch(self, branch_name: str, from_branch: str | None = None) -> str:
        from_branch = from_branch or self.get_default_branch()
        sha = self.get_ref_sha(from_branch)
        r = httpx.post(
            f"{API}/repos/{self.repo}/git/refs",
            headers=self._headers(),
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            timeout=20.0,
        )
        if r.status_code == 422 and "already exists" in r.text.lower():
            return branch_name
        if r.status_code >= 400:
            raise PermissionError(
                self._auth_error_message(
                    r, action=f"create branch `{branch_name}` on `{self.repo}`"
                )
            )
        return branch_name

    def commit_files(
        self,
        branch: str,
        files: dict[str, str],
        message: str,
    ) -> str:
        """Creates a commit on `branch` with the given path→content map.

        Uses the Contents API for simplicity (fine for POC-scale patches). Returns commit sha.
        """
        if not files:
            return ""
        last_sha = ""
        for path, content in files.items():
            get = httpx.get(
                f"{API}/repos/{self.repo}/contents/{path}",
                headers=self._headers(),
                params={"ref": branch},
                timeout=20.0,
            )
            payload: dict[str, Any] = {
                "message": message,
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": branch,
                "committer": {
                    "name": self.bot,
                    "email": f"{self.bot}@users.noreply.github.com",
                },
            }
            if get.status_code == 200:
                payload["sha"] = get.json()["sha"]
            put = httpx.put(
                f"{API}/repos/{self.repo}/contents/{path}",
                headers=self._headers(),
                json=payload,
                timeout=30.0,
            )
            if put.status_code >= 400:
                raise PermissionError(
                    self._auth_error_message(put, action=f"commit `{path}` on `{branch}`")
                )
            last_sha = put.json().get("commit", {}).get("sha", "")
        return last_sha

    def open_pr(self, branch: str, title: str, body: str, base: str | None = None) -> PRResult:
        base = base or self.get_default_branch()
        r = httpx.post(
            f"{API}/repos/{self.repo}/pulls",
            headers=self._headers(),
            json={"title": title, "head": branch, "base": base, "body": body},
            timeout=30.0,
        )
        if r.status_code >= 400:
            return PRResult(
                branch_name=branch,
                pr_url=None,
                pr_number=None,
                commits=[],
                error=self._auth_error_message(r, action=f"open PR from `{branch}`"),
            )
        data = r.json()
        try:
            httpx.post(
                f"{API}/repos/{self.repo}/issues/{data['number']}/labels",
                headers=self._headers(),
                json=["seo-agent", "auto-generated"],
                timeout=15.0,
            )
        except httpx.HTTPError:
            pass
        return PRResult(
            branch_name=branch,
            pr_url=data.get("html_url"),
            pr_number=data.get("number"),
            commits=[],
        )

    def get_pr_ci_status(self, pr_number: int) -> dict[str, Any]:
        """Surface CI status (FR-5.5) without auto-merging."""
        r = httpx.get(
            f"{API}/repos/{self.repo}/pulls/{pr_number}",
            headers=self._headers(),
            timeout=20.0,
        )
        r.raise_for_status()
        head_sha = r.json()["head"]["sha"]
        status = httpx.get(
            f"{API}/repos/{self.repo}/commits/{head_sha}/status",
            headers=self._headers(),
            timeout=20.0,
        )
        if status.status_code != 200:
            return {"state": "unknown", "statuses": []}
        data = status.json()
        return {"state": data.get("state"), "statuses": data.get("statuses", [])}

    @staticmethod
    def _auth_error_message(response: httpx.Response, *, action: str) -> str:
        code = response.status_code
        body = (response.text or "")[:300]
        if code == 401:
            return (
                f"GitHub 401 Unauthorized while trying to {action}. "
                "Your PAT is missing, expired, revoked, or was pasted incorrectly. "
                "Create a new fine-grained token for this repo with Contents (Read and write) "
                "and Pull requests (Read and write), then paste it again (do not reuse a "
                "token that was shared in chat)."
            )
        if code == 403:
            return (
                f"GitHub 403 Forbidden while trying to {action}. "
                "The token authenticated but lacks permission — grant Contents + Pull requests "
                f"write on this repository. Details: {body}"
            )
        if code == 404:
            return (
                f"GitHub 404 Not Found while trying to {action}. "
                "Repo name may be wrong, or the token cannot see a private repo "
                "(resource not granted to the fine-grained PAT)."
            )
        return f"GitHub HTTP {code} while trying to {action}: {body}"
