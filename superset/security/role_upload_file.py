# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""Permission of the Upload file feature.

One permission, ``can access on UploadFile``, opens the whole feature (the page
and every API of ``superset/views/upload_file.py``): select it in the
permissions of a role (Settings > List Roles) and the role can use Upload file.

Superset builds its AppBuilder with ``update_perms=False``, so the permission
of a new view only exists after ``superset init``. ``sync_permissions`` is run
at start-up to create it and to:

* give it to the ``Admin`` role;
* give it to the roles that held one of the permissions of the previous
  releases (``can page``, ``can process``, ``menu access`` ...), then remove
  those obsolete permissions so the role form only offers the one to select.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

VIEW_MENU = "UploadFile"
PERMISSION = "can_access"
# Menu entry of the previous releases (its "menu access" permission is obsolete)
LEGACY_MENU = "Upload File"

# NOTE: keep the imports of superset.extensions / FAB models inside functions:
# the security manager is loaded very early and top-level imports could create
# a circular import.


def ensure_permission() -> None:
    """Create ``can access on UploadFile`` when it does not exist yet."""
    from flask import current_app

    appbuilder = current_app.appbuilder
    for baseview in appbuilder.baseviews:
        if getattr(baseview, "class_permission_name", None) == VIEW_MENU:
            appbuilder._add_permission(baseview, update_perms=True)  # noqa: SLF001


def _permission_views(*view_menus: str) -> list[Any]:
    from flask_appbuilder.security.sqla.models import PermissionView, ViewMenu

    from superset.extensions import db

    return (
        db.session.query(PermissionView)
        .join(ViewMenu, PermissionView.view_menu_id == ViewMenu.id)
        .filter(ViewMenu.name.in_(view_menus))
        .all()
    )


def sync_permissions() -> None:
    from flask import current_app
    from flask_appbuilder.security.sqla.models import Role, ViewMenu

    from superset.extensions import db

    ensure_permission()
    current = [
        pv for pv in _permission_views(VIEW_MENU) if pv.permission.name == PERMISSION
    ]
    if not current:
        logger.warning("Upload file permission not found, nothing to sync")
        return
    access = current[0]

    legacy = [
        pv for pv in _permission_views(VIEW_MENU, LEGACY_MENU) if pv.id != access.id
    ]
    roles: dict[int, Any] = {}
    for pv in legacy:
        for role in pv.role:
            roles[role.id] = role
    admin = (
        db.session.query(Role)
        .filter_by(name=current_app.config.get("AUTH_ROLE_ADMIN", "Admin"))
        .one_or_none()
    )
    if admin is not None:
        roles[admin.id] = admin

    granted = 0
    for role in roles.values():
        if access not in role.permissions:
            role.permissions.append(access)
            granted += 1

    # Obsolete permissions: detach them from the roles, then delete them
    for pv in legacy:
        for role in list(pv.role):
            role.permissions.remove(pv)
        db.session.delete(pv)
    db.session.flush()
    obsolete_menu = db.session.query(ViewMenu).filter_by(name=LEGACY_MENU).one_or_none()
    if obsolete_menu is not None and not _permission_views(LEGACY_MENU):
        db.session.delete(obsolete_menu)

    if granted or legacy:
        db.session.commit()
        logger.info(
            "Upload file: %d grant(s) of '%s', %d obsolete permission(s) removed",
            granted,
            PERMISSION,
            len(legacy),
        )
