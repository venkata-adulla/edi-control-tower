from __future__ import annotations

import os
from enum import Enum
from typing import Iterable, Set


class Role(str, Enum):
    viewer = "viewer"
    operator = "operator"
    admin = "admin"


class Permission(str, Enum):
    view = "view"
    upload = "upload"
    manage_incidents = "manage_incidents"
    configure = "configure"


_ROLE_PERMISSIONS = {
    Role.viewer: {Permission.view},
    Role.operator: {Permission.view, Permission.upload, Permission.manage_incidents},
    Role.admin: {
        Permission.view,
        Permission.upload,
        Permission.manage_incidents,
        Permission.configure,
    },
}


def get_current_role() -> Role:
    raw = (os.getenv("EDI_ROLE", Role.viewer.value) or Role.viewer.value).strip().lower()
    try:
        return Role(raw)
    except ValueError:
        return Role.viewer


def permissions_for(role: Role) -> Set[Permission]:
    return set(_ROLE_PERMISSIONS.get(role, {Permission.view}))


def has_permission(permission: Permission, role: Role | None = None) -> bool:
    if role is None:
        role = get_current_role()
    return permission in permissions_for(role)


def require_permissions(perms: Iterable[Permission], role: Role | None = None) -> bool:
    if role is None:
        role = get_current_role()
    role_perms = permissions_for(role)
    return all(p in role_perms for p in perms)
