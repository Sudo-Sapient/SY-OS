"""Roles and permission checks. Admin may do everything; every other role is a Django group of the same name."""

from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

ADMIN, DATA_ENTRY, FABRIC, CUTTING, SUPERVISOR = "Admin", "Data entry", "Fabric in-charge", "Cutting in-charge", "Supervisor"


def role(user):
    if user.is_superuser:
        return ADMIN
    g = user.groups.first()
    return g.name if g else ""


def roles(*allowed):
    """Server-side role check; Admin may do everything."""

    def deco(view):
        @wraps(view)
        @login_required
        def inner(request, *a, **kw):
            if role(request.user) not in (ADMIN, *allowed):
                raise PermissionDenied
            return view(request, *a, **kw)

        return inner

    return deco


def nav_context(request):
    if not request.user.is_authenticated:
        return {"demo_mode": settings.DEMO_MODE}
    r = role(request.user)
    return {
        "user_role": r,
        "is_admin": r == ADMIN,
        "can_edit_orders": r in (ADMIN, DATA_ENTRY),
        "can_edit_fabric": r in (ADMIN, FABRIC),
    }


def stamp(obj, request):
    if not obj.pk:
        obj.created_by = request.user
    return obj


def can_post(request, *allowed):
    """Anyone logged in may look; only these roles (and Admin) may save."""
    if request.method == "POST" and role(request.user) not in (ADMIN, *allowed):
        raise PermissionDenied
