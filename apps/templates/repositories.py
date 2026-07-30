"""Data-access layer for templates. The only place template ORM queries live."""
from .models import Template


class TemplateRepository:
    @staticmethod
    def all():
        return Template.objects.all()

    @staticmethod
    def for_account(account):
        """Account-scoped queryset. The web layer always goes through this — a
        template outside the caller's active account must never be reachable."""
        return Template.objects.filter(account=account)

    @staticmethod
    def get(template_id):
        return Template.objects.get(pk=template_id)

    @staticmethod
    def get_or_none(template_id):
        return Template.objects.filter(pk=template_id).first()

    @staticmethod
    def get_in_account(template_id, account):
        return Template.objects.filter(pk=template_id, account=account).first()

    @staticmethod
    def get_by_name(account, name):
        return Template.objects.filter(account=account, name=name).first()

    @staticmethod
    def create(**fields):
        return Template.objects.create(**fields)

    @staticmethod
    def update(template, **fields):
        for key, value in fields.items():
            setattr(template, key, value)
        template.save()
        return template

    @staticmethod
    def delete(template):
        template.delete()
