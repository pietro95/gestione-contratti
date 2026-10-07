# Rev15: l'imponibile della fattura diventa l'importo del documento (l'«Importo SAP»).

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("contratti", "0027_lavorazione_fatture"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="fattura",
            name="contratti_fattura_imponibile_non_negativo",
        ),
        migrations.RenameField(
            model_name="fattura",
            old_name="imponibile",
            new_name="importo_documento",
        ),
        migrations.RenameField(
            model_name="historicalfattura",
            old_name="imponibile",
            new_name="importo_documento",
        ),
    ]
