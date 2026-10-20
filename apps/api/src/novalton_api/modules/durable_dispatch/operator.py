"""A scoped, verified internal operator capability for dispatch control.

Only a trusted adapter calls authenticate_operator with the presented credential.
No HTTP endpoint, model tool or caller-supplied tenant UUID creates this authority.
The server stores only a SHA-256 digest of a high-entropy operator key.
"""

import hashlib
import hmac
from uuid import UUID

from novalton_api.core.config import get_settings
from novalton_api.core.exceptions import ApplicationError

PERMISSIONS = frozenset(
    {
        "activation.configure",
        "dispatch.enqueue",
        "dispatch.read",
        "dispatch.cancel",
        "dispatch.resolve",
    }
)
_SEAL = object()


def _forbidden() -> ApplicationError:
    return ApplicationError(
        "dispatch_operator_forbidden", "Dispatch operator authority is unavailable", status_code=403
    )


def _configured() -> tuple[str, str, UUID, UUID, frozenset[str]]:
    settings = get_settings()
    values = (
        settings.durable_dispatch_operator_key_sha256,
        settings.durable_dispatch_operator_id,
        settings.durable_dispatch_operator_tenant_id,
        settings.durable_dispatch_operator_workspace_id,
    )
    if any(value is None for value in values):
        raise _forbidden()
    permissions = frozenset(
        item.strip() for item in settings.durable_dispatch_operator_permissions.split(",") if item.strip()
    )
    if not permissions or not permissions <= PERMISSIONS:
        raise _forbidden()
    digest, actor_id, tenant_id, workspace_id = values
    assert isinstance(digest, str) and isinstance(actor_id, str)
    assert isinstance(tenant_id, UUID) and isinstance(workspace_id, UUID)
    return digest, actor_id, tenant_id, workspace_id, permissions


class OperatorAuthority:
    """Opaque in-process result of successful credential verification."""

    __slots__ = ("_seal", "_digest", "actor_id", "tenant_id", "workspace_id", "permissions")

    def __init__(
        self,
        seal: object,
        digest: str,
        actor_id: str,
        tenant_id: UUID,
        workspace_id: UUID,
        permissions: frozenset[str],
    ) -> None:
        if seal is not _SEAL:
            raise _forbidden()
        self._seal = seal
        self._digest = digest
        self.actor_id = actor_id
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.permissions = permissions

    def require(self, permission: str, *, tenant_id: UUID, workspace_id: UUID) -> None:
        digest, actor_id, configured_tenant, configured_workspace, permissions = _configured()
        if (
            self._seal is not _SEAL
            or not hmac.compare_digest(self._digest, digest)
            or self.actor_id != actor_id
            or (self.tenant_id, self.workspace_id) != (configured_tenant, configured_workspace)
            or self.permissions != permissions
            or (tenant_id, workspace_id) != (configured_tenant, configured_workspace)
            or permission not in permissions
        ):
            raise _forbidden()


def authenticate_operator(credential: str) -> OperatorAuthority:
    """Verify a high-entropy key in constant time against process configuration.

    The plaintext credential is never retained, persisted, logged or audited.
    Rotate the configured digest to revoke previously issued capabilities.
    """
    digest, actor_id, tenant_id, workspace_id, permissions = _configured()
    if not isinstance(credential, str) or len(credential) < 32:
        raise _forbidden()
    candidate = hashlib.sha256(credential.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(candidate, digest):
        raise _forbidden()
    return OperatorAuthority(_SEAL, digest, actor_id, tenant_id, workspace_id, permissions)
