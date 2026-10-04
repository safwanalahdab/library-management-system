"""Output serializers for the statistics dashboard.

They render the dictionaries built by dashboard.statistics_queries and document
the response contract in Swagger. Every count is an integer (never null) and
every rate a float; sections that do not apply to a level are empty arrays.
"""

from rest_framework import serializers

from .statistics_queries import CUSTOM_PERIOD, GOVERNORATE, LIBRARY, MINISTRY, PERIOD_DAYS


class ScopeUnitSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_active = serializers.BooleanField()


class ScopeSerializer(serializers.Serializer):
    level = serializers.ChoiceField(choices=[MINISTRY, GOVERNORATE, LIBRARY])
    governorate = ScopeUnitSerializer(allow_null=True)
    library = ScopeUnitSerializer(allow_null=True)


class PeriodSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=[*PERIOD_DAYS, CUSTOM_PERIOD])
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    days = serializers.IntegerField(help_text="عدد الأيام شاملاً الطرفين.")
    timezone = serializers.CharField()


class StatsHeaderSerializer(serializers.Serializer):
    scope = ScopeSerializer()
    period = PeriodSerializer()


# Overview


class OrganizationSerializer(serializers.Serializer):
    """Snapshot. Governorate counts exist at MINISTRY level only."""

    governorates_count = serializers.IntegerField(required=False)
    active_governorates_count = serializers.IntegerField(required=False)
    inactive_governorates_count = serializers.IntegerField(required=False)
    libraries_count = serializers.IntegerField()
    active_libraries_count = serializers.IntegerField()
    inactive_libraries_count = serializers.IntegerField()


READER_NOT_APPLICABLE = "null على مستوى المكتبة: القارئ يتبع المحافظة لا المكتبة (غير قابل للتعريف، وليس صفراً)."


class UsersSerializer(serializers.Serializer):
    """Snapshot. Reader metrics are null at LIBRARY level (not applicable)."""

    readers_basis = serializers.ChoiceField(
        choices=["SYSTEM", GOVERNORATE], allow_null=True, help_text=READER_NOT_APPLICABLE
    )
    readers_count = serializers.IntegerField(allow_null=True, help_text=READER_NOT_APPLICABLE)
    active_readers_count = serializers.IntegerField(allow_null=True, help_text=READER_NOT_APPLICABLE)
    inactive_readers_count = serializers.IntegerField(allow_null=True, help_text=READER_NOT_APPLICABLE)
    borrowing_blocked_readers_count = serializers.IntegerField(
        allow_null=True, help_text=READER_NOT_APPLICABLE
    )
    librarians_count = serializers.IntegerField()
    active_librarians_count = serializers.IntegerField()
    inactive_librarians_count = serializers.IntegerField()


class CatalogSerializer(serializers.Serializer):
    """Snapshot."""

    books_count = serializers.IntegerField()
    active_books_count = serializers.IntegerField(help_text="غير المؤرشفة.")
    archived_books_count = serializers.IntegerField()
    total_copies = serializers.IntegerField()
    available_copies = serializers.IntegerField()
    borrowed_copies = serializers.IntegerField(
        help_text="SUM(total_copies - available_copies): حالة المخزون الحالية."
    )
    unavailable_books_count = serializers.IntegerField(
        help_text="كتب غير مؤرشفة لا تتوفر منها أي نسخة."
    )
    authors_count = serializers.IntegerField(help_text="مؤلفون مختلفون مستخدمون في كتب النطاق.")
    categories_count = serializers.IntegerField(help_text="تصنيفات مختلفة مستخدمة في كتب النطاق.")


class BorrowingCurrentSerializer(serializers.Serializer):
    active_borrows = serializers.IntegerField()
    returned_borrows_total = serializers.IntegerField()


class BorrowingPeriodSerializer(serializers.Serializer):
    borrows_created = serializers.IntegerField(help_text="بحسب borrowed_at.")
    direct_borrows = serializers.IntegerField(help_text="request IS NULL.")
    request_borrows = serializers.IntegerField(help_text="request IS NOT NULL.")
    returns = serializers.IntegerField(help_text="بحسب returned_at.")


class BorrowingSerializer(serializers.Serializer):
    current = BorrowingCurrentSerializer()
    period = BorrowingPeriodSerializer()


class RequestsCurrentSerializer(serializers.Serializer):
    pending_requests = serializers.IntegerField()


