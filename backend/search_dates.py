"""Calendar-aware date phrases, expressed as inclusive ISO day bounds."""
import calendar
import re
from datetime import date

MONTHS = {name.casefold(): i for i in range(1,13) for name in (calendar.month_name[i], calendar.month_abbr[i])}
MONTHS['sept'] = 9


def period(value):
    raw = value.strip().strip('"')
    if re.fullmatch(r'\d{4}(?:-\d{2}){0,2}', raw):
        parts = [int(p) for p in raw.split('-')]
        year = parts[0]
        month = parts[1] if len(parts)>1 else None
        day = parts[2] if len(parts)>2 else None
    else:
        clean = re.sub(r'(\d)(?:st|nd|rd|th)\b', r'\1', raw, flags=re.I)
        parts = re.sub(r'[.,]', ' ', clean).split()
        year = month = day = None
        if len(parts) in (2,3) and parts[0].casefold() in MONTHS:
            month = MONTHS[parts[0].casefold()]
            year = int(parts[-1]) if re.fullmatch(r'\d{4}',parts[-1]) else None
            day = int(parts[1]) if len(parts)==3 and parts[1].isdigit() else None
            if len(parts)==3 and day is None: raise ValueError('Invalid day in date')
        elif len(parts)==3 and parts[1].casefold() in MONTHS and parts[0].isdigit():
            day,month = int(parts[0]),MONTHS[parts[1].casefold()]
            year = int(parts[2]) if re.fullmatch(r'\d{4}',parts[2]) else None
        if year is None:
            raise ValueError('Use a year, May 2025, May 21 2024, 21 May 2024, or YYYY-MM-DD')
    if month is None:
        return date(year,1,1).isoformat(), date(year,12,31).isoformat()
    if day is not None:
        value = date(year,month,day).isoformat()
        return value,value
    return date(year,month,1).isoformat(),date(year,month,calendar.monthrange(year,month)[1]).isoformat()


def comparison(op, bounds):
    low,high = bounds
    from .metadata_support import DATE_LOW, DATE_HIGH
    field = DATE_LOW if op in ('>','<=') else DATE_HIGH
    if op in ('=', '!='):
        sql = f'coalesce(({DATE_HIGH} >= ? AND {DATE_LOW} <= ?),0)'
        return (f'coalesce(NOT ({DATE_HIGH} >= ? AND {DATE_LOW} <= ?),0)' if op=='!=' else sql), [low,high]
    edge = high if op in ('>','<=') else low
    return f'coalesce({field} {op} ?,0)', [edge]
