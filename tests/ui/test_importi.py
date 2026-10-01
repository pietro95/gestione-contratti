from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from contratti.forms import ImportoField, interpreta_importo


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("12.000,00", "12000.00"),
        ("12000,5", "12000.5"),
        ("12000.50", "12000.50"),
        ("12.000", "12000"),
        ("1.234.567,89", "1234567.89"),
        (" 1.234,56 € ", "1234.56"),
        ("0,01", "0.01"),
        ("150", "150"),
    ],
)
def test_interpreta_importo(testo, atteso):
    assert interpreta_importo(testo) == atteso


def test_importo_field_pulisce_e_valida():
    campo = ImportoField(max_digits=14, decimal_places=2, min_value=0)
    assert campo.clean("12.000,00") == Decimal("12000.00")
    with pytest.raises(ValidationError):
        campo.clean("12,345")  # tre decimali
    with pytest.raises(ValidationError):
        campo.clean("-1")


def test_importo_field_widget_testo_localizzato():
    campo = ImportoField(max_digits=14, decimal_places=2)
    html = campo.widget.render("importo", Decimal("1234.50"))
    assert 'type="text"' in html
    assert 'inputmode="decimal"' in html
    assert 'value="1.234,50"' in html