class RequestsPeriodSerializer(serializers.Serializer):
    requests_created = serializers.IntegerField(help_text="بحسب created_at.")
    approved_requests = serializers.IntegerField(help_text="بحسب decided_at.")
    rejected_requests = serializers.IntegerField(help_text="بحسب decided_at.")
    decided_requests = serializers.IntegerField(help_text="approved + rejected.")
    approval_rate = serializers.FloatField(help_text="approved / decided * 100، و0 عند عدم وجود قرارات.")
    rejection_rate = serializers.FloatField(help_text="rejected / decided * 100، و0 عند عدم وجود قرارات.")


class RequestsSerializer(serializers.Serializer):
    current = RequestsCurrentSerializer()
    period = RequestsPeriodSerializer()


class FavoritesCurrentSerializer(serializers.Serializer):
    favorites_count = serializers.IntegerField(help_text="كل سجلات المفضلة لكتب النطاق، والمؤرشفة منها.")


class FavoritesPeriodSerializer(serializers.Serializer):
    favorites_added = serializers.IntegerField(help_text="بحسب created_at.")


class FavoritesSerializer(serializers.Serializer):
    current = FavoritesCurrentSerializer()
    period = FavoritesPeriodSerializer()


class OverviewSerializer(StatsHeaderSerializer):
    organization = OrganizationSerializer(
        allow_null=True, help_text="null على مستوى المكتبة؛ scope يكفي."
    )
    users = UsersSerializer()
    catalog = CatalogSerializer()
    borrowing = BorrowingSerializer()
    requests = RequestsSerializer()
    favorites = FavoritesSerializer()


# Timeline


class TimelinePointSerializer(serializers.Serializer):
    date = serializers.DateField()
    borrows = serializers.IntegerField()
    returns = serializers.IntegerField()
    requests = serializers.IntegerField()
    approved_requests = serializers.IntegerField()
    rejected_requests = serializers.IntegerField()


class TimelineSerializer(StatsHeaderSerializer):
    series = TimelinePointSerializer(many=True)


# Rankings


class RankedBookSerializer(serializers.Serializer):
    book_id = serializers.IntegerField()
    title = serializers.CharField()
    library_id = serializers.IntegerField()
    library_name = serializers.CharField()
    count = serializers.IntegerField()


class RankedLibrarySerializer(serializers.Serializer):
    library_id = serializers.IntegerField()
    library_name = serializers.CharField()
    governorate_id = serializers.IntegerField()
    governorate_name = serializers.CharField()
    borrows_count = serializers.IntegerField()


class RankedGovernorateSerializer(serializers.Serializer):
    governorate_id = serializers.IntegerField()
    governorate_name = serializers.CharField()
    borrows_count = serializers.IntegerField()


class RankingsSerializer(StatsHeaderSerializer):
    limit = serializers.IntegerField()
    favorites_window = serializers.ChoiceField(
        choices=["LIFETIME"], help_text="most_favorited_books لا يتأثر بالفترة."
    )
    most_borrowed_books = RankedBookSerializer(many=True)
    most_requested_books = RankedBookSerializer(many=True)
    most_favorited_books = RankedBookSerializer(many=True)
    most_active_libraries = RankedLibrarySerializer(
        many=True, help_text="فارغة على مستوى المكتبة."
    )
    most_active_governorates = RankedGovernorateSerializer(
        many=True, help_text="على مستوى الوزارة فقط؛ فارغة لغيره."
    )


# Distributions


class GovernorateDistributionSerializer(serializers.Serializer):
    governorate_id = serializers.IntegerField()
    governorate_name = serializers.CharField()
    is_active = serializers.BooleanField()
    libraries_count = serializers.IntegerField()
    readers_count = serializers.IntegerField()
    books_count = serializers.IntegerField()
    active_borrows_count = serializers.IntegerField()
    period_borrows_count = serializers.IntegerField()


class LibraryDistributionSerializer(serializers.Serializer):
    library_id = serializers.IntegerField()
    library_name = serializers.CharField()
    is_active = serializers.BooleanField()
    books_count = serializers.IntegerField()
    librarians_count = serializers.IntegerField()
    active_borrows_count = serializers.IntegerField()
    period_borrows_count = serializers.IntegerField()


class DistributionsSerializer(StatsHeaderSerializer):
    governorates = GovernorateDistributionSerializer(
        many=True, help_text="على مستوى الوزارة فقط؛ فارغة لغيره."
    )
    libraries = LibraryDistributionSerializer(
        many=True, help_text="على مستوى المحافظة فقط؛ فارغة لغيره."
    )
