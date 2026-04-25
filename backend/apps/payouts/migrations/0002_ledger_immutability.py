from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payouts", "0001_initial"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="ledgerentry",
            constraint=models.CheckConstraint(
                check=models.Q(amount_paise__gt=0),
                name="ledger_amount_paise_positive",
            ),
        ),
    ]
