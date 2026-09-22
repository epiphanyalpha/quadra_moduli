"""Strict date-only conversion for Gregorian Word content controls."""
import re
from datetime import datetime


def converti(valore, formato='dd/MM/yyyy', calendario='gregorian'):
    if calendario not in ('gregorian', ''):
        raise ValueError('Calendario Word non supportato: ' + calendario)
    # Numeric patterns only: never guess locales or ambiguous month names.
    if not re.fullmatch(r'(?:d{1,2}([/.-])M{1,2}\1yyyy|yyyy([/.-])M{1,2}\2d{1,2})', formato):
        raise ValueError('Formato data Word non supportato: ' + formato)
    value = str(valore).strip()
    parsed = None
    for pattern, fmt in [(r'\d{4}-\d{2}-\d{2}', '%Y-%m-%d'),
                         (r'\d{1,2}/\d{1,2}/\d{4}', '%d/%m/%Y'),
                         (r'\d{1,2}-\d{1,2}-\d{4}', '%d-%m-%Y'),
                         (r'\d{1,2}\.\d{1,2}\.\d{4}', '%d.%m.%Y')]:
        if re.fullmatch(pattern, value):
            try:
                parsed = datetime.strptime(value, fmt)
            except ValueError:
                pass
            break
    if parsed is None:
        raise ValueError('Data assente, non valida o non interpretabile senza ambiguita')
    parts = {'yyyy':f'{parsed.year:04d}', 'MM':f'{parsed.month:02d}',
             'M':str(parsed.month), 'dd':f'{parsed.day:02d}', 'd':str(parsed.day)}
    visible = re.sub(r'yyyy|MM|dd|M|d', lambda m:parts[m.group()], formato)
    return visible, parsed.strftime('%Y-%m-%dT00:00:00Z')
