"""Query layer for the administrative statistics dashboard.

Views stay thin: they call parse_stats_period() and resolve_dashboard_scope(),
then one of the build_* functions, which return plain dictionaries.

Performance rules followed by every function here:
- Every number is computed by the database (aggregate/annotate with filtered
  Count/Sum); rows are never loaded into Python to be counted.
- The number of queries per endpoint is fixed. It never depends on how many
  governorates, libraries, books or readers exist: per-unit numbers come from
  one GROUP BY query per dataset, merged in Python by id.
- Only the new borrowing system is used (Borrow, BorrowRequest). The legacy
  BorrowedBook model is never queried.

Scope is organizational, not reader-visible: archived books, inactive libraries
and inactive governorates stay inside the statistics so history is never hidden.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import BigIntegerField, Count, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.models import CustomUser, Governorate, Library
from accounts.scopes import is_superuser
from books.models import Book, Borrow, BorrowRequest, FavoriteBook

from .query_params import parse_id_param


# Levels


MINISTRY = "MINISTRY"
GOVERNORATE = "GOVERNORATE"
LIBRARY = "LIBRARY"

GOVERNORATE_ID_MESSAGE = "يجب أن يكون معرّف المحافظة رقماً صحيحاً موجباً."
LIBRARY_ID_MESSAGE = "يجب أن يكون معرّف المكتبة رقماً صحيحاً موجباً."
CONTRADICTING_FILTERS_MESSAGE = "المكتبة المحددة لا تتبع المحافظة المحددة."
SCOPE_NOT_FOUND = "النطاق المطلوب غير موجود."


# Period


PERIOD_DAYS = {"7d": 7, "30d": 30}
DEFAULT_PERIOD = "30d"
CUSTOM_PERIOD = "custom"
MAX_CUSTOM_RANGE_DAYS = 366
DATE_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True)
class StatsPeriod:
    """An inclusive range of local calendar days."""

    type: str
    date_from: date
    date_to: date

    @property
    def days(self):
        return (self.date_to - self.date_from).days + 1

    @property
    def start(self):
        """Aware start of date_from in the current timezone (inclusive)."""
        return timezone.make_aware(datetime.combine(self.date_from, time.min))

    @property
    def end(self):
        """Aware start of the day after date_to (exclusive)."""
        return timezone.make_aware(
            datetime.combine(self.date_to + timedelta(days=1), time.min)
        )

    def q(self, field):
        """Half-open range filter: index friendly and DST safe."""
        return Q(**{f"{field}__gte": self.start, f"{field}__lt": self.end})

    def dates(self):
        return [self.date_from + timedelta(days=i) for i in range(self.days)]

    def as_dict(self):
        return {
            "type": self.type,
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "days": self.days,
            "timezone": timezone.get_current_timezone_name(),
        }


def _parse_date(params, name):
    value = params.get(name)
    if value in (None, ""):
        raise ValidationError({name: "يجب تحديد date_from وdate_to معاً للفترة المخصصة."})
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except (TypeError, ValueError):
        raise ValidationError({name: "يجب أن يكون التاريخ بصيغة YYYY-MM-DD."})


def parse_stats_period(params):
    """Resolve `period` (7d/30d, default 30d) or a custom date_from/date_to range."""
    period = params.get("period")
    has_custom = any(params.get(name) not in (None, "") for name in ("date_from", "date_to"))

    if has_custom:
        if period not in (None, ""):
            raise ValidationError(
                {"period": "لا يمكن استخدام period مع date_from/date_to معاً."}
            )
        date_from = _parse_date(params, "date_from")
        date_to = _parse_date(params, "date_to")
        # Historical dashboard: no future days (date_from <= date_to covers it).
        if date_to > timezone.localdate():
            raise ValidationError({"date_to": "لا يمكن أن يكون تاريخ النهاية في المستقبل."})
        if date_from > date_to:
            raise ValidationError({"date_from": "يجب ألا يكون date_from بعد date_to."})
        if (date_to - date_from).days + 1 > MAX_CUSTOM_RANGE_DAYS:
            raise ValidationError(
                {"date_to": f"الحد الأقصى للفترة المخصصة {MAX_CUSTOM_RANGE_DAYS} يوماً."}
            )
        return StatsPeriod(CUSTOM_PERIOD, date_from, date_to)

    period = period or DEFAULT_PERIOD
    if period not in PERIOD_DAYS:
        raise ValidationError({"period": "القيم المسموحة: 7d، 30d."})
    today = timezone.localdate()
    return StatsPeriod(period, today - timedelta(days=PERIOD_DAYS[period] - 1), today)


# Limit (rankings)


DEFAULT_RANKING_LIMIT = 5
MAX_RANKING_LIMIT = 10


def parse_ranking_limit(params):
    value = params.get("limit")
    if value in (None, ""):
        return DEFAULT_RANKING_LIMIT
    message = f"يجب أن يكون limit رقماً صحيحاً بين 1 و{MAX_RANKING_LIMIT}."
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ValidationError({"limit": message})
    if not 1 <= limit <= MAX_RANKING_LIMIT:
        raise ValidationError({"limit": message})
    return limit


# Scope


@dataclass(frozen=True)
class DashboardScope:
    """The organizational unit the statistics are computed for.

    Every scoped queryset is built here, so the four endpoints can never apply
    different scope rules.
    """

    level: str
    governorate: Governorate | None = None
    library: Library | None = None

    def book_filter(self, prefix=""):
        """Filter kwargs for a model reaching Book through `prefix` (e.g. "book__")."""
        if self.level == LIBRARY:
            return {f"{prefix}library_id": self.library.pk}
        if self.level == GOVERNORATE:
            return {f"{prefix}library__governorate_id": self.governorate.pk}
        return {}

    def books(self):
        return Book.objects.filter(**self.book_filter())

    def borrows(self):
        return Borrow.objects.filter(**self.book_filter("book__"))

    def borrow_requests(self):
        return BorrowRequest.objects.filter(**self.book_filter("book__"))

    def favorites(self):
        return FavoriteBook.objects.filter(**self.book_filter("book__"))

    def libraries(self):
        if self.level == LIBRARY:
            return Library.objects.filter(pk=self.library.pk)
        if self.level == GOVERNORATE:
            return Library.objects.filter(governorate_id=self.governorate.pk)
        return Library.objects.all()

    def readers_q(self):
        """Readers belong to a governorate, never to a library.

        Not used at library level, where reader metrics are not applicable.
        """
        q = Q(role=CustomUser.Role.READER)
        if self.governorate is not None:
            q &= Q(governorate_id=self.governorate.pk)
        return q

    def librarians_q(self):
        q = Q(role=CustomUser.Role.LIBRARIAN)
        if self.level == LIBRARY:
            q &= Q(library_id=self.library.pk)
        elif self.level == GOVERNORATE:
            q &= Q(library__governorate_id=self.governorate.pk)
        return q

    @property
    def readers_basis(self):
        """SYSTEM or GOVERNORATE; None at library level (no reader metrics)."""
        if self.level == LIBRARY:
            return None
        return "SYSTEM" if self.level == MINISTRY else GOVERNORATE

    def as_dict(self):
        return {
            "level": self.level,
            "governorate": _unit(self.governorate),
            "library": _unit(self.library),
        }


def _unit(obj):
    if obj is None:
        return None
    return {"id": obj.pk, "name": obj.name, "is_active": obj.is_active}


def _get_library(**filters):
    library = Library.objects.select_related("governorate").filter(**filters).first()
    if library is None:
        raise NotFound(SCOPE_NOT_FOUND)
    return library


def resolve_dashboard_scope(user, params):
    """Resolve the actor's scope, narrowed by optional governorate/library filters.

    Filters only narrow: a unit outside the actor's scope is reported as
    NOT_FOUND (its existence is not revealed); a library that does not belong
    to the requested governorate is a VALIDATION_ERROR. At most one query.
    """
    governorate_id = parse_id_param(params, "governorate", GOVERNORATE_ID_MESSAGE)
    library_id = parse_id_param(params, "library", LIBRARY_ID_MESSAGE)

    if is_superuser(user) or user.role == CustomUser.Role.MINISTRY_ADMIN:
        if library_id is not None:
            library = _get_library(pk=library_id)
            if governorate_id is not None and library.governorate_id != governorate_id:
                raise ValidationError({"library": CONTRADICTING_FILTERS_MESSAGE})
            return DashboardScope(LIBRARY, library.governorate, library)
        if governorate_id is not None:
            governorate = Governorate.objects.filter(pk=governorate_id).first()
            if governorate is None:
                raise NotFound(SCOPE_NOT_FOUND)
            return DashboardScope(GOVERNORATE, governorate)
        return DashboardScope(MINISTRY)

    if user.role == CustomUser.Role.GOVERNORATE_ADMIN:
        if governorate_id is not None and governorate_id != user.governorate_id:
            raise NotFound(SCOPE_NOT_FOUND)
        if library_id is not None:
            library = _get_library(pk=library_id, governorate_id=user.governorate_id)
            return DashboardScope(LIBRARY, library.governorate, library)
        governorate = Governorate.objects.filter(pk=user.governorate_id).first()
        if governorate is None:
            raise NotFound(SCOPE_NOT_FOUND)
        return DashboardScope(GOVERNORATE, governorate)

    if user.role == CustomUser.Role.LIBRARIAN:
        if library_id is not None and library_id != user.library_id:
            raise NotFound(SCOPE_NOT_FOUND)
        library = _get_library(pk=user.library_id)
        if governorate_id is not None and governorate_id != library.governorate_id:
            raise NotFound(SCOPE_NOT_FOUND)
        return DashboardScope(LIBRARY, library.governorate, library)

    raise PermissionDenied()


# Helpers


def _count(q=None):
    return Count("pk", filter=q)


def _sum(expression):
    return Coalesce(Sum(expression), Value(0), output_field=BigIntegerField())


def _rate(part, whole):
    return round(part * 100 / whole, 2) if whole else 0.0


def _header(scope, period):
    return {"scope": scope.as_dict(), "period": period.as_dict()}


# Overview


def _organization(scope):
    """Current organizational counts; none at library level (scope says it all)."""
    if scope.level == LIBRARY:
        return None
    data = scope.libraries().aggregate(
        libraries_count=_count(),
        active_libraries_count=_count(Q(is_active=True)),
        inactive_libraries_count=_count(Q(is_active=False)),
    )
    if scope.level == MINISTRY:
        data.update(
            Governorate.objects.aggregate(
                governorates_count=_count(),
                active_governorates_count=_count(Q(is_active=True)),
                inactive_governorates_count=_count(Q(is_active=False)),
            )
        )
    return data


READER_METRICS = (
    "readers_count",
    "active_readers_count",
    "inactive_readers_count",
    "borrowing_blocked_readers_count",
)


def _users(scope):
    """One query. Reader metrics are null at library level: readers belong to a
    governorate, so "readers of a library" is undefined (not zero)."""
    librarians = scope.librarians_q()
    aggregates = {
        "librarians_count": _count(librarians),
        "active_librarians_count": _count(librarians & Q(is_active=True)),
        "inactive_librarians_count": _count(librarians & Q(is_active=False)),
    }
    if scope.level == LIBRARY:
        data = CustomUser.objects.filter(is_superuser=False).filter(librarians).aggregate(
            **aggregates
        )
        return {"readers_basis": scope.readers_basis, **dict.fromkeys(READER_METRICS), **data}

    readers = scope.readers_q()
    data = CustomUser.objects.filter(is_superuser=False).filter(readers | librarians).aggregate(
        readers_count=_count(readers),
        active_readers_count=_count(readers & Q(is_active=True)),
        inactive_readers_count=_count(readers & Q(is_active=False)),
        borrowing_blocked_readers_count=_count(readers & Q(borrowing_blocked=True)),
        **aggregates,
    )
    return {"readers_basis": scope.readers_basis, **data}


def _catalog(scope):
    # Copies cover every book in scope, archived included: copies of an
    # archived book can still be out on loan.
    data = scope.books().aggregate(
        books_count=_count(),
        active_books_count=_count(Q(is_archived=False)),
        archived_books_count=_count(Q(is_archived=True)),
        # Aliases may not reuse field names; renamed below.
        copies_total=_sum("total_copies"),
        copies_available=_sum("available_copies"),
        borrowed_copies=_sum(F("total_copies") - F("available_copies")),
        unavailable_books_count=_count(Q(is_archived=False, available_copies=0)),
        authors_count=Count("author", distinct=True),
        categories_count=Count("category", distinct=True),
    )
    data["total_copies"] = data.pop("copies_total")
    data["available_copies"] = data.pop("copies_available")
    return data


def _borrowing(scope, period):
    created = period.q("borrowed_at")
    data = scope.borrows().aggregate(
        active_borrows=_count(Q(status=Borrow.Status.ACTIVE)),
        returned_borrows_total=_count(Q(status=Borrow.Status.RETURNED)),
        borrows_created=_count(created),
        direct_borrows=_count(created & Q(request__isnull=True)),
        request_borrows=_count(created & Q(request__isnull=False)),
        returns=_count(period.q("returned_at")),
    )
    return {
        "current": {
            "active_borrows": data["active_borrows"],
            "returned_borrows_total": data["returned_borrows_total"],
        },
        "period": {
            "borrows_created": data["borrows_created"],
            "direct_borrows": data["direct_borrows"],
            "request_borrows": data["request_borrows"],
            "returns": data["returns"],
        },
    }


def _requests(scope, period):
    decided = period.q("decided_at")
    data = scope.borrow_requests().aggregate(
        pending_requests=_count(Q(status=BorrowRequest.Status.PENDING)),
        requests_created=_count(period.q("created_at")),
        approved_requests=_count(decided & Q(status=BorrowRequest.Status.APPROVED)),
        rejected_requests=_count(decided & Q(status=BorrowRequest.Status.REJECTED)),
    )
    approved = data["approved_requests"]
    rejected = data["rejected_requests"]
    decided_count = approved + rejected
    return {
        "current": {"pending_requests": data["pending_requests"]},
        "period": {
            "requests_created": data["requests_created"],
            "approved_requests": approved,
            "rejected_requests": rejected,
            "decided_requests": decided_count,
            "approval_rate": _rate(approved, decided_count),
            "rejection_rate": _rate(rejected, decided_count),
        },
    }


def _favorites(scope, period):
    # Favorites of archived books stay counted: the book is still in scope.
    data = scope.favorites().aggregate(
        favorites_count=_count(),
        favorites_added=_count(period.q("created_at")),
    )
    return {
        "current": {"favorites_count": data["favorites_count"]},
        "period": {"favorites_added": data["favorites_added"]},
    }


def build_overview(scope, period):
    """At most 7 queries (ministry level); 5 at library level."""
    return {
        **_header(scope, period),
        "organization": _organization(scope),
        "users": _users(scope),
        "catalog": _catalog(scope),
        "borrowing": _borrowing(scope, period),
        "requests": _requests(scope, period),
        "favorites": _favorites(scope, period),
    }


# Timeline


def _daily_counts(queryset, field, **counts):
    """One GROUP BY local day query over `field` inside the period.

    Returns {date: {name: count}} for days with activity only.
    """
    rows = (
        queryset.annotate(day=TruncDate(field))
        .values("day")
        .annotate(**counts)
        .order_by()
    )
    return {row.pop("day"): row for row in rows}


def build_timeline(scope, period):
    """4 queries: one per date field; missing days are filled with zeros in Python."""
    borrows = _daily_counts(
        scope.borrows().filter(period.q("borrowed_at")), "borrowed_at", borrows=_count()
    )
    returns = _daily_counts(
        scope.borrows().filter(period.q("returned_at")), "returned_at", returns=_count()
    )
    requests = _daily_counts(
        scope.borrow_requests().filter(period.q("created_at")),
        "created_at",
        requests=_count(),
    )
    decisions = _daily_counts(
        scope.borrow_requests().filter(
            period.q("decided_at"),
            status__in=[BorrowRequest.Status.APPROVED, BorrowRequest.Status.REJECTED],
        ),
        "decided_at",
        approved_requests=_count(Q(status=BorrowRequest.Status.APPROVED)),
        rejected_requests=_count(Q(status=BorrowRequest.Status.REJECTED)),
    )

    series = []
    for day in period.dates():
        row = {"date": day.isoformat(), "borrows": 0, "returns": 0, "requests": 0,
               "approved_requests": 0, "rejected_requests": 0}
        for source in (borrows, returns, requests, decisions):
            row.update(source.get(day, {}))
        series.append(row)
    return {**_header(scope, period), "series": series}


# Rankings


def _top(queryset, fields, count_name, limit, tie_breaker, plain=()):
    """Top `limit` groups by count; `plain` are real field names, `fields` aliases."""
    return list(
        queryset.values(*plain, **fields)
        .annotate(**{count_name: _count()})
        .order_by(f"-{count_name}", tie_breaker)[:limit]
    )


BOOK_FIELDS = {
    "title": F("book__title"),
    "library_id": F("book__library_id"),
    "library_name": F("book__library__name"),
}


def build_rankings(scope, period, limit):
    """At most 5 queries (ministry level); 3 at library level."""
    borrows_in_period = scope.borrows().filter(period.q("borrowed_at"))

    most_active_libraries = []
    if scope.level != LIBRARY:
        most_active_libraries = _top(
            borrows_in_period,
            {
                "library_id": F("book__library_id"),
                "library_name": F("book__library__name"),
                "governorate_id": F("book__library__governorate_id"),
                "governorate_name": F("book__library__governorate__name"),
            },
            "borrows_count",
            limit,
            "library_id",
        )

    most_active_governorates = []
    if scope.level == MINISTRY:
        most_active_governorates = _top(
            borrows_in_period,
            {
                "governorate_id": F("book__library__governorate_id"),
                "governorate_name": F("book__library__governorate__name"),
            },
            "borrows_count",
            limit,
            "governorate_id",
        )

    return {
        **_header(scope, period),
        "limit": limit,
        "favorites_window": "LIFETIME",
        "most_borrowed_books": _top(
            borrows_in_period, BOOK_FIELDS, "count", limit, "book_id", plain=("book_id",)
        ),
        "most_requested_books": _top(
            scope.borrow_requests().filter(period.q("created_at")),
            BOOK_FIELDS,
            "count",
            limit,
            "book_id",
            plain=("book_id",),
        ),
        "most_favorited_books": _top(
            scope.favorites(), BOOK_FIELDS, "count", limit, "book_id", plain=("book_id",)
        ),
        "most_active_libraries": most_active_libraries,
        "most_active_governorates": most_active_governorates,
    }


# Distributions


def _borrows_by(scope, period, group_field):
    """{unit id: (active, period)} in one GROUP BY query.

    The WHERE clause keeps only rows that can count, so a future index on
    status/borrowed_at can serve it.
    """
    created = period.q("borrowed_at")
    active = Q(status=Borrow.Status.ACTIVE)
    rows = (
        scope.borrows()
        .filter(active | created)
        .values(group_field)
        .annotate(active=_count(active), created=_count(created))
        .order_by()
    )
    return {row[group_field]: (row["active"], row["created"]) for row in rows}


def _counts_by(queryset, group_field):
    return dict(
        queryset.values(group_field).annotate(n=_count()).order_by().values_list(group_field, "n")
    )


def _governorate_distribution(scope, period):
    """4 queries regardless of the number of governorates."""
    governorates = (
        Governorate.objects.values("id", "name", "is_active")
        .annotate(libraries_count=Count("libraries"))
        .order_by("name", "id")
    )
    readers = _counts_by(
        CustomUser.objects.filter(is_superuser=False).filter(scope.readers_q()), "governorate_id"
    )
    books = _counts_by(scope.books(), "library__governorate_id")
    borrows = _borrows_by(scope, period, "book__library__governorate_id")
    return [
        {
            "governorate_id": row["id"],
            "governorate_name": row["name"],
            "is_active": row["is_active"],
            "libraries_count": row["libraries_count"],
            "readers_count": readers.get(row["id"], 0),
            "books_count": books.get(row["id"], 0),
            "active_borrows_count": borrows.get(row["id"], (0, 0))[0],
            "period_borrows_count": borrows.get(row["id"], (0, 0))[1],
        }
        for row in governorates
    ]


def _library_distribution(scope, period):
    """3 queries regardless of the number of libraries."""
    libraries = (
        scope.libraries()
        .values("id", "name", "is_active")
        .annotate(books_count=Count("books"))
        .order_by("name", "id")
    )
    librarians = _counts_by(
        CustomUser.objects.filter(is_superuser=False).filter(scope.librarians_q()), "library_id"
    )
    borrows = _borrows_by(scope, period, "book__library_id")
    return [
        {
            "library_id": row["id"],
            "library_name": row["name"],
            "is_active": row["is_active"],
            "books_count": row["books_count"],
            "librarians_count": librarians.get(row["id"], 0),
            "active_borrows_count": borrows.get(row["id"], (0, 0))[0],
            "period_borrows_count": borrows.get(row["id"], (0, 0))[1],
        }
        for row in libraries
    ]


def build_distributions(scope, period):
    """Ministry: by governorate. Governorate: by library. Library: both empty."""
    return {
        **_header(scope, period),
        "governorates": (
            _governorate_distribution(scope, period) if scope.level == MINISTRY else []
        ),
        "libraries": _library_distribution(scope, period) if scope.level == GOVERNORATE else [],
    }
