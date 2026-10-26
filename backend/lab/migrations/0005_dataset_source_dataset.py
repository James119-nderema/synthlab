from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('lab', '0004_dataset_differentially_private'),
    ]

    operations = [
        migrations.AddField(
            model_name='dataset',
            name='source_dataset',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='synthetic_outputs',
                to='lab.dataset',
            ),
        ),
    ]
