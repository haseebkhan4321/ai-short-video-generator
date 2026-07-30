from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.access import Perm, requires_perm

from .forms import TemplateForm
from .services import TemplateService


def _get_or_404(template_id, account):
    template = TemplateService.get_template(template_id, account)
    if template is None:
        # 404 rather than 403: a template in another account should not be
        # distinguishable from one that does not exist.
        raise Http404("Template not found")
    return template


@requires_perm(Perm.TEMPLATE_VIEW)
def template_list(request):
    templates = TemplateService.list_templates_with_stats(request.account)
    return render(request, "templates/list.html", {"templates": templates})


@requires_perm(Perm.TEMPLATE_VIEW)
def template_detail(request, template_id):
    template = _get_or_404(template_id, request.account)
    videos = template.videos.all()
    return render(
        request,
        "templates/detail.html",
        {
            "template": template,
            "videos": videos,
            "cost_summary": TemplateService.cost_summary(template),
        },
    )


@requires_perm(Perm.TEMPLATE_MANAGE)
def template_create(request):
    if request.method == "POST":
        form = TemplateForm(request.POST, account=request.account)
        if form.is_valid():
            template = TemplateService.create_template(
                request.account, form.cleaned_data
            )
            messages.success(request, f"Template '{template.name}' created.")
            return redirect(reverse("templates:detail", args=[template.pk]))
    else:
        form = TemplateForm(account=request.account)
    return render(
        request,
        "templates/form.html",
        {"form": form, "title": "New template"},
    )


@requires_perm(Perm.TEMPLATE_MANAGE)
def template_edit(request, template_id):
    template = _get_or_404(template_id, request.account)
    if request.method == "POST":
        form = TemplateForm(request.POST, instance=template, account=request.account)
        if form.is_valid():
            TemplateService.update_template(template, form.cleaned_data)
            messages.success(request, "Template updated.")
            return redirect(reverse("templates:detail", args=[template.pk]))
    else:
        form = TemplateForm(instance=template, account=request.account)
    return render(
        request,
        "templates/form.html",
        {"form": form, "title": f"Edit {template.name}", "template": template},
    )


@requires_perm(Perm.TEMPLATE_MANAGE)
def template_delete(request, template_id):
    template = _get_or_404(template_id, request.account)
    if request.method == "POST":
        name = template.name
        TemplateService.delete_template(template)
        messages.success(request, f"Template '{name}' deleted.")
        return redirect(reverse("templates:list"))
    return render(request, "templates/confirm_delete.html", {"template": template})
