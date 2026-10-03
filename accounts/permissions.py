from rest_framework.permissions import BasePermission

from .models import CustomUser
from .scopes import can_access_user, is_authenticated_user, is_superuser


ROLE_LEVELS = {
    CustomUser.Role.READER: 1,
    CustomUser.Role.LIBRARIAN: 2,
    CustomUser.Role.GOVERNORATE_ADMIN: 3,
    CustomUser.Role.MINISTRY_ADMIN: 4,
}


class HasMinimumBusinessRole(BasePermission):
    required_role = None

    def has_permission(self, request, view):
        user = request.user
        if not is_authenticated_user(user):
            return False
        if is_superuser(user):
            return True

        required_level = ROLE_LEVELS.get(self.required_role)
        user_level = ROLE_LEVELS.get(user.role)
        return (
            required_level is not None
            and user_level is not None
            and user_level >= required_level
        )


class IsSystemAdmin(HasMinimumBusinessRole):
    """Allows Django superusers and ministry administrators."""

    required_role = CustomUser.Role.MINISTRY_ADMIN


class IsGovernorateAdmin(HasMinimumBusinessRole):
    """Allows governorate administrators and higher roles."""

    required_role = CustomUser.Role.GOVERNORATE_ADMIN


class IsLibrarian(HasMinimumBusinessRole):
    """Allows librarians and higher roles."""

    required_role = CustomUser.Role.LIBRARIAN


class IsReader(HasMinimumBusinessRole):
    """Allows every valid business role, plus Django superusers."""

    required_role = CustomUser.Role.READER


class IsReaderRole(BasePermission):
    """Allows readers only; superusers and staff roles act on behalf of readers elsewhere."""

    def has_permission(self, request, view):
        user = request.user
        return (
            is_authenticated_user(user)
            and not is_superuser(user)
            and user.role == CustomUser.Role.READER
        )


class CanAccessUser(BasePermission):
    """Applies the centralized actor-to-user scope rule to a user object."""

    def has_permission(self, request, view):
        return is_authenticated_user(request.user)

    def has_object_permission(self, request, view, obj):
        return can_access_user(request.user, obj)


class CanResetUserPassword(BasePermission):
    """Allow password resets by ministry and governorate admins for in-scope accounts."""

    def has_permission(self, request, view):
        user = request.user
        return is_authenticated_user(user) and (
            is_superuser(user)
            or user.role
            in {
                CustomUser.Role.MINISTRY_ADMIN,
                CustomUser.Role.GOVERNORATE_ADMIN,
            }
        )

    def has_object_permission(self, request, view, target):
        actor = request.user
        if actor.pk == target.pk or target.is_superuser:
            return False
        if is_superuser(actor):
            return target.role in CustomUser.Role.values
        if actor.role == CustomUser.Role.MINISTRY_ADMIN:
            return target.role in CustomUser.Role.values
        if actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
            return can_access_user(actor, target) and target.role in {
                CustomUser.Role.LIBRARIAN,
                CustomUser.Role.READER,
            }
        return False
