from django.db.models import Q

from books.models import Book

from .models import CustomUser, Library


BUSINESS_ROLES = frozenset(CustomUser.Role.values)


def is_authenticated_user(user):
    return bool(user and user.is_authenticated)


def is_superuser(user):
    return is_authenticated_user(user) and user.is_superuser


def get_effective_governorate(user):
    if not is_authenticated_user(user):
        return None
    if user.governorate_id is not None:
        return user.governorate
    if user.library_id is not None:
        return user.library.governorate
    return None


def get_effective_governorate_id(user):
    if not is_authenticated_user(user):
        return None
    if user.governorate_id is not None:
        return user.governorate_id
    if user.library_id is not None:
        return user.library.governorate_id
    return None


def get_effective_library(user):
    if not is_authenticated_user(user) or user.library_id is None:
        return None
    return user.library


def can_access_governorate(user, governorate):
    if not is_authenticated_user(user) or governorate is None:
        return False
    if is_superuser(user) or user.role == CustomUser.Role.MINISTRY_ADMIN:
        return True
    if user.role in {CustomUser.Role.GOVERNORATE_ADMIN, CustomUser.Role.READER}:
        return user.governorate_id == governorate.pk
    if user.role == CustomUser.Role.LIBRARIAN:
        return get_effective_governorate_id(user) == governorate.pk
    return False


def can_access_library(user, library):
    if not is_authenticated_user(user) or library is None:
        return False
    if is_superuser(user) or user.role == CustomUser.Role.MINISTRY_ADMIN:
        return True
    if user.role == CustomUser.Role.GOVERNORATE_ADMIN:
        return user.governorate_id == library.governorate_id
    if user.role == CustomUser.Role.LIBRARIAN:
        return user.library_id == library.pk
    return False


def can_access_user(actor, target):
    if not is_authenticated_user(actor) or target is None:
        return False
    if actor.pk is not None and actor.pk == target.pk:
        return True
    if is_superuser(actor):
        return True
    if target.is_superuser:
        return False

    if actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return target.role in BUSINESS_ROLES

    if actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
        if target.role not in {
            CustomUser.Role.GOVERNORATE_ADMIN,
            CustomUser.Role.LIBRARIAN,
            CustomUser.Role.READER,
        }:
            return False
        target_governorate = get_effective_governorate(target)
        return (
            target_governorate is not None
            and actor.governorate_id == target_governorate.pk
        )

    # Librarians and readers only reach their own account here. Librarians
    # find readers through readers_searchable_by(), which exposes limited data.
    return False


def libraries_accessible_to(actor):
    """Return the library queryset visible to an actor under the business scope rules."""
    queryset = Library.objects.all()
    if not is_authenticated_user(actor):
        return queryset.none()
    if is_superuser(actor) or actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return queryset
    if actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
        if actor.governorate_id is None:
            return queryset.none()
        return queryset.filter(governorate_id=actor.governorate_id)
    if actor.role == CustomUser.Role.LIBRARIAN:
        if actor.library_id is None:
            return queryset.none()
        return queryset.filter(pk=actor.library_id)
    if actor.role == CustomUser.Role.READER:
        if actor.governorate_id is None:
            return queryset.none()
        return queryset.filter(governorate_id=actor.governorate_id, is_active=True)
    return queryset.none()


def books_accessible_to(actor):
    """Return the book queryset visible to an actor under the business scope rules.

    Admin roles see archived books and books in inactive libraries inside their
    scope. Readers see only non-archived books in active libraries of their own
    active governorate.
    """
    if (
        is_authenticated_user(actor)
        and not is_superuser(actor)
        and actor.role == CustomUser.Role.READER
    ):
        if actor.governorate_id is None:
            return Book.objects.none()
        return Book.objects.filter(
            library__governorate_id=actor.governorate_id,
            library__governorate__is_active=True,
            library__is_active=True,
            is_archived=False,
        )
    return books_manageable_by(actor)


def books_manageable_by(actor):
    """Return the books an actor may update, archive or restore.

    Same organizational scope as the admin read scope, including archived books
    and inactive libraries. Readers manage no books.
    """
    queryset = Book.objects.all()
    if not is_authenticated_user(actor):
        return queryset.none()
    if is_superuser(actor) or actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return queryset
    if actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
        if actor.governorate_id is None:
            return queryset.none()
        return queryset.filter(library__governorate_id=actor.governorate_id)
    if actor.role == CustomUser.Role.LIBRARIAN:
        if actor.library_id is None:
            return queryset.none()
        return queryset.filter(library_id=actor.library_id)
    return queryset.none()


