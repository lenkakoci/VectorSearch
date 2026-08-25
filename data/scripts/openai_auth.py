"""OpenAI SDK client authentication helpers for data scripts."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from openai import OpenAI


TokenProvider = Callable[[], str]

_ENTRA_MODES = {"entra", "aad", "azure_ad", "managed_identity"}
_KEY_MODES = {"key", "api_key"}


class EntraOpenAI(OpenAI):
    """OpenAI client that refreshes Microsoft Entra bearer tokens per request."""

    def __init__(self, *, token_provider: TokenProvider, **kwargs: Any) -> None:
        self._token_provider = token_provider
        super().__init__(api_key="entra-token", **kwargs)

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token_provider()}"}


def create_openai_client(
    *,
    api_key: str | None,
    base_url: str | None = None,
    api_version: str | None = None,
) -> OpenAI:
    """Create an OpenAI SDK client using API key or Microsoft Entra ID."""

    if should_use_entra_auth(api_key, base_url):
        if not base_url:
            raise ValueError("OPENAI_BASE_URL is required when OPENAI_AUTH_MODE=entra")
        return EntraOpenAI(
            token_provider=_get_entra_token_provider(base_url),
            **_build_endpoint_kwargs(base_url=base_url, api_version=api_version),
        )
    return OpenAI(**build_openai_client_kwargs(api_key=api_key, base_url=base_url, api_version=api_version))


def build_openai_client_kwargs(
    *,
    api_key: str | None,
    base_url: str | None = None,
    api_version: str | None = None,
) -> dict[str, Any]:
    """Build unified OpenAI SDK kwargs for OpenAI, Azure OpenAI, or Foundry."""

    use_entra = should_use_entra_auth(api_key, base_url)
    if use_entra:
        if not base_url:
            raise ValueError("OPENAI_BASE_URL is required when OPENAI_AUTH_MODE=entra")
        credential: str | TokenProvider = _get_entra_token_provider(base_url)
    else:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required unless Microsoft Entra ID auth is enabled")
        credential = api_key

    kwargs: dict[str, Any] = {"api_key": credential}
    kwargs.update(_build_endpoint_kwargs(base_url=base_url, api_version=api_version))
    return kwargs


def _build_endpoint_kwargs(*, base_url: str | None, api_version: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if base_url:
        kwargs["base_url"] = base_url
    default_query = _default_query(base_url, api_version)
    if default_query:
        kwargs["default_query"] = default_query
    return kwargs


def should_use_entra_auth(api_key: str | None, base_url: str | None) -> bool:
    """Return whether Microsoft Entra ID should authenticate Azure/Foundry calls."""

    auth_mode = os.getenv("OPENAI_AUTH_MODE", "auto").strip().lower()
    if auth_mode in _ENTRA_MODES:
        return True
    if auth_mode in _KEY_MODES:
        return False
    if _truthy(os.getenv("OPENAI_USE_ENTRA_ID")) or _truthy(os.getenv("AZURE_OPENAI_USE_ENTRA_ID")):
        return True
    return bool(base_url and not api_key)


def _get_entra_token_provider(base_url: str) -> TokenProvider:
    scope = (
        os.getenv("OPENAI_ENTRA_SCOPE")
        or os.getenv("AZURE_OPENAI_TOKEN_SCOPE")
        or _default_entra_scope(base_url)
    )
    if os.getenv("OPENAI_ENTRA_CREDENTIAL", "auto").strip().lower() == "azure_cli":
        return _azure_cli_token_provider(scope)

    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "Microsoft Entra ID auth requires the azure-identity package. "
            "Install data script dependencies with uv sync."
        ) from exc

    return get_bearer_token_provider(DefaultAzureCredential(), scope)


def _azure_cli_token_provider(scope: str) -> TokenProvider:
    resource = scope.removesuffix("/.default")
    az_command = shutil.which("az") or shutil.which("az.cmd") or "az"

    def provider() -> str:
        completed = subprocess.run(
            [az_command, "account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    return provider


def _default_query(base_url: str | None, api_version: str | None) -> dict[str, str] | None:
    if not base_url or not api_version:
        return None
    if "/openai/v1" in base_url.lower():
        return None
    return {"api-version": api_version}


def _default_entra_scope(base_url: str) -> str:
    normalized = base_url.lower()
    if "services.ai.azure.com" in normalized:
        return "https://ai.azure.com/.default"
    return "https://cognitiveservices.azure.com/.default"


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})
