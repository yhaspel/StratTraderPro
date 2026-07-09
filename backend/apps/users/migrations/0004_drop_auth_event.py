# M10 — drop AuthEvent after its rows are migrated into the chained audit_log.
#
# Depends on audit.0003_migrate_auth_events so the data migration (which reads
# users_auth_event via the historical model) runs BEFORE the table is dropped.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_oauth_exchange_code'),
        ('audit', '0003_migrate_auth_events'),
    ]

    operations = [
        migrations.DeleteModel(
            name='AuthEvent',
        ),
    ]
