"""
extractor/classify.py — Heuristic URL type and subject classifier.

Rules are keyword/domain-based — no LLM dependency.
Both functions return strings matching the DB enum values.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── Type classification ────────────────────────────────────────────────────────

_REPO_DOMAINS = {"github.com", "gitlab.com", "bitbucket.org", "codeberg.org"}
_VIDEO_DOMAINS = {"youtube.com", "youtu.be", "vimeo.com", "loom.com", "wistia.com"}
_SOCIAL_DOMAINS = {
    "twitter.com", "x.com", "linkedin.com", "reddit.com",
    "threads.net", "mastodon.social", "bsky.app",
}
_PKG_DOMAINS = {"pypi.org", "npmjs.com", "crates.io", "hex.pm", "packagist.org"}
_DOC_DOMAINS = {
    "docs.microsoft.com", "learn.microsoft.com", "developer.mozilla.org",
    "readthedocs.io", "readthedocs.org",
}
_RESEARCH_PATTERNS = re.compile(
    r"arxiv\.org|paper(?:s)?\.ssrn|openreview\.net|semanticscholar\.org"
    r"|dl\.acm\.org|ieeexplore\.ieee\.org|springer\.com/article"
    r"|nature\.com/articles|proceedings\.",
    re.IGNORECASE,
)
_TOOL_KEYWORDS = re.compile(
    r"\b(tool|cli|dashboard|playground|sandbox|ide|editor|builder|generator)\b",
    re.IGNORECASE,
)


def classify_type(url: str, title: str = "", description: str = "") -> str:
    """Return one of: repo, video, research, doc, package, article, social, tool, other."""
    parsed = urlparse(url.lower())
    domain = parsed.netloc.lstrip("www.")

    if domain in _REPO_DOMAINS:
        return "repo"
    if domain in _VIDEO_DOMAINS:
        return "video"
    if domain in _SOCIAL_DOMAINS:
        return "social"
    if domain in _PKG_DOMAINS:
        return "package"
    if any(domain.endswith(d) for d in _DOC_DOMAINS):
        return "doc"
    if _RESEARCH_PATTERNS.search(url):
        return "research"

    combined = f"{title} {description}".lower()
    if _TOOL_KEYWORDS.search(combined):
        return "tool"

    return "article"


# ── Subject classification ─────────────────────────────────────────────────────

_SUBJECT_PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "ai",
        re.compile(
            r"\b(ai|llm|gpt|claude|gemini|mistral|llama|machine.learning|deep.learning"
            r"|neural|transformer|generative|diffusion|embedding|rag|vector|semantic"
            r"|nlp|computer.vision|stable.diffusion|midjourney|openai|anthropic)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "benchmark",
        re.compile(
            r"\b(benchmark|evaluation|leaderboard|performance|metric|score|test|eval"
            r"|comparison|ranking|sota|state.of.the.art)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "power-platform",
        re.compile(
            r"\b(power.apps|power.automate|power.bi|power.pages|power.virtual.agents"
            r"|dataverse|dynamics.365|d365|copilot.studio|power.platform|canvas.app)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "azure",
        re.compile(
            r"\b(azure|microsoft.cloud|azure.devops|ado|azure.openai|azure.ai"
            r"|azure.functions|azure.logic.apps|bicep|arm.template)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "dev-tools",
        re.compile(
            r"\b(vscode|cursor|copilot|neovim|git|github.actions|ci.cd|devops"
            r"|docker|kubernetes|k8s|helm|terraform|pulumi|ansible|cli.tool)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "infra",
        re.compile(
            r"\b(linux|server|nginx|caddy|traefik|selfhost|self.host|vps|homelab"
            r"|networking|firewall|vpn|tailscale|wireguard|reverse.proxy)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "web-dev",
        re.compile(
            r"\b(react|nextjs|next\.js|vue|svelte|astro|typescript|javascript"
            r"|tailwind|css|html|frontend|fullstack|web.framework|rest.api|graphql)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data",
        re.compile(
            r"\b(data.engineering|dbt|airflow|spark|kafka|flink|pipeline|etl|elt"
            r"|datalake|warehouse|snowflake|bigquery|postgres|sqlite|duckdb)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "security",
        re.compile(
            r"\b(security|pentest|ctf|vuln|cve|owasp|auth|oauth|jwt|zero.trust"
            r"|siem|threat|malware|exploit|red.team|blue.team)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "career",
        re.compile(
            r"\b(career|job|resume|interview|salary|hire|freelance|consulting"
            r"|founder|startup|product.management|pm|leadership)\b",
            re.IGNORECASE,
        ),
    ),
]


def classify_subject(url: str, title: str = "", description: str = "") -> str:
    """Return best-matching subject or 'unspecified'."""
    combined = f"{url} {title} {description}".lower()
    for subject, pattern in _SUBJECT_PATTERNS:
        if pattern.search(combined):
            return subject
    return "unspecified"
