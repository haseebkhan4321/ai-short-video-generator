from django.contrib import admin

from .models import Template


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "account", "niche", "language", "created_at")
    list_filter = ("account", "language")
    search_fields = ("name", "niche")
    list_select_related = ("account",)
