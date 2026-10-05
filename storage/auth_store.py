"""
╔══════════════════════════════════════════════════════════════════════╗
║                          P  R  I  S  M                               ║
║       Autonomous AI Incident Management System                       ║
╚══════════════════════════════════════════════════════════════════════╝

  Building an Autonomous AI Incident Management System
  with LangGraph and OpenTelemetry

  Author   : Upadhyayula Avinash
  GitHub   : https://github.com/u-avinash
  LinkedIn : https://www.linkedin.com/in/avinash-upadhyayula/
  Email    : uavinash.csit@gmail.com

  Copyright (c) 2026-2035 Upadhyayula Avinash. All rights reserved.
"""
from __future__ import annotations

"""
auth_store.py — JSON-file based store for users, projects, teams, and role-based access.

Roles:
  admin       — Platform administrator; not tagged to any project by default.
  team_admin  — Manages a project's team, integrations, and feature access.
  user        — Regular team member; access scoped to assigned projects/features.

Default admin credentials:  username=admin  password=ChangeMe123!
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from storage.database import (
    ProjectIntegrationConfig,
    SecurityAuditEvent,
    get_session as get_db_session,
    init_database,
)
from utils.secret_crypto import decrypt_secret, encrypt_secret

# ── Storage path ────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "..", "data")
_AUTH_FILE = os.path.join(_DATA_DIR, "auth_data.json")

# Fields within each section that must be stored encrypted
_SECRET_FIELDS = {
    "llm": {"api_key"},
    "jira": {"api_token"},
    "github": {"token"},
    "anypoint": {"client_secret"},
    "slack": {"webhook_url"},
    "teams": {"webhook_url"},
    "runtime": set(),
    "api_keys": set(),
}

# All sections persisted in the DB config table
_DB_CONFIG_SECTIONS = ("llm", "jira", "github", "anypoint", "slack", "teams", "runtime", "api_keys")

# ── Default admin credentials ───────────────────────────────────────────────
DEFAULT_ADMIN_USERNAME = os.getenv("PRISM_DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("PRISM_DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")
DEFAULT_ADMIN_EMAIL = os.getenv("PRISM_DEFAULT_ADMIN_EMAIL", "admin@prism.local")

# ── All available feature keys ───────────────────────────────────────────────
ALL_FEATURES = [
    "dashboard",
    "incidents",
    "observability",
    "log_viewer",
    "traces",
    "metrics",
    "app_health",
    "api_analytics",
    "audit",
    "settings",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

_PASSWORD_HASH_ITERATIONS = 310_000
_SESSION_TTL_SECONDS = int(os.getenv("PRISM_SESSION_TTL_SECONDS", str(60 * 60 * 8)))


def _hash_password(password: str) -> str:
    """Return a salted PBKDF2-HMAC password hash suitable for new credentials."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PASSWORD_HASH_ITERATIONS,
    )
    return f"pbkdf2_sha256${_PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Return (is_valid, needs_upgrade), supporting legacy SHA-256 once."""
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False, False
            digest = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return hmac.compare_digest(digest.hex(), digest_hex), False
        except (TypeError, ValueError):
            return False, False

    # Legacy one-round SHA-256 hashes are upgraded at the next successful login.
    legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, stored_hash), True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "") -> str:
    return prefix + str(uuid.uuid4())[:8].upper()


def _sanitize_section_name(section: str) -> str:
    return "teams" if section in {"teams", "teams_notif"} else section


def _default_project_config(project_id: str) -> dict:
    return {
        "project_id": project_id,
        "llm": {},
        "jira": {},
        "github": {},
        "anypoint": {},
        "slack": {},
        "teams": {},
        "teams_notif": {},
        "runtime": {},
        "api_keys": [],
    }


def _encrypt_section(section: str, values: dict) -> dict:
    secret_fields = _SECRET_FIELDS.get(section, set())
    encrypted: dict = {}
    for key, value in (values or {}).items():
        if key in secret_fields and value not in (None, ""):
            encrypted[key] = encrypt_secret(str(value))
        else:
            encrypted[key] = value
    return encrypted


