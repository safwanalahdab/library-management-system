"""Move READER accounts from library scope to direct governorate scope.

Order matters:
1. Drop the old role/scope constraint (it requires READER.library).
2. Move readers to their library's governorate and clear the library link.
3. Add the new constraint (READER.governorate required, READER.library empty).

Every reader is inspected before any row is changed. Conflicting or
undeterminable readers stop the migration without choosing a default.
"""

import django.db.models.deletion
from django.db import migrations, models


READER = "READER"


class ReaderScopeMigrationError(RuntimeError):
    pass


def plan_reader_scope_updates(CustomUser, alias):
    """Return {user_id: governorate_id} for readers that need changes.

    Raises ReaderScopeMigrationError listing every reader that cannot be
    migrated safely; no data is changed in that case.
    """
    readers = (
        CustomUser.objects.using(alias)
        .filter(role=READER, is_superuser=False)
        .select_related("library")
        .order_by("pk")
    )

    updates = {}
    conflicts = []
    unresolved = []
    for reader in readers:
        library_governorate_id = (
            reader.library.governorate_id if reader.library_id is not None else None
        )

        if reader.library_id is None:
            if reader.governorate_id is None:
                unresolved.append(reader.pk)
            continue

        if (
            reader.governorate_id is not None
            and reader.governorate_id != library_governorate_id
        ):
            conflicts.append(
                f"{reader.pk} (governorate={reader.governorate_id}, "
                f"library={reader.library_id}, "
                f"library_governorate={library_governorate_id})"
            )
            continue

        updates[reader.pk] = library_governorate_id

    if conflicts or unresolved:
        messages = []
        if conflicts:
            messages.append(
                "Readers whose governorate conflicts with their library's governorate: "
                + ", ".join(conflicts)
            )
        if unresolved:
            messages.append(
                "Readers without a governorate or library: "
                + ", ".join(str(pk) for pk in unresolved)
            )
        raise ReaderScopeMigrationError(
            "Reader scope migration stopped; no rows were changed. "
            "Fix these accounts manually, then rerun migrate. "
            + " | ".join(messages)
        )

    return updates


def move_readers_to_governorate(apps, schema_editor):
    CustomUser = apps.get_model("accounts", "CustomUser")
    alias = schema_editor.connection.alias

    updates = plan_reader_scope_updates(CustomUser, alias)
    for user_id, governorate_id in updates.items():
        CustomUser.objects.using(alias).filter(pk=user_id).update(
            governorate_id=governorate_id,
            library_id=None,
        )


def reject_reverse_with_readers(apps, schema_editor):
    CustomUser = apps.get_model("accounts", "CustomUser")
    alias = schema_editor.connection.alias

    if CustomUser.objects.using(alias).filter(role=READER, is_superuser=False).exists():
        raise ReaderScopeMigrationError(
            "Cannot reverse the reader scope migration while READER accounts exist: "
            "the previous schema requires a library for every reader, and the "
            "original library cannot be recovered automatically."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_customuser_accounts_user_role_scope_valid_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="customuser",
            name="accounts_user_role_scope_valid",
        ),
        migrations.RunPython(
            move_readers_to_governorate,
            reject_reverse_with_readers,
        ),
        migrations.AddConstraint(
            model_name="customuser",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_superuser=True)
                    | models.Q(role="MINISTRY_ADMIN", governorate__isnull=True, library__isnull=True)
                    | models.Q(role="GOVERNORATE_ADMIN", governorate__isnull=False, library__isnull=True)
                    | models.Q(role="LIBRARIAN", governorate__isnull=True, library__isnull=False)
                    | models.Q(role="READER", governorate__isnull=False, library__isnull=True)
                ),
                name="accounts_user_role_scope_valid",
            ),
        ),
        migrations.AlterField(
            model_name="customuser",
            name="governorate",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="users",
                to="accounts.governorate",
            ),
        ),
    ]
