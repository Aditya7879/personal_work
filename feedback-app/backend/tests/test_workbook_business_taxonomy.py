import pytest

from app.business_domain import split_business_taxonomy, workbook_business_taxonomy


@pytest.mark.parametrize('label,expected', [
    ('F2S - Lifecycle Management', ('F2S', 'Lifecycle Management')),
    ('F2S-DC to DC planning', ('F2S', 'DC to DC planning')),
    ('F2S-Transportation Management', ('F2S', 'Transportation Management')),
    ('O2C-Credit Management', ('O2C', 'Credit Management')),
    ('O2C- Credit management', ('O2C', 'Credit management')),
    (' f2s – Batch Management ', ('F2S', 'Batch Management')),
    ('OTC - Customer Master Data', ('O2C', 'Customer Master Data')),
    ('Catalogue Management', (None, 'Catalogue Management')),
    ('', (None, None)),
])
def test_explicit_workbook_prefixes(label, expected):
    assert split_business_taxonomy(label) == expected


def test_bare_names_use_only_unambiguous_workbook_peers():
    result = workbook_business_taxonomy(['F2S - Sub-contracting/Copacking', 'Sub-contracting/Copacking',
        'O2C - Credit Management', 'O2C- Credit management', 'Catalogue Management'])
    assert result['Sub-contracting/Copacking'] == {'domain': 'F2S', 'subdomain': 'Sub-contracting/Copacking'}
    assert result['O2C- Credit management'] == {'domain': 'O2C', 'subdomain': 'Credit Management'}
    assert result['Catalogue Management']['domain'] is None


def test_ambiguous_bare_labels_are_not_assigned_a_domain():
    result = workbook_business_taxonomy(['F2S - Master Data', 'O2C - Master Data', 'Master Data'])
    assert result['Master Data']['domain'] is None
