from __future__ import annotations

import os
from enum import Enum
from typing import Iterable, Set


class Role(str, Enum):
    ops = "Ops"
    manager = "Manager"
    exec = "Exec"


class Feature(str, Enum):
    chatbot = "chatbot"
    upload = "upload"
    kpis = "kpis"
    incidents = "incidents"


class Permission(str, Enum):
    view = "view"
    upload = "upload"
    manage_incidents = "manage_incidents"
    configure = "configure"


_ROLE_FEATURES = {
    Role.ops: {Feature.chatbot, Feature.upload, Feature.kpis, Feature.incidents},
    Role.manager: {Feature.chatbot, Feature.upload, Feature.kpis, Feature.incidents},
    Role.exec: {Feature.chatbot, Feature.kpis, Feature.incidents},
}


_ROLE_PERMISSIONS = {
    Role.ops: {Permission.view, Permission.upload, Permission.manage_incidents},
    Role.manager: {Permission.view, Permission.upload, Permission.manage_incidents, Permission.configure},
    Role.exec: {Permission.view},
}


def get_current_role() -> Role:
    """
    Current business role for this session.

    This is set by the Streamlit sidebar selector in app.py via CONTROL_TOWER_ROLE.
    """
    raw = (os.getenv("CONTROL_TOWER_ROLE", Role.ops.value) or Role.ops.value).strip()
    try:
        return Role(raw)
    except ValueError:
        return Role.ops


def features_for(role: Role) -> Set[Feature]:
    return set(_ROLE_FEATURES.get(role, set()))


def can_access(feature: Feature, role: Role | None = None) -> bool:
    if role is None:
        role = get_current_role()
    return feature in features_for(role)


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
