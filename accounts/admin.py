from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import SellerProfile, User


class SellerProfileInline(admin.StackedInline):
    model = SellerProfile
    extra = 0
    can_delete = False
    max_num = 1


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("phone",)

    list_display = (
        "phone",
        "display_name",
        "is_staff",
        "is_active",
        "is_phone_verified",
        "date_joined",
    )

    list_filter = ("is_active", "is_staff", "is_phone_verified")

    search_fields = ("phone", "display_name", "email")

    readonly_fields = ("date_joined", "updated_at")

    inlines = [SellerProfileInline]

    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        (
            "Profile",
            {"fields": ("display_name", "email", "is_phone_verified")},
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        (
            "Important dates",
            {"fields": ("last_login", "date_joined", "updated_at")},
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "display_name", "password1", "password2"),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ("phone",)
        return self.readonly_fields

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("seller_profile")


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("seller_code", "user", "business_name", "is_active")
    list_filter = ("is_active",)
    search_fields = (
        "seller_code",
        "business_name",
        "user__phone",
        "user__display_name",
    )
