from dataclasses import dataclass

from pydantic import SecretStr

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError


@dataclass(frozen=True)
class GitHubBinding:
    provider: str
    api_base: str
    owner: str
    repository: str
    base_branch: str
    version: str
    key: str
    workspace_root: str


def trusted_binding() -> GitHubBinding:
    settings = get_settings()
    if not settings.github_owner or not settings.github_repository or not settings.workspace_root:
        raise ApplicationError(
            "github_binding_unavailable", "GitHub binding is unavailable", status_code=409
        )
    return GitHubBinding(
        "github",
        "https://api.github.com",
        settings.github_owner,
        settings.github_repository,
        settings.github_base_branch,
        settings.github_binding_version,
        settings.github_binding_key,
        settings.workspace_root,
    )


def resolve_github_credential() -> SecretStr:
    token = get_settings().github_publication_pat
    if token is None or not token.get_secret_value():
        raise ApplicationError(
            "github_credential_unavailable", "GitHub credential is unavailable", status_code=409
        )
    return token
