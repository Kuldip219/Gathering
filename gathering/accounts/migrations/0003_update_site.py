from django.db import migrations


def update_site(apps, schema_editor):
    # The default Site (created by django.contrib.sites) points at example.com,
    # which makes reset links / site names in emails wrong. Point it at the
    # local dev server. TODO: revisit for production deploys.
    Site = apps.get_model('sites', 'Site')
    Site.objects.filter(pk=1).update(domain='127.0.0.1:8000', name='Gathering')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_alter_user_email'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(update_site, migrations.RunPython.noop),
    ]
