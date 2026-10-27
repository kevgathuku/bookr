"""Staff catalog: products to sell and the grant (sale) endpoint."""

from typing import ClassVar

from django.contrib.auth import get_user_model
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.permissions import IsStaffOrReadOnly, IsVenueMember
from passes.models import PassProduct
from passes.services import issue_pass
from passes.views import MemberPassSerializer

User = get_user_model()


class PassProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = PassProduct
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "name",
            "credits_total",
            "validity_days",
            "applicable_class_types",
            "transferable",
        ]


class PassProductViewSet(viewsets.ModelViewSet):
    """Staff catalog. No DELETE: issued passes PROTECT their product."""

    serializer_class = PassProductSerializer
    permission_classes: ClassVar[list] = [IsVenueMember, IsStaffOrReadOnly]
    http_method_names: ClassVar[list[str]] = [
        "get",
        "post",
        "patch",
        "head",
        "options",
    ]

    def get_queryset(self):
        return PassProduct.objects.for_venue(self.request.venue).prefetch_related(
            "applicable_class_types"
        )

    def perform_create(self, serializer):
        if serializer.validated_data["venue"] != self.request.venue:
            raise NotFound("No such venue.")
        serializer.save()

    def perform_update(self, serializer):
        if serializer.instance.venue != self.request.venue:
            raise NotFound("No such venue.")
        serializer.save()


class GrantSerializer(serializers.Serializer):
    member = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=PassProduct.objects.all())


class GrantView(APIView):
    """Staff sale: issue a pass + purchase ledger row."""

    permission_classes: ClassVar[list] = [IsVenueMember, IsStaffOrReadOnly]

    def post(self, request):
        form = GrantSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        product = form.validated_data["product"]
        if product.venue != request.venue:
            raise NotFound("No such venue.")
        member_pass = issue_pass(form.validated_data["member"], product)
        return Response(MemberPassSerializer(member_pass).data, status=201)