def _decrypt_section(section: str, values: dict | None) -> dict:
    secret_fields = _SECRET_FIELDS.get(section, set())
    decrypted: dict = {}
    for key, value in (values or {}).items():
        if key in secret_fields and value not in (None, ""):
            decrypted[key] = decrypt_secret(value)
        else:
            decrypted[key] = value
    return decrypted


def _mask_section_for_ui(section: str, values: dict | None) -> dict:
    masked = dict(values or {})
    for key in _SECRET_FIELDS.get(section, set()):
        if masked.get(key):
            masked[key] = ""
            masked[key + "_configured"] = True
        else:
            masked[key + "_configured"] = False
    return masked


def _load_db_project_config(project_id: str, mask_secrets: bool = False) -> Optional[dict]:
    with get_db_session() as session:
        row = session.query(ProjectIntegrationConfig).filter_by(project_id=project_id).first()
        if not row:
            return None

        cfg = _default_project_config(project_id)
        for section in _DB_CONFIG_SECTIONS:
            section_data = _decrypt_section(section, getattr(row, section) or {})
            cfg[section] = _mask_section_for_ui(section, section_data) if mask_secrets else section_data
        cfg["teams_notif"] = dict(cfg["teams"])
        return cfg


def _save_db_project_config(project_id: str, section: str, values: dict) -> dict:
    normalized_section = _sanitize_section_name(section)
    if normalized_section not in _DB_CONFIG_SECTIONS:
        raise ValueError(f"Unsupported project config section: {section}")

    with get_db_session() as session:
        row = session.query(ProjectIntegrationConfig).filter_by(project_id=project_id).first()
        if not row:
            row = ProjectIntegrationConfig(project_id=project_id)
            session.add(row)
            session.flush()

        current_values = _decrypt_section(normalized_section, getattr(row, normalized_section) or {})
        merged_values = dict(current_values)

        for key, value in (values or {}).items():
            if key in _SECRET_FIELDS.get(normalized_section, set()) and value in (None, ""):
                continue
            merged_values[key] = value

        setattr(row, normalized_section, _encrypt_section(normalized_section, merged_values))
        session.flush()

    cfg = _load_db_project_config(project_id, mask_secrets=False)
    return cfg or _default_project_config(project_id)


def _remove_obsolete_repository_mapping_data(data: dict) -> bool:
    """Permanently discard deprecated per-project aliases and repo mappings."""
    changed = False
    for project in data.get("projects", []):
        if project.pop("app_names", None) is not None:
            changed = True
    for config in data.get("project_configs", []):
        if config.pop("repo_mappings", None) is not None:
            changed = True
    return changed


def _migrate_legacy_project_configs(data: dict) -> bool:
    changed = False
    legacy_configs = data.get("project_configs", [])
    if not legacy_configs:
        return False

    for cfg in legacy_configs:
        project_id = cfg.get("project_id")
        if not project_id:
            continue
        for section in _DB_CONFIG_SECTIONS:
            section_values = cfg.get(section) or cfg.get("teams_notif" if section == "teams" else section) or {}
            if section_values:
                _save_db_project_config(project_id, section, section_values)
                changed = True

    if changed:
        data["project_configs"] = []
        _save(data)
    return changed


# ── File I/O ─────────────────────────────────────────────────────────────────

