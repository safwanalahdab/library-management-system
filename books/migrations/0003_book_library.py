"""Link every Book to exactly one Library.

Order matters:
1. Add Book.library as nullable so existing rows do not need a value.
2. Stop if any book has no library; no default library is chosen and no row
   is deleted or changed. Those books need an explicit linking decision first.
3. Make Book.library required (null=False, no default).

Library is created in accounts.0001_initial and its table is not altered by
later accounts migrations, so that is the only accounts dependency needed.
"""

import django.db.models.deletion
from django.db import migrations, models


class BooksWithoutLibraryError(RuntimeError):
    pass


def find_books_without_library(Book, alias):
    return list(
        Book.objects.using(alias)
        .filter(library__isnull=True)
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def ensure_all_books_have_library(apps, schema_editor):
    Book = apps.get_model("books", "Book")
    unlinked = find_books_without_library(Book, schema_editor.connection.alias)
    if unlinked:
        raise BooksWithoutLibraryError(
            "Cannot make Book.library required: "
            f"{len(unlinked)} book(s) have no library (ids: {unlinked}). "
            "Link each book to its library explicitly, then run the migration again."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("books", "0002_remove_bookreservation_book_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="library",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="books",
                to="accounts.library",
            ),
        ),
        # Reverse is a no-op: the reversed AlterField makes the column nullable
        # again and the reversed AddField drops it, with no data updates.
        migrations.RunPython(
            ensure_all_books_have_library,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="book",
            name="library",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="books",
                to="accounts.library",
            ),
        ),
    ]
