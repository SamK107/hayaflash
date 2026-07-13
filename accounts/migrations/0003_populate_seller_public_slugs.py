from __future__ import annotations

from django.db import migrations


def populate_seller_slugs(apps, schema_editor):
    SellerProfile = apps.get_model("accounts", "SellerProfile")
    from accounts.services.slugs import generate_unique_seller_public_slug

    for profile in SellerProfile.objects.filter(public_slug="").iterator():
        profile.public_slug = generate_unique_seller_public_slug(profile)
        profile.save(update_fields=["public_slug"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_sellerprofile_public_slug"),
    ]

    operations = [
        migrations.RunPython(populate_seller_slugs, migrations.RunPython.noop),
    ]
