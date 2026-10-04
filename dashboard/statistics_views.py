"""Read-only administrative statistics endpoints.

GET /dashboard/stats/overview/
GET /dashboard/stats/timeline/
GET /dashboard/stats/rankings/
GET /dashboard/stats/distributions/

Views only validate filters, resolve the scope and render the result; every
query lives in dashboard.statistics_queries. These replace the legacy
GET /dashboard/stats/ (DashboardStatsView), which relies on BorrowedBook.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.views import APIView

from accounts.permissions import IsLibrarian
from Bookshelf.api_responses import ArabicApiResponseMixin
from Bookshelf.openapi import error_response, success_envelope

from . import statistics_queries as queries
from .statistics_serializers import (
    DistributionsSerializer,
    OverviewSerializer,
    RankingsSerializer,
    TimelineSerializer,
)


SCOPE_DESCRIPTION = (
    "متاح لـSUPERUSER وMINISTRY_ADMIN وGOVERNORATE_ADMIN وLIBRARIAN؛ READER ممنوع (403). "
    "النطاق: SUPERUSER وMINISTRY_ADMIN مستوى الوزارة ويمكنهما التضييق بـgovernorate أو library؛ "
    "GOVERNORATE_ADMIN محافظته ويمكنه التضييق بـlibrary ضمن محافظته؛ LIBRARIAN مكتبته فقط. "
    "الفلاتر تضيّق ولا توسّع: وحدة خارج النطاق تُعاد NOT_FOUND، وlibrary لا تتبع governorate "
    "المحددة تُرفض بـVALIDATION_ERROR. الإحصائيات إدارية: تشمل الكتب المؤرشفة والمكتبات والمحافظات "
    "غير المفعّلة وتاريخها. الفترة: period=7d|30d (الافتراضي 30d) أو date_from وdate_to معاً "
    f"(YYYY-MM-DD، بحد أقصى {queries.MAX_CUSTOM_RANGE_DAYS} يوماً، وdate_to لا يتجاوز اليوم)، "
    "ولا يُجمع بين الطريقتين. "
    "الأيام بتوقيت المشروع. يعيد كل endpoint النطاق والفترة المحسومة."
)

COMMON_PARAMETERS = [
    OpenApiParameter(
        name="period", type=str, required=False, enum=list(queries.PERIOD_DAYS),
        description="الفترة النسبية المنتهية اليوم. الافتراضي 30d.",
    ),
    OpenApiParameter(
        name="date_from", type=str, required=False,
        description="بداية فترة مخصصة YYYY-MM-DD (مع date_to).",
    ),
    OpenApiParameter(
        name="date_to", type=str, required=False,
        description=(
            "نهاية فترة مخصصة YYYY-MM-DD شاملة (مع date_from). "
            "لا يمكن أن يكون في المستقبل (بعد اليوم بتوقيت المشروع)."
        ),
    ),
    OpenApiParameter(
        name="governorate", type=int, required=False,
        description="معرّف المحافظة (للوزارة؛ لمسؤول المحافظة يقبل محافظته فقط).",
    ),
    OpenApiParameter(
        name="library", type=int, required=False,
        description="معرّف المكتبة ضمن النطاق (لأمين المكتبة يقبل مكتبته فقط).",
    ),
]

LIMIT_PARAMETER = OpenApiParameter(
    name="limit", type=int, required=False,
    description=(
        f"عدد العناصر في كل ترتيب. الافتراضي {queries.DEFAULT_RANKING_LIMIT} "
        f"والحد الأقصى {queries.MAX_RANKING_LIMIT}."
    ),
)

COMMON_ERRORS = {
    400: error_response("VALIDATION_ERROR لفلتر أو فترة غير صالحة أو فلاتر متناقضة."),
    401: error_response("AUTHENTICATION_REQUIRED أو INVALID_TOKEN."),
    403: error_response("PERMISSION_DENIED للقارئ أو لمستخدم بلا دور صالح."),
    404: error_response("NOT_FOUND لمحافظة أو مكتبة غير موجودة أو خارج النطاق."),
    429: error_response("THROTTLED."),
}


class DashboardStatisticsView(ArabicApiResponseMixin, APIView):
    """Shared filters, scope and response handling for the statistics endpoints."""

    permission_classes = [IsLibrarian]
    http_method_names = ["get", "head", "options"]
    output_serializer_class = None
    success_code = None
    success_message = None

    def build(self, scope, period):
        raise NotImplementedError

    def get(self, request):
        period = queries.parse_stats_period(request.query_params)
        scope = queries.resolve_dashboard_scope(request.user, request.query_params)
        data = self.output_serializer_class(self.build(scope, period)).data
        return self.success_response(data, self.success_code, self.success_message)


def _schema(operation_id, summary, description, serializer, envelope, code, extra=()):
    return extend_schema(
        tags=["Dashboard Statistics"],
        operation_id=operation_id,
        summary=summary,
        description=f"{description} {SCOPE_DESCRIPTION}",
        parameters=[*COMMON_PARAMETERS, *extra],
        responses={200: success_envelope(envelope, serializer(), [code]), **COMMON_ERRORS},
    )


class DashboardOverviewView(DashboardStatisticsView):
    output_serializer_class = OverviewSerializer
    success_code = "DASHBOARD_OVERVIEW_RETRIEVED"
    success_message = "تم جلب ملخص لوحة الإحصائيات بنجاح."

    def build(self, scope, period):
        return queries.build_overview(scope, period)

    @_schema(
        "dashboard_stats_overview",
        "ملخص لوحة الإحصائيات",
        "أقسام current لقطة للحالة الحالية ولا تتأثر بالفترة؛ أقسام period نشاط الفترة المختارة. "
        "organization على مستوى الوزارة يشمل المحافظات والمكتبات، وعلى مستوى المحافظة المكتبات فقط، "
        "وnull على مستوى المكتبة. حقول القرّاء في users (readers_basis وreaders_count "
        "وactive/inactive_readers_count وborrowing_blocked_readers_count) null على مستوى المكتبة "
        "لأن القارئ يتبع المحافظة؛ أرقام أمناء المكتبة تبقى. borrowed_copies من المخزون (total - available) وactive_borrows "
        "من سجلات Borrow النشطة، وهما مقياسان منفصلان. approval_rate وrejection_rate من "
        "القرارات خلال الفترة فقط (دون PENDING)، و0 عند عدم وجود قرارات.",
        OverviewSerializer,
        "DashboardOverviewSuccessEnvelope",
        "DASHBOARD_OVERVIEW_RETRIEVED",
    )
    def get(self, request):
        return super().get(request)


class DashboardTimelineView(DashboardStatisticsView):
    output_serializer_class = TimelineSerializer
    success_code = "DASHBOARD_TIMELINE_RETRIEVED"
    success_message = "تم جلب السلسلة الزمنية للإحصائيات بنجاح."

    def build(self, scope, period):
        return queries.build_timeline(scope, period)

    @_schema(
        "dashboard_stats_timeline",
        "السلسلة الزمنية اليومية",
        "عنصر لكل يوم في الفترة (والأيام بلا نشاط بقيم 0). borrows بحسب borrowed_at، returns بحسب "
        "returned_at، requests بحسب created_at، approved/rejected_requests بحسب decided_at.",
        TimelineSerializer,
        "DashboardTimelineSuccessEnvelope",
        "DASHBOARD_TIMELINE_RETRIEVED",
    )
    def get(self, request):
        return super().get(request)


class DashboardRankingsView(DashboardStatisticsView):
    output_serializer_class = RankingsSerializer
    success_code = "DASHBOARD_RANKINGS_RETRIEVED"
    success_message = "تم جلب ترتيبات الإحصائيات بنجاح."

    def build(self, scope, period):
        limit = queries.parse_ranking_limit(self.request.query_params)
        return queries.build_rankings(scope, period, limit)

    @_schema(
        "dashboard_stats_rankings",
        "الترتيبات (الأكثر استعارة وطلباً وتفضيلاً ونشاطاً)",
        "most_borrowed_books عدد سجلات Borrow المنشأة خلال الفترة لكل كتاب؛ most_requested_books "
        "عدد BorrowRequest المنشأة خلال الفترة؛ most_favorited_books كل المفضلة (LIFETIME) ولا "
        "يتأثر بالفترة؛ most_active_libraries وmost_active_governorates عدد سجلات Borrow خلال "
        "الفترة. most_active_libraries فارغة على مستوى المكتبة، وmost_active_governorates على "
        "مستوى الوزارة فقط. التعادل يُرتب بالمعرّف تصاعدياً.",
        RankingsSerializer,
        "DashboardRankingsSuccessEnvelope",
        "DASHBOARD_RANKINGS_RETRIEVED",
        extra=[LIMIT_PARAMETER],
    )
    def get(self, request):
        return super().get(request)


class DashboardDistributionsView(DashboardStatisticsView):
    output_serializer_class = DistributionsSerializer
    success_code = "DASHBOARD_DISTRIBUTIONS_RETRIEVED"
    success_message = "تم جلب توزيعات الإحصائيات بنجاح."

    def build(self, scope, period):
        return queries.build_distributions(scope, period)

    @_schema(
        "dashboard_stats_distributions",
        "التوزيع حسب المحافظات أو المكتبات",
        "مستوى الوزارة: governorates لكل المحافظات (بما فيها غير المفعّلة) وlibraries فارغة. "
        "مستوى المحافظة: libraries لكل مكتبات المحافظة وgovernorates فارغة. مستوى المكتبة: "
        "كلاهما فارغ. active_borrows_count لقطة حالية وperiod_borrows_count خلال الفترة. "
        "لا يوجد توزيع للقرّاء حسب المكتبة لأن القارئ يتبع المحافظة.",
        DistributionsSerializer,
        "DashboardDistributionsSuccessEnvelope",
        "DASHBOARD_DISTRIBUTIONS_RETRIEVED",
    )
    def get(self, request):
        return super().get(request)
