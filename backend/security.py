import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

GITHUB_URL = re.compile(r"^github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:/tree/(?P<ref>[^/]+))?$")

def parse_github_url(value: str) -> dict[str, str]:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ValueError("Enter a valid public GitHub repository URL.")
    match = GITHUB_URL.match(parsed.netloc.lower() + parsed.path.rstrip("/"))
    if not match or parsed.query or parsed.fragment:
        raise ValueError("Use a URL like https://github.com/owner/repository.")
    data = match.groupdict()
    data["repo"] = data["repo"].removesuffix(".git")
    if not data["repo"]:
        raise ValueError("Repository name is required.")
    return {"owner": data["owner"], "name": data["repo"], "ref": data.get("ref") or ""}

def workspace_for(owner: str, name: str, ref: str = "") -> str:
    return hashlib.sha256(f"{owner}/{name}@{ref}".encode()).hexdigest()[:24]

def safe_join(root: Path, relative: str) -> Path:
    destination = (root / relative).resolve()
    root_resolved = root.resolve()
    if destination != root_resolved and root_resolved not in destination.parents:
        raise ValueError("Archive contains an unsafe path.")
    return destination
