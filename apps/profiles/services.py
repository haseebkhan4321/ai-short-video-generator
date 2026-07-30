"""Business logic for profiles. Views call these; these call the repository."""
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .repositories import ProfileRepository


class ProfileService:
    @staticmethod
    def list_profiles():
        return ProfileRepository.all()

    @staticmethod
    def list_profiles_with_stats():
        """Profiles annotated with video count and total spend for the list view."""
        return ProfileRepository.all().annotate(
            video_count=Count("videos", distinct=True),
            total_cost=Sum("videos__total_cost_usd"),
        )

    @staticmethod
    def get_profile(profile_id):
        return ProfileRepository.get_or_none(profile_id)

    @staticmethod
    def cost_summary(profile):
        """Aggregate spend and video counts across all of a profile's videos."""
        agg = profile.videos.aggregate(
            total=Sum("total_cost_usd"),
            count=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            failed=Count("id", filter=Q(status="failed")),
        )
        return {
            "total_cost_usd": agg["total"] or Decimal("0"),
            "video_count": agg["count"] or 0,
            "completed_count": agg["completed"] or 0,
            "failed_count": agg["failed"] or 0,
        }

    @staticmethod
    def create_profile(data):
        return ProfileRepository.create(
            name=data["name"],
            niche=data.get("niche", ""),
            description=data.get("description", ""),
            style_prompt=data.get("style_prompt", ""),
            narrator_voice=data.get("narrator_voice", ""),
            language=data.get("language", "en"),
        )

    @staticmethod
    def update_profile(profile, data):
        return ProfileRepository.update(
            profile,
            name=data["name"],
            niche=data.get("niche", ""),
            description=data.get("description", ""),
            style_prompt=data.get("style_prompt", ""),
            narrator_voice=data.get("narrator_voice", ""),
            language=data.get("language", "en"),
        )

    @staticmethod
    def delete_profile(profile):
        ProfileRepository.delete(profile)
