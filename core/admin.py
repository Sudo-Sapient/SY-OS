from django.contrib import admin

from .models import Amendment, Buyer, LotStageUpdate, Party

admin.site.site_header = "SY OS settings"


@admin.register(Buyer)
class BuyerAdmin(admin.ModelAdmin):
    list_display = ("name", "country")


@admin.register(Party)
class PartyAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "in_house", "phone")
    list_filter = ("kind",)


@admin.register(Amendment, LotStageUpdate)
class AuditAdmin(admin.ModelAdmin):
    """Read-only history for the owner."""

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False
