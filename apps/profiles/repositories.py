"""Data-access layer for profiles. The only place profile ORM queries live."""
from .models import Profile


class ProfileRepository:
    @staticmethod
    def all():
        return Profile.objects.all()

    @staticmethod
    def get(profile_id):
        return Profile.objects.get(pk=profile_id)

    @staticmethod
    def get_or_none(profile_id):
        return Profile.objects.filter(pk=profile_id).first()

    @staticmethod
    def create(**fields):
        return Profile.objects.create(**fields)

    @staticmethod
    def update(profile, **fields):
        for key, value in fields.items():
            setattr(profile, key, value)
        profile.save()
        return profile

    @staticmethod
    def delete(profile):
        profile.delete()