def _load() -> dict:
    os.makedirs(_DATA_DIR, exist_ok=True)
    if not os.path.exists(_AUTH_FILE):
        return _seed_defaults()
    with open(_AUTH_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    changed = _remove_obsolete_repository_mapping_data(data)
    changed = _migrate_legacy_project_configs(data) or changed
    if changed:
        _save(data)
    return data


def _save(data: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_AUTH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _seed_defaults() -> dict:
    """Create the initial data file with a default admin user."""
    data: dict = {
        "users": [],
        "projects": [],
        "teams": [],
        "memberships": [],
        "project_assignments": [],
        "project_configs": [],
    }
    admin_id = "USR-ADMIN"
    data["users"].append(
        {
            "id": admin_id,
            "username": DEFAULT_ADMIN_USERNAME,
            "email": DEFAULT_ADMIN_EMAIL,
            "password_hash": _hash_password(DEFAULT_ADMIN_PASSWORD),
            "role": "admin",
            "features": ALL_FEATURES,
            "created_at": _now(),
            "is_active": True,
        }
    )
    _save(data)
    return data


def _ensure_keys(data: dict) -> None:
    """Back-fill missing top-level keys for older data files."""
    for key in ("project_assignments", "project_configs"):
        data.setdefault(key, [])
    for u in data.get("users", []):
        if "features" not in u:
            if u.get("role") == "admin":
                u["features"] = ALL_FEATURES
            elif u.get("role") == "team_admin":
                u["features"] = ALL_FEATURES
            else:
                u["features"] = ["dashboard", "incidents"]


# ════════════════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════════════════

def authenticate(username: str, password: str) -> Optional[dict]:
    """Return user dict on success, None on failure."""
    data = _load()
    _ensure_keys(data)
    matches = []
    requires_save = False
    for user in data["users"]:
        if user.get("username") != username or not user.get("is_active", True):
            continue
        valid, needs_upgrade = _verify_password(password, str(user.get("password_hash") or ""))
        if not valid:
            continue
        if needs_upgrade:
            user["password_hash"] = _hash_password(password)
            requires_save = True
        matches.append(user)

    if requires_save:
        _save(data)
    if not matches:
        return None

    assigned_user_ids = {a.get("user_id") for a in data.get("project_assignments", [])}

    def _sort_key(user: dict) -> tuple:
        return (
            1 if user.get("id") in assigned_user_ids else 0,
            1 if user.get("role") in {"team_admin", "admin"} else 0,
            user.get("created_at", ""),
        )

    matches.sort(key=_sort_key, reverse=True)
    return matches[0]


def get_user_by_id(user_id: str) -> Optional[dict]:
    data = _load()
    return next((u for u in data["users"] if u["id"] == user_id), None)


def get_user_by_username(username: str) -> Optional[dict]:
    data = _load()
    return next((u for u in data["users"] if u["username"] == username), None)


# ════════════════════════════════════════════════════════════════════════════
# USERS (admin management)
# ════════════════════════════════════════════════════════════════════════════

def list_users() -> list:
    data = _load()
    _ensure_keys(data)
    return data.get("users", [])


def create_user(payload: dict) -> dict:
    data = _load()
    _ensure_keys(data)

    username = (payload.get("username") or "").strip()
    email = (payload.get("email") or "").strip()

    existing = next(
        (
            u for u in data["users"]
            if u.get("username", "").lower() == username.lower()
            or (email and u.get("email", "").lower() == email.lower())
        ),
        None,
    )
    if existing:
        return existing

    role = payload.get("role", "user")
    if role == "admin":
        default_features = ALL_FEATURES
    elif role == "team_admin":
        default_features = ALL_FEATURES
    else:
        default_features = payload.get("features", ["dashboard", "incidents"])

    user = {
        "id": "USR-" + _new_id(),
        "username": username,
        "email": email,
        "password_hash": _hash_password(payload.get("password", "changeme")),
        "role": role,
        "features": default_features,
        "created_at": _now(),
        "is_active": True,
    }
    data["users"].append(user)
    _save(data)
    return user


def update_user(user_id: str, payload: dict) -> Optional[dict]:
    data = _load()
    _ensure_keys(data)
    for u in data["users"]:
        if u["id"] == user_id:
            if "password" in payload:
                u["password_hash"] = _hash_password(payload.pop("password"))
            for k, v in payload.items():
                if k not in ("id", "password_hash"):
                    u[k] = v
            _save(data)
            return u
    return None


def delete_user(user_id: str) -> bool:
    data = _load()
    _ensure_keys(data)
    before = len(data["users"])
    data["users"] = [u for u in data["users"] if u["id"] != user_id]
    data["memberships"] = [m for m in data["memberships"] if m["user_id"] != user_id]
    data["project_assignments"] = [
        a for a in data["project_assignments"] if a["user_id"] != user_id
    ]
    _save(data)
    return len(data["users"]) < before


# ════════════════════════════════════════════════════════════════════════════
# FEATURE ACCESS PER USER (managed by Team Admin)
# ════════════════════════════════════════════════════════════════════════════

def set_user_features(user_id: str, features: list) -> Optional[dict]:
    """Team Admin sets which features a user can access."""
    return update_user(user_id, {"features": features})


def get_user_features(user_id: str) -> list:
    user = get_user_by_id(user_id)
    if not user:
        return []
    return user.get("features", ["dashboard", "incidents"])


# ════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ════════════════════════════════════════════════════════════════════════════

def list_projects() -> list:
    data = _load()
    return data.get("projects", [])


def create_project(payload: dict) -> dict:
    data = _load()
    _ensure_keys(data)
    project = {
        "id": "PRJ-" + _new_id(),
        "name": payload["name"],
        "description": payload.get("description", ""),
        "repo_url": payload.get("repo_url", ""),
        "applications": [],
        "customer_id": payload.get("customer_id", ""),
        "stack": payload.get("stack", ""),
        "environment": payload.get("environment", "production"),
        "owner_id": "USR-ADMIN",
        "team_admin_id": payload.get("team_admin_id", ""),
        "team_admin_email": payload.get("team_admin_email", ""),
        "created_at": _now(),
        "is_active": True,
    }
    data["projects"].append(project)
    _save(data)
    get_project_config(project["id"])
    return project


def get_project(project_id: str) -> Optional[dict]:
    data = _load()
    return next((p for p in data["projects"] if p["id"] == project_id), None)


def update_project(project_id: str, payload: dict) -> Optional[dict]:
    data = _load()
    for p in data["projects"]:
        if p["id"] == project_id:
            for k, v in payload.items():
                if k != "id":
                    p[k] = v
            _save(data)
            return p
    return None


def _normalize_application_token(value: object) -> str:
    """Normalize service/repository aliases for deterministic application lookup."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def list_project_applications(project_id: str) -> list[dict]:
    """Return the explicitly registered applications for a project."""
    project = get_project(project_id)
    if not project:
        return []
    return [
        dict(application)
        for application in project.get("applications", [])
        if isinstance(application, dict)
    ]


def get_project_application(project_id: str, identifier: str) -> Optional[dict]:
    """Resolve an application by its ID, name, service identifier, or alias."""
    token = _normalize_application_token(identifier)
    if not token:
        return None
    for application in list_project_applications(project_id):
        candidates = [
            application.get("id"),
            application.get("name"),
            application.get("service_name"),
            *(application.get("aliases") or []),
        ]
        if any(_normalize_application_token(candidate) == token for candidate in candidates):
            return application
    return None


def upsert_project_application(project_id: str, payload: dict) -> Optional[dict]:
    """Create or update a project application registration."""
    data = _load()
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("Application name is required")

    for project in data.get("projects", []):
        if project.get("id") != project_id:
            continue

        applications = project.setdefault("applications", [])
        application_id = str(payload.get("id") or "").strip()
        application = next(
            (
                item for item in applications
                if item.get("id") == application_id
                or (
                    not application_id
                    and _normalize_application_token(item.get("name"))
                    == _normalize_application_token(name)
                )
            ),
            None,
        )
        aliases = [
            str(alias).strip()
            for alias in (payload.get("aliases") or [])
            if str(alias).strip()
        ]
        values = {
            "name": name,
            "aliases": list(dict.fromkeys(aliases)),
            "technology": str(payload.get("technology") or payload.get("stack") or "").strip(),
            "repository": str(payload.get("repository") or "").strip(),
            "default_branch": str(payload.get("default_branch") or "").strip(),
            "service_name": str(payload.get("service_name") or name).strip(),
            "service_namespace": str(payload.get("service_namespace") or "").strip(),
            "environments": list(payload.get("environments") or []),
            "enabled": bool(payload.get("enabled", True)),
            "description": str(payload.get("description") or "").strip(),
            "updated_at": _now(),
        }
        if application:
            application.update(values)
        else:
            application = {
                "id": "APP-" + _new_id(),
                "created_at": _now(),
                **values,
            }
            applications.append(application)

        _save(data)
        return dict(application)
    return None


def delete_project_application(project_id: str, application_id: str) -> bool:
    """Remove a first-class application record without deleting historical aliases."""
    data = _load()
    for project in data.get("projects", []):
        if project.get("id") != project_id:
            continue
        before = len(project.get("applications", []))
        project["applications"] = [
            item for item in project.get("applications", [])
            if item.get("id") != application_id
        ]
        if len(project["applications"]) != before:
            _save(data)
            return True
    return False


def delete_project(project_id: str) -> bool:
    data = _load()
    before = len(data["projects"])
    data["projects"] = [p for p in data["projects"] if p["id"] != project_id]
    data["project_assignments"] = [a for a in data.get("project_assignments", []) if a["project_id"] != project_id]
    _save(data)

    with get_db_session() as session:
        session.query(ProjectIntegrationConfig).filter_by(project_id=project_id).delete()

    return len(data["projects"]) < before


# ════════════════════════════════════════════════════════════════════════════
# PROJECT ↔ USER ASSIGNMENTS
# ════════════════════════════════════════════════════════════════════════════

def assign_user_to_project(user_id: str, project_id: str) -> dict:
    data = _load()
    _ensure_keys(data)
    existing = next(
        (a for a in data["project_assignments"] if a["user_id"] == user_id and a["project_id"] == project_id),
        None,
    )
    if existing:
        return existing
    assignment = {"id": "ASN-" + _new_id(), "user_id": user_id, "project_id": project_id, "assigned_at": _now()}
    data["project_assignments"].append(assignment)
    _save(data)
    return assignment


def remove_user_from_project(user_id: str, project_id: str) -> bool:
    data = _load()
    _ensure_keys(data)
    before = len(data["project_assignments"])
    data["project_assignments"] = [
        a for a in data["project_assignments"]
        if not (a["user_id"] == user_id and a["project_id"] == project_id)
    ]
    _save(data)
    return len(data["project_assignments"]) < before


def get_user_projects(user_id: str) -> list:
    """Return list of projects assigned to a user."""
    data = _load()
    _ensure_keys(data)
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        return []
    if user.get("role") == "admin":
        return data.get("projects", [])
    project_ids = {a["project_id"] for a in data["project_assignments"] if a["user_id"] == user_id}
    for p in data.get("projects", []):
        if p.get("team_admin_id") == user_id:
            project_ids.add(p["id"])
    return [p for p in data.get("projects", []) if p["id"] in project_ids]


def get_project_users(project_id: str) -> list:
    """Return list of users assigned to a project."""
    data = _load()
    _ensure_keys(data)
    user_ids = {a["user_id"] for a in data["project_assignments"] if a["project_id"] == project_id}
    return [u for u in data["users"] if u["id"] in user_ids]


# ════════════════════════════════════════════════════════════════════════════
# PROJECT CONFIGS  (per-project integration settings)
# ════════════════════════════════════════════════════════════════════════════

def get_project_config(project_id: str, mask_secrets: bool = False) -> Optional[dict]:
    data = _load()
    _ensure_keys(data)
    cfg = _load_db_project_config(project_id, mask_secrets=mask_secrets)
    if cfg is None:
        cfg = _default_project_config(project_id)
        for section in _DB_CONFIG_SECTIONS:
            _save_db_project_config(project_id, section, {})
        cfg = _load_db_project_config(project_id, mask_secrets=mask_secrets)
    return cfg


def update_project_config(project_id: str, section: str, values: dict) -> Optional[dict]:
    data = _load()
    _ensure_keys(data)
    normalized_section = _sanitize_section_name(section)
    sanitized_values = {
        k: v for k, v in (values or {}).items()
        if k not in {"project_id", "section"} and v is not None
    }
    cfg = _save_db_project_config(project_id, normalized_section, sanitized_values)
    if normalized_section == "teams":
        cfg["teams_notif"] = dict(cfg["teams"])
    return cfg


def clear_project_config(project_id: str, section: str) -> Optional[dict]:
    normalized_section = _sanitize_section_name(section)
    if normalized_section not in _DB_CONFIG_SECTIONS:
        raise ValueError(f"Unsupported project config section: {section}")

    with get_db_session() as session:
        row = session.query(ProjectIntegrationConfig).filter_by(project_id=project_id).first()
        if not row:
            row = ProjectIntegrationConfig(project_id=project_id)
            session.add(row)
            session.flush()
        setattr(row, normalized_section, {})
        session.flush()

    return _load_db_project_config(project_id, mask_secrets=False) or _default_project_config(project_id)


def record_security_audit_event(
    action: str,
    *,
    project_id: Optional[str] = None,
    actor_type: str = "system",
    actor_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    outcome: str = "success",
    source_ip: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Persist a best-effort append-only event without exposing credentials."""
    try:
        with get_db_session() as session:
            session.add(
                SecurityAuditEvent(
                    event_id=str(uuid.uuid4()),
                    project_id=project_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    outcome=outcome,
                    source_ip=source_ip,
                    details=details or {},
                )
            )
    except Exception:
        # A security event must not make an ingestion request or an emergency
        # key revocation unavailable if audit storage is temporarily unhealthy.
        pass


def _api_key_digest(api_key: str) -> str:
    """Return a stable non-reversible digest for an ingestion API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _get_api_key_records(config: dict) -> list[dict]:
    """Support the persisted section wrapper and temporary legacy list form."""
    section = (config or {}).get("api_keys") or {}
    if isinstance(section, list):
        return [entry for entry in section if isinstance(entry, dict)]
    if isinstance(section, dict):
        return [
            entry for entry in (section.get("api_keys") or [])
            if isinstance(entry, dict)
        ]
    return []


def create_project_api_key(project_id: str, label: str, expires_at: Optional[str] = None) -> dict:
    """Create an ingestion key and persist only its digest; raw key is returned once."""
    raw_key = "prism_" + secrets.token_urlsafe(32)
    record = {
        "id": "KEY-" + _new_id(),
        "label": (label or "Ingestion key").strip()[:100],
        "digest": _api_key_digest(raw_key),
        "created_at": _now(),
        "expires_at": expires_at,
        "revoked_at": None,
        "last_used_at": None,
    }
    cfg = get_project_config(project_id) or _default_project_config(project_id)
    records = _get_api_key_records(cfg)
    records.append(record)
    update_project_config(project_id, "api_keys", {"api_keys": records})
    record_security_audit_event(
        "api_key.created",
        project_id=project_id,
        target_type="api_key",
        target_id=record["id"],
        details={"label": record["label"], "expires_at": expires_at},
    )
    return {**record, "key": raw_key}


def list_project_api_keys(project_id: str) -> list[dict]:
    """Return API-key metadata, never raw key values or digests."""
    cfg = get_project_config(project_id) or {}
    return [
        {k: v for k, v in entry.items() if k not in {"key", "digest"}}
        for entry in _get_api_key_records(cfg)
    ]


def revoke_project_api_key(project_id: str, key_id: str) -> bool:
    """Revoke a key without deleting its audit-relevant lifecycle record."""
    cfg = get_project_config(project_id) or _default_project_config(project_id)
    records = _get_api_key_records(cfg)
    found = False
    for record in records:
        if isinstance(record, dict) and record.get("id") == key_id and not record.get("revoked_at"):
            record["revoked_at"] = _now()
            found = True
    if found:
        update_project_config(project_id, "api_keys", {"api_keys": records})
        record_security_audit_event(
            "api_key.revoked",
            project_id=project_id,
            target_type="api_key",
            target_id=key_id,
        )
    return found


def verify_project_api_key(project_id: str, api_key: str) -> Optional[dict]:
    """Verify an active, unexpired hashed key and record its last use."""
    cfg = get_project_config(project_id) or {}
    records = _get_api_key_records(cfg)
    candidate_digest = _api_key_digest(api_key)
    now = datetime.now(timezone.utc)
    matched: Optional[dict] = None

    for record in records:
        if not isinstance(record, dict) or record.get("revoked_at"):
            continue
        expires_at = record.get("expires_at")
        if expires_at:
            try:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= now:
                    continue
            except ValueError:
                continue
        digest = record.get("digest")
        # Legacy plaintext entries remain valid only for migration compatibility.
        legacy_key = record.get("key")
        if (digest and hmac.compare_digest(str(digest), candidate_digest)) or (
            legacy_key and hmac.compare_digest(str(legacy_key), api_key)
        ):
            record["last_used_at"] = _now()
            matched = dict(record)
            break

    if matched:
        update_project_config(project_id, "api_keys", {"api_keys": records})
        record_security_audit_event(
            "api_key.used",
            project_id=project_id,
            actor_type="api_key",
            actor_id=matched.get("id"),
            target_type="ingestion",
            details={"label": matched.get("label")},
        )
        return {k: v for k, v in matched.items() if k not in {"key", "digest"}}
    return None


# ════════════════════════════════════════════════════════════════════════════
# TEAMS
# ════════════════════════════════════════════════════════════════════════════

def list_teams(project_id: Optional[str] = None) -> list:
    data = _load()
    teams = data.get("teams", [])
    if project_id:
        teams = [t for t in teams if t.get("project_id") == project_id]
    return teams


def create_team(payload: dict) -> dict:
    data = _load()
    _ensure_keys(data)
    team = {
        "id": "TM-" + _new_id(),
        "name": payload["name"],
        "description": payload.get("description", ""),
        "project_id": payload.get("project_id", ""),
        "created_at": _now(),
    }
    data["teams"].append(team)
    _save(data)
    return team


# ════════════════════════════════════════════════════════════════════════════
# SESSIONS  (simple in-memory via JSON)
# ════════════════════════════════════════════════════════════════════════════

_SESSIONS_FILE = os.path.join(_DATA_DIR, "sessions.json")


def _load_sessions() -> dict:
    if not os.path.exists(_SESSIONS_FILE):
        return {}
    try:
        with open(_SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sessions(sessions: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_SESSIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)


def create_session(user: dict) -> str:
    token = str(uuid.uuid4())
    sessions = _load_sessions()
    sessions[token] = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user.get("role", "user"),
        "email": user.get("email", ""),
        "features": user.get("features", ["dashboard", "incidents"]),
        "csrf_token": secrets.token_urlsafe(32),
        "created_at": _now(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=_SESSION_TTL_SECONDS)).isoformat(),
    }
    _save_sessions(sessions)
    return token


def get_session(token: str) -> Optional[dict]:
    sessions = _load_sessions()
    session = sessions.get(token)
    if not session:
        return None

    expires_at = session.get("expires_at")
    try:
        expires = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        # Sessions created before expiry support are invalidated rather than
        # kept indefinitely.
        expires = datetime.min.replace(tzinfo=timezone.utc)

    if expires <= datetime.now(timezone.utc):
        sessions.pop(token, None)
        _save_sessions(sessions)
        return None
    return session


def delete_session(token: str) -> None:
    sessions = _load_sessions()
    sessions.pop(token, None)
    _save_sessions(sessions)


# ════════════════════════════════════════════════════════════════════════════
# FIRST-RUN CHECK
# ════════════════════════════════════════════════════════════════════════════

def is_first_run() -> bool:
    """True if no auth data file exists yet (fresh install)."""
    return not os.path.exists(_AUTH_FILE)


# ════════════════════════════════════════════════════════════════════════════
# COMPAT ALIASES  (legacy names used by server.py)
# ════════════════════════════════════════════════════════════════════════════

def authenticate_user(username: str, password: str) -> Optional[dict]:
    return authenticate(username, password)