def borrowing_records_visible_to(actor, queryset):
    """Scope a BorrowRequest or Borrow queryset (both have `reader` and `book`).

    Readers see their own records. Operators see records of books they manage:
    librarians their library, governorate admins their governorate, ministry
    admins and superusers everything.
    """
    if not is_authenticated_user(actor):
        return queryset.none()
    if is_superuser(actor) or actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return queryset
    if actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
        if actor.governorate_id is None:
            return queryset.none()
        return queryset.filter(book__library__governorate_id=actor.governorate_id)
    if actor.role == CustomUser.Role.LIBRARIAN:
        if actor.library_id is None:
            return queryset.none()
        return queryset.filter(book__library_id=actor.library_id)
    if actor.role == CustomUser.Role.READER:
        return queryset.filter(reader_id=actor.pk)
    return queryset.none()


def users_accessible_to(actor):
    """Return the user queryset visible to an actor under the business scope rules."""
    queryset = CustomUser.objects.all()
    if not is_authenticated_user(actor):
        return queryset.none()
    if is_superuser(actor):
        return queryset
    if actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return queryset.filter(is_superuser=False, role__in=BUSINESS_ROLES)
    if actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
        return queryset.filter(is_superuser=False).filter(
            Q(pk=actor.pk)
            | Q(
                role=CustomUser.Role.GOVERNORATE_ADMIN,
                governorate_id=actor.governorate_id,
            )
            | Q(
                role=CustomUser.Role.LIBRARIAN,
                library__governorate_id=actor.governorate_id,
            )
            | Q(
                role=CustomUser.Role.READER,
                governorate_id=actor.governorate_id,
            )
        )
    return queryset.filter(pk=actor.pk)


def readers_searchable_by(actor):
    """Active readers an actor may look up when selecting a borrower."""
    queryset = CustomUser.objects.filter(
        role=CustomUser.Role.READER,
        is_superuser=False,
        is_active=True,
    )
    if not is_authenticated_user(actor):
        return queryset.none()
    if is_superuser(actor) or actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return queryset
    if actor.role in {CustomUser.Role.GOVERNORATE_ADMIN, CustomUser.Role.LIBRARIAN}:
        governorate_id = get_effective_governorate_id(actor)
        if governorate_id is None:
            return queryset.none()
        return queryset.filter(governorate_id=governorate_id)
    return queryset.none()


def is_active_governorate(governorate):
    return governorate is not None and governorate.is_active


def is_active_library(library):
    return (
        library is not None
        and library.is_active
        and library.governorate.is_active
    )


def can_manage_user_status(actor, target):
    """Return whether actor may deactivate/reactivate this business account."""
    if (
        not is_authenticated_user(actor)
        or target is None
        or target.is_superuser
        or actor.pk == target.pk
    ):
        return False
    if is_superuser(actor):
        return target.role in BUSINESS_ROLES
    if actor.role == CustomUser.Role.MINISTRY_ADMIN:
        return target.role in {
            CustomUser.Role.GOVERNORATE_ADMIN,
            CustomUser.Role.LIBRARIAN,
            CustomUser.Role.READER,
        }
    if actor.role == CustomUser.Role.GOVERNORATE_ADMIN:
        return can_access_user(actor, target) and target.role in {
            CustomUser.Role.LIBRARIAN,
            CustomUser.Role.READER,
        }
    return False


def has_active_user_scope(user):
    """Return whether the organizational scope required by a business role is active."""
    if user.role == CustomUser.Role.MINISTRY_ADMIN:
        return user.governorate_id is None and user.library_id is None
    if user.role == CustomUser.Role.GOVERNORATE_ADMIN:
        return user.library_id is None and is_active_governorate(user.governorate)
    if user.role == CustomUser.Role.LIBRARIAN:
        return user.governorate_id is None and is_active_library(user.library)
    if user.role == CustomUser.Role.READER:
        return user.library_id is None and is_active_governorate(user.governorate)
    return False
