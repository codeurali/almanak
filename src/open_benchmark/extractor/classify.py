"""
extractor/classify.py — Heuristic URL type and subject classifier.

Rules are keyword/domain-based — no LLM dependency.
Both functions return strings matching the DB enum values.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── Type classification ────────────────────────────────────────────────────────

_REPO_DOMAINS = {"github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "gitflic.ru"}
_VIDEO_DOMAINS = {"youtube.com", "youtu.be", "vimeo.com", "loom.com", "wistia.com"}
_SOCIAL_DOMAINS = {
    "twitter.com", "x.com", "linkedin.com", "reddit.com",
    "threads.net", "mastodon.social", "bsky.app", "substack.com",
}
_PKG_DOMAINS = {
    "pypi.org", "npmjs.com", "crates.io", "hex.pm", "packagist.org",
    "rubygems.org", "pub.dev", "nuget.org",
}
_DOC_DOMAINS = {
    "docs.microsoft.com", "learn.microsoft.com", "developer.mozilla.org",
    "readthedocs.io", "readthedocs.org", "docs.github.com", "docs.python.org",
    "developers.google.com", "cloud.google.com/docs", "docs.aws.amazon.com",
}
_MODEL_DOMAINS = {
    "huggingface.co", "ollama.com", "ollama.ai",
    "civitai.com", "replicate.com",
}
_DATASET_DOMAINS = {
    "kaggle.com", "zenodo.org", "data.gov", "archive.ics.uci.edu",
}
_RESEARCH_PATTERNS = re.compile(
    r"arxiv\.org|paper(?:s)?\.ssrn|openreview\.net|semanticscholar\.org"
    r"|dl\.acm\.org|ieeexplore\.ieee\.org|springer\.com/article"
    r"|nature\.com/articles|proceedings\.",
    re.IGNORECASE,
)
_TOOL_KEYWORDS = re.compile(
    r"\b(tool|cli|dashboard|playground|sandbox|ide|editor|builder|generator|extension|plugin)\b",
    re.IGNORECASE,
)


def classify_type(url: str, title: str = "", description: str = "") -> str:
    """Return one of: repo, video, research, doc, package, model, dataset, article, social, tool, other."""
    parsed = urlparse(url.lower())
    domain = parsed.netloc.lstrip("www.")

    if domain in _REPO_DOMAINS:
        # Sub-classify: org pages, user pages, non-repo paths are not repos
        path = parsed.path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return "repo"
        return "other"
    if domain in _MODEL_DOMAINS:
        return "model"
    if domain in _DATASET_DOMAINS:
        return "dataset"
    if domain in _VIDEO_DOMAINS:
        return "video"
    if domain in _SOCIAL_DOMAINS:
        return "social"
    if domain in _PKG_DOMAINS:
        return "package"
    if any(domain == d or domain.endswith(f".{d}") for d in _DOC_DOMAINS):
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
        "agentic-tools",
        re.compile(
            r"\b(mcp|model.context.protocol|agentic.tool|agent.framework|agent.sdk"
            r"|langgraph|langchain|crewai|autogen|llamaindex|llama.index|smolagents"
            r"|openai.agents|claude.tool.use|function.calling|tool.use|tool.call"
            r"|agent.orchestrat|multi.?agent|agent.loop|agent.workflow|agent.system"
            r"|memory.agent|planning.agent|react.agent|reflexion|taskweaver|agentops"
            r"|composio|e2b|dagger.ai|browseruse|computer.use|tool.augment)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "software-engineering",
        re.compile(
            r"\b(spec.driven|test.driven|tdd|bdd|ddd|domain.driven|clean.code"
            r"|clean.architecture|solid.principle|design.pattern|refactor"
            r"|code.review|technical.debt|engineering.practice|software.craft"
            r"|openapi|swagger|api.contract|api.spec|api.first|schema.first"
            r"|pair.programm|mob.programm|trunk.based|feature.flag|continuous.integr"
            r"|monorepo|code.quality|software.architect|engineering.culture"
            r"|developer.experience|dx|devex|inner.source|documentation.driven)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "ai",
        re.compile(
            r"\b(ai|llm|gpt|claude|gemini|mistral|llama|machine.learning|deep.learning"
            r"|neural|transformer|generative|diffusion|embedding|rag|vector|semantic"
            r"|nlp|computer.vision|stable.diffusion|midjourney|openai|anthropic"
            r"|hugging.?face|fine.?tun|inference|prompt|agent|agentic|multi.?modal"
            r"|text.to.image|text.to.video|vision.language|foundation.model|sora|flux)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "benchmark",
        re.compile(
            r"\b(benchmark|evaluation|leaderboard|performance|metric|score|test|eval"
            r"|comparison|ranking|sota|state.of.the.art|evals?|lm.?eval|hellaswag"
            r"|mmlu|humaneval|swe.bench)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "power-platform",
        re.compile(
            r"\b(power.apps|power.automate|power.bi|power.pages|power.virtual.agents"
            r"|dataverse|dynamics.365|d365|copilot.studio|power.platform|canvas.app"
            r"|model.driven.app|power.fx|pcf|pac.cli)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "azure",
        re.compile(
            r"\b(azure|microsoft.cloud|azure.devops|ado|azure.openai|azure.ai"
            r"|azure.functions|azure.logic.apps|bicep|arm.template|azure.ml"
            r"|azure.container|aks|azure.search|cognitive.services)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system-design",
        re.compile(
            r"\b(system.design|system.architecture|distributed.system|scalab"
            r"|microservice|api.design|high.availability|load.balanc|caching"
            r"|message.queue|event.driven|cqrs|saga.pattern|cap.theorem"
            r"|consistency|replication|sharding|distributed)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "dev-tools",
        re.compile(
            r"\b(vscode|cursor|copilot|neovim|git|github.actions|ci.?cd|devops"
            r"|docker|kubernetes|k8s|helm|terraform|pulumi|ansible|cli.tool"
            r"|taskfile|makefile|pre.?commit|linting|formatter|debugger)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "infra",
        re.compile(
            r"\b(linux|server|nginx|caddy|traefik|selfhost|self.host|vps|homelab"
            r"|networking|firewall|vpn|tailscale|wireguard|reverse.proxy|proxmox"
            r"|bare.metal|colocation|cloud.infra|sre|reliability|observab)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "web-dev",
        re.compile(
            r"\b(react|nextjs|next\.js|vue|svelte|astro|typescript|javascript"
            r"|tailwind|css|html|frontend|fullstack|web.framework|rest.api|graphql"
            r"|remix|nuxt|sveltekit|htmx|trpc|prisma|drizzle|web.component)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data",
        re.compile(
            r"\b(data.engineering|dbt|airflow|spark|kafka|flink|pipeline|etl|elt"
            r"|datalake|warehouse|snowflake|bigquery|postgres|sqlite|duckdb"
            r"|analytics|pandas|polars|arrow|parquet|iceberg|delta.lake)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mobile",
        re.compile(
            r"\b(android|ios|swift|kotlin|flutter|react.native|expo|mobile.app"
            r"|xcode|app.store|play.store|swiftui|jetpack.compose)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "security",
        re.compile(
            r"\b(security|pentest|ctf|vuln|cve|owasp|auth|oauth|jwt|zero.trust"
            r"|siem|threat|malware|exploit|red.team|blue.team|devsecops"
            r"|supply.chain|sbom|encryption|cryptography)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "career",
        re.compile(
            r"\b(career|job|resume|interview|salary|hire|freelance|consulting"
            r"|founder|startup|product.management|pm|leadership|hiring|recrui)\b",
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
