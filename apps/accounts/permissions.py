"""The permission catalog.

Permissions are defined here in code, never in the database. Roles are created by
users and hold a list of these codenames, so the set of *possible* actions is
fixed by the developer while the set of *roles* is open-ended.

Codenames are dotted (``step.approve_paid``). Django templates cannot resolve a
dotted dictionary key, so the context processor also exposes an underscored form
(``can.step_approve_paid``) — see ``as_template_key``.
"""


class Perm:
    """Permission codenames. Views and templates reference these, never literals."""

    # Templates (the content identity formerly called "profile")
    TEMPLATE_VIEW = "template.view"
    TEMPLATE_MANAGE = "template.manage"

    # Videos
    VIDEO_VIEW = "video.view"
    VIDEO_CREATE = "video.create"
    VIDEO_DELETE = "video.delete"

    # Pipeline steps
    STEP_RUN_FREE = "step.run_free"
    STEP_APPROVE_PAID = "step.approve_paid"
    STEP_APPROVE_BUDGET = "step.approve_budget"
    STEP_OVERRIDE_BUDGET = "step.override_budget"
    STEP_REJECT = "step.reject"
    STEP_REGENERATE = "step.regenerate"

    # Account administration
    ACCOUNT_MANAGE_USERS = "account.manage_users"
    ACCOUNT_MANAGE_ROLES = "account.manage_roles"
    ACCOUNT_MANAGE_SETTINGS = "account.manage_settings"


# (codename, group, label, help text) — drives the role permission checkboxes.
PERMISSIONS = [
    (Perm.TEMPLATE_VIEW, "Templates", "View templates",
     "See templates and their videos."),
    (Perm.TEMPLATE_MANAGE, "Templates", "Manage templates",
     "Create, edit and delete templates, including the style prompt used in paid calls."),

    (Perm.VIDEO_VIEW, "Videos", "View videos",
     "Open videos, read scripts, play narration and watch renders."),
    (Perm.VIDEO_CREATE, "Videos", "Create videos",
     "Start a new video from a premise. This also queues the first paid script step."),
    (Perm.VIDEO_DELETE, "Videos", "Delete videos",
     "Permanently delete a video and all of its parts, images, steps and logs."),

    (Perm.STEP_RUN_FREE, "Pipeline", "Run free steps",
     "Run steps that cost nothing: splitting, narration, merging and rendering."),
    (Perm.STEP_APPROVE_PAID, "Pipeline", "Approve paid steps",
     "Authorize steps that spend real money on OpenAI (script and images)."),
    (Perm.STEP_APPROVE_BUDGET, "Pipeline", "Approve a whole video's budget up front",
     "Authorize a video's projected spend in one go, so its paid steps run without "
     "stopping for approval each. Stronger than approving one step at a time."),
    (Perm.STEP_OVERRIDE_BUDGET, "Pipeline", "Override the budget cap",
     "Approve spend that would push a video past MAX_COST_PER_VIDEO."),
    (Perm.STEP_REJECT, "Pipeline", "Reject steps",
     "Reject a step that is waiting for approval."),
    (Perm.STEP_REGENERATE, "Pipeline", "Regenerate steps",
     "Retry a failed step, or queue a fresh copy of a completed one."),

    (Perm.ACCOUNT_MANAGE_USERS, "Account", "Manage users",
     "Add users to this account, change their role and remove them."),
    (Perm.ACCOUNT_MANAGE_ROLES, "Account", "Manage roles",
     "Create roles and choose which permissions each one grants."),
    (Perm.ACCOUNT_MANAGE_SETTINGS, "Account", "Manage account settings",
     "Rename the account and change its settings."),
]

ALL_CODENAMES = frozenset(codename for codename, _, _, _ in PERMISSIONS)

# Preserves the declaration order of PERMISSIONS, which is grouped for display.
PERMISSION_GROUPS = []
for _codename, _group, _label, _help in PERMISSIONS:
    if not PERMISSION_GROUPS or PERMISSION_GROUPS[-1]["name"] != _group:
        PERMISSION_GROUPS.append({"name": _group, "permissions": []})
    PERMISSION_GROUPS[-1]["permissions"].append(
        {"codename": _codename, "label": _label, "help": _help}
    )

LABELS = {codename: label for codename, _, label, _ in PERMISSIONS}


def choices():
    """``(codename, label)`` pairs for a form field."""
    return [(codename, label) for codename, _, label, _ in PERMISSIONS]


def clean(codenames):
    """Drop anything that is not in the catalog, and keep catalog order.

    Role permissions are stored as JSON, so a codename can survive in the
    database after being removed from the catalog. Filtering on read means a
    stale codename can never grant anything.
    """
    given = set(codenames or ())
    return [codename for codename, _, _, _ in PERMISSIONS if codename in given]


def as_template_key(codename):
    """``step.approve_paid`` -> ``step_approve_paid`` for template lookups."""
    return codename.replace(".", "_")


# ---- Seeded default roles ----
# Cloned into every new account so it is usable immediately. Editable afterwards.

OWNER_ROLE = "Owner"
PRODUCER_ROLE = "Producer"
VIEWER_ROLE = "Viewer"

DEFAULT_ROLES = [
    {
        "name": OWNER_ROLE,
        "description": "Full control of the account, including users, roles and spend.",
        "permissions": [codename for codename, _, _, _ in PERMISSIONS],
    },
    {
        "name": PRODUCER_ROLE,
        "description": (
            "Makes videos and approves paid steps, but cannot exceed the budget cap "
            "or administer the account."
        ),
        "permissions": [
            Perm.TEMPLATE_VIEW,
            Perm.TEMPLATE_MANAGE,
            Perm.VIDEO_VIEW,
            Perm.VIDEO_CREATE,
            Perm.VIDEO_DELETE,
            Perm.STEP_RUN_FREE,
            Perm.STEP_APPROVE_PAID,
            Perm.STEP_REJECT,
            Perm.STEP_REGENERATE,
        ],
    },
    {
        "name": VIEWER_ROLE,
        "description": "Read-only. Can watch and read, but cannot start or approve anything.",
        "permissions": [Perm.TEMPLATE_VIEW, Perm.VIDEO_VIEW],
    },
]
