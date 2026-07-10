from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import ProfileForm
from .services import ProfileService


def profile_list(request):
    profiles = ProfileService.list_profiles()
    return render(request, "profiles/list.html", {"profiles": profiles})


def profile_detail(request, profile_id):
    profile = ProfileService.get_profile(profile_id)
    if profile is None:
        raise Http404("Profile not found")
    videos = profile.videos.all()
    return render(
        request,
        "profiles/detail.html",
        {"profile": profile, "videos": videos},
    )


def profile_create(request):
    if request.method == "POST":
        form = ProfileForm(request.POST)
        if form.is_valid():
            profile = ProfileService.create_profile(form.cleaned_data)
            messages.success(request, f"Profile '{profile.name}' created.")
            return redirect(reverse("profiles:detail", args=[profile.pk]))
    else:
        form = ProfileForm()
    return render(
        request,
        "profiles/form.html",
        {"form": form, "title": "New profile"},
    )


def profile_edit(request, profile_id):
    profile = ProfileService.get_profile(profile_id)
    if profile is None:
        raise Http404("Profile not found")
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            ProfileService.update_profile(profile, form.cleaned_data)
            messages.success(request, "Profile updated.")
            return redirect(reverse("profiles:detail", args=[profile.pk]))
    else:
        form = ProfileForm(instance=profile)
    return render(
        request,
        "profiles/form.html",
        {"form": form, "title": f"Edit {profile.name}", "profile": profile},
    )


def profile_delete(request, profile_id):
    profile = ProfileService.get_profile(profile_id)
    if profile is None:
        raise Http404("Profile not found")
    if request.method == "POST":
        name = profile.name
        ProfileService.delete_profile(profile)
        messages.success(request, f"Profile '{name}' deleted.")
        return redirect(reverse("profiles:list"))
    return render(request, "profiles/confirm_delete.html", {"profile": profile})
