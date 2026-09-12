from dataclasses import dataclass
import httpx
from .config import settings
from .security import parse_github_url

@dataclass
class Repository:
    owner: str
    name: str
    ref: str
    url: str
    description: str
    default_branch: str
    archive_url: str

class GitHubService:
    def __init__(self) -> None:
        self.headers = {"Accept": "application/vnd.github+json", "User-Agent": "GitHub-Repo-Analyzer"}
        if settings.github_token:
            self.headers["Authorization"] = f"Bearer {settings.github_token}"

    async def validate(self, url: str) -> Repository:
        parsed = parse_github_url(url)
        endpoint = f"https://api.github.com/repos/{parsed['owner']}/{parsed['name']}"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(endpoint, headers=self.headers)
        if response.status_code == 404:
            raise ValueError("Repository not found or not public.")
        if response.status_code in {401, 403}:
            raise ValueError("GitHub rejected the request. Try again later or configure GITHUB_TOKEN.")
        response.raise_for_status()
        data = response.json()
        if data.get("private"):
            raise ValueError("Private repositories are not supported.")
        ref = parsed["ref"] or data.get("default_branch", "main")
        return Repository(parsed["owner"], parsed["name"], ref, data["html_url"], data.get("description") or "No description provided.", data.get("default_branch", "main"), f"https://api.github.com/repos/{parsed['owner']}/{parsed['name']}/tarball/{ref}")

    async def download_archive(self, repository: Repository, target) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            async with client.stream("GET", repository.archive_url, headers=self.headers) as response:
                response.raise_for_status()
                with target.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 64):
                        total += len(chunk)
                        if total > settings.max_repository_bytes:
                            raise ValueError("Repository archive exceeds the configured size limit.")
                        output.write(chunk)
