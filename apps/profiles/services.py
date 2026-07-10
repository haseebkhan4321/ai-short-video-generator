"""Business logic for profiles. Views call these; these call the repository."""
from .repositories import ProfileRepository


class ProfileService:
    @staticmethod
    def list_profiles():
        return ProfileRepository.all()

    @staticmethod
    def get_profile(profile_id):
        return ProfileRepository.get_or_none(profile_id)

    @staticmethod
    def create_profile(data):
        return ProfileRepository.create(
            name=data["name"],
            niche=data.get("niche", ""),
            description=data.get("description", ""),
            style_prompt=data.get("style_prompt", ""),
            elevenlabs_voice_id=data.get("elevenlabs_voice_id", ""),
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
            elevenlabs_voice_id=data.get("elevenlabs_voice_id", ""),
            language=data.get("language", "en"),
        )

    @staticmethod
    def delete_profile(profile):
        ProfileRepository.delete(profile)
