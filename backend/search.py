"""Small, bounded expression language. Values are always SQL parameters."""

import json
import re
from datetime import date
from fastapi import HTTPException
from .core import db

TOKEN = re.compile(r'\s*("(?:[^"\\]|\\.)*"|&&|\|\||>=|<=|==|!=|[()><=]|[^\s()><=&|]+)')


class Parser:
    def __init__(self, text, connection, ignore_geography=False):
        self.original_text = text
        self.replacements = []
        self.ignore_geography = ignore_geography
        self.c = connection
        self.tokens = []
        pos = 0
        while pos < len(text.rstrip()):
            match = TOKEN.match(text, pos)
            if not match:
                raise ValueError(f"Unexpected character at position {pos + 1}")
            self.tokens.append(match.group(1))
            pos = match.end()
        if len(self.tokens) > 160:
            raise ValueError("Search is too long (maximum 160 terms and operators)")
        self.i = 0

    def canonical_text(self):
        if not self.replacements:
            return self.original_text
        tokens = list(self.tokens)
        for start,end,value in sorted(self.replacements,reverse=True):
            tokens[start:end] = [value]
        return ' '.join(tokens)

    def peek(self):
        return self.tokens[self.i].lower() if self.i < len(self.tokens) else ""

    def pop(self):
        if not self.peek():
            raise ValueError("Search ends before a value or closing parenthesis")
        t = self.tokens[self.i]
        self.i += 1
        return t

    def expect(self, value):
        if self.pop().lower() != value:
            raise ValueError(f"Expected {value}")

    def value(self):
        value = self.pop()
        if value.startswith('"'):
            return json.loads(value)
        if value.lower() in {"and", "or", "not", "(", ")", "&&", "||"}:
            raise ValueError("Expected a name; put names in double quotes")
        return value

    def person(self, name):
        rows = self.c.execute("SELECT id,name FROM people").fetchall()
        explicit = re.fullmatch(r"(.*) \[#(\d+)\]", name)
        if explicit:
            matches = [
                r["id"]
                for r in rows
                if r["id"] == int(explicit[2])
                and (r["name"] or f"Group {r['id']}").casefold()
                == explicit[1].casefold()
            ]
            if len(matches) == 1:
                return matches[0]
        matches = [
            r["id"]
            for r in rows
            if (r["name"] or f"Group {r['id']}").casefold() == name.casefold()
        ]
        if len(matches)>1:
            active=[identity for identity in matches if self.c.execute("SELECT 1 FROM faces WHERE person_id=? AND status!='dismissed' LIMIT 1",(identity,)).fetchone()]
            if len(active)==1: matches=active
        if len(matches) != 1:
            raise ValueError(
                f'Person "{name}" is unknown or ambiguous; choose a unique saved name'
            )
        return matches[0]

    def exists(self, identity):
        return (
            "EXISTS(SELECT 1 FROM faces sf WHERE sf.media_id=m.id AND sf.status!='dismissed' AND sf.person_id=?)",
            [identity],
        )

    @staticmethod
    def combine(left, args, right, params, op):
        # Removed geographic clauses are absent, including beneath NOT/OR.
        if left is None:
            return right, params
        if right is None:
            return left, args
        return f"({left} {op} {right})", args + params

    def expression(self, depth=0):
        if depth > 16:
            raise ValueError("Too many nested parentheses")
        sql, args = self.conjunction(depth)
        while self.peek() in ("or", "||"):
            self.pop()
            right, params = self.conjunction(depth)
            sql, args = self.combine(sql, args, right, params, "OR")
        return sql, args

    def conjunction(self, depth):
        sql, args = self.atom(depth)
        while self.peek() in ("and", "&&"):
            self.pop()
            right, params = self.atom(depth)
            sql, args = self.combine(sql, args, right, params, "AND")
        return sql, args

    def date_value(self):
        parts = []
        while self.peek() and self.peek() not in ('and','or','&&','||',')','(', 'to'):
            parts.append(self.value())
        if not parts:
            raise ValueError('Choose a date after the date operator')
        from .search_dates import period
        return period(' '.join(parts))

    def date_clause(self):
        from .search_dates import comparison
        op = self.pop().lower()
        if op == 'date':
            op = self.pop().lower()
        if op == 'on' and self.peek() == 'or':
            self.pop()
            direction = self.pop().lower()
            if direction not in ('after','before'):
                raise ValueError('Use on or after, or on or before')
            op = '>=' if direction == 'after' else '<='
        if op == 'between':
            low = self.date_value()[0]
            if self.pop().lower() not in ('and','to'):
                raise ValueError('Use between May 2025 and April 2026')
            high = self.date_value()[1]
            if low > high:
                raise ValueError('The start date must not be after the end date')
            from .metadata_support import DATE_LOW, DATE_HIGH
            return f'coalesce(({DATE_HIGH} >= ? AND {DATE_LOW} <= ?),0)', [low,high]
        if op == '==':
            op = '='
        op = {'after':'>', 'before':'<', 'since':'>=', 'until':'<=', 'through':'<=', 'on':'=', 'in':'=', 'during':'='}.get(op,op)
        if op not in ('>','<','>=','<=','=','!='):
            raise ValueError('Use after, before, between, on, in, since, until, or a date comparison')
        return comparison(op,self.date_value())

    def atom(self, depth):
        token = self.peek()
        if token == "only" and self.i+1<len(self.tokens) and self.tokens[self.i+1].lower() in ('photos','images','videos'):
            start=self.i
            self.pop()
            kind='video' if self.pop().lower()=='videos' else 'photo'
            self.replacements.append((start,self.i,'MediaType('+json.dumps(kind)+')'))
            return 'm.kind=?',[kind]
        if token == "allphones":
            self.pop()
            self.expect("(")
            self.expect(")")
            return "1", []
        if token == "not":
            self.pop()
            sql, args = self.atom(depth + 1)
            return (None, []) if sql is None else (f"NOT coalesce(({sql}),0)", args)
        if token == "(":
            self.pop()
            result = self.expression(depth + 1)
            self.expect(")")
            return result
        if token in ("includes", "only", "just"):
            mode = self.pop().lower()
            grouped = self.peek() == "("
            if grouped:
                self.pop()
            ids = [self.person(self.value())]
            while grouped and self.peek() in ("and", "&&"):
                self.pop()
                ids.append(self.person(self.value()))
            if grouped:
                self.expect(")")
            ids = list(dict.fromkeys(ids))
            parts, args = [], []
            for identity in ids:
                sql, params = self.exists(identity)
                parts.append(sql)
                args += params
            if mode == "includes":
                return "(" + " AND ".join(parts) + ")", args
            named = (
                "AND EXISTS(SELECT 1 FROM people sp WHERE sp.id=sf.person_id AND trim(coalesce(sp.name,''))!='')"
                if mode == "just"
                else ""
            )
            parts.append(
                "NOT EXISTS(SELECT 1 FROM faces sf WHERE sf.media_id=m.id AND sf.status!='dismissed' "
                + named
                + " AND (sf.person_id IS NULL OR sf.person_id NOT IN ("
                + ",".join("?" for _ in ids)
                + ")))"
            )
            args += ids
            if mode == "only":
                # A second face mistakenly assigned to the same identity must not satisfy Only.
                parts.append(
                    "NOT EXISTS(SELECT 1 FROM faces sf WHERE sf.media_id=m.id AND sf.status!='dismissed' GROUP BY coalesce(sf.timestamp,0) HAVING count(*)>?)"
                )
                args.append(len(ids))
            return "(" + " AND ".join(parts) + ")", args
        if token in ("phone", "album", "mediatype", "orientation", "text", "area", "location"):
            kind = self.pop().lower()
            self.expect("(")
            value = self.value()
            self.expect(")")
            if kind == "phone":
                from .search_devices import matching_devices
                phones = matching_devices(self.c,value)
                if len(phones)>1:
                    if value in phones: phones=[value]
                    else: raise ValueError('Device name is ambiguous; choose the exact saved name')
                return "m.phone=?", [phones[0] if phones else value]
            if kind == "album":
                if "\x1f" in value:
                    phone, album = value.split("\x1f", 1)
                    return "(m.phone=? AND m.album=?)", [phone, album]
                return "m.album=?", [value]
            if kind == "mediatype":
                if value not in ("photo", "video"):
                    raise ValueError('MediaType must be "photo" or "video"')
                return "m.kind=?", [value]
            if kind == "orientation":
                if value not in ("portrait", "landscape", "square"):
                    raise ValueError('Orientation must be "portrait", "landscape", or "square"')
                op = {"portrait":"<", "landscape":">", "square":"="}[value]
                return f"m.width {op} m.height", []
            if kind == "text":
                return "(instr(lower(m.name),lower(?))>0 OR instr(lower(m.album),lower(?))>0)", [value,value]
            if kind == "location":
                from .metadata_support import UNKNOWN, NO_GPS
                choices={'unknown':UNKNOWN,'no_gps':NO_GPS,'no_date':"m.taken IS NULL OR m.taken=''"}
                if value.lower() not in choices:
                    raise ValueError('Use Location("unknown"), Location("no_gps"), Location("no_date") or Place("name")')
                return (None, []) if self.ignore_geography and value.lower()!='no_date' else ('('+choices[value.lower()]+')', [])
            from .geo import add_location
            import math
            try:
                coords = [float(part.strip()) for part in value.split(",")]
                if len(coords) != 4 or not all(math.isfinite(v) for v in coords):
                    raise ValueError()
                south,north,west,east = coords
                if not (-90 <= south < north <= 90 and -180 <= west <= 180 and -180 <= east <= 180 and west != east):
                    raise ValueError()
            except ValueError:
                raise ValueError('Area expects "south,north,west,east" with valid latitude/longitude bounds')
            clauses, args = [], []
            add_location(clauses,args,"bounds",south,north,west,east,None,None,None)
            return (None, []) if self.ignore_geography else ("(" + " AND ".join(clauses) + ")", args)
        if token in ("date", "after", "before", "between", "since", "until", "through", "on", "in", "during", ">", "<", ">=", "<=", "=", "==", "!="):
            return self.date_clause()
        name_start = self.i
        typed = token in ("person", "place")
        if typed:
            kind = self.pop().lower()
            self.expect("(")
            name = self.value()
            self.expect(")")
        else:
            kind, name = "", self.value()
            # Bare saved names may contain spaces; operators still delimit terms.
            while self.peek() and self.peek() not in ("and", "or", "&&", "||", "(", ")", "not", ">", "<", "=", ">=", "<=", "!="):
                name += " " + self.value()
        if kind == "person":
            return self.exists(self.person(name))
        from .search_places import matching_places
        from .search_devices import matching_devices, device_key
        if not kind and device_key(name) in ('allphone','allphones','alldevices'):
            self.replacements.append((name_start,self.i,'AllPhones()'))
            return "1", []
        media_names={'photos':'photo','photo':'photo','images':'photo','image':'photo','videos':'video','video':'video','photos only':'photo','images only':'photo','videos only':'video'}
        if not kind and name.strip().lower() in media_names:
            media_kind=media_names[name.strip().lower()]
            self.replacements.append((name_start,self.i,'MediaType('+json.dumps(media_kind)+')'))
            return 'm.kind=?',[media_kind]
        locations = matching_places(self.c, name)
        persons = [
            r
            for r in self.c.execute("SELECT id,name FROM people")
            if (r["name"] or f"Group {r['id']}").casefold() == name.casefold()
        ]
        phones = matching_devices(self.c,name) if not kind else []
        if phones:
            if locations or persons or len(phones)>1:
                raise ValueError('Name is ambiguous; use Phone, Person or Place with an exact saved name')
            self.replacements.append((name_start,self.i,'Phone('+json.dumps(phones[0],ensure_ascii=False)+')'))
            return 'm.phone=?', [phones[0]]
        if kind == "place" or (locations and not persons):
            if len(locations) != 1:
                raise ValueError(
                    f'Place "{name}" is unknown or ambiguous; use its place ID'
                )
            identity = locations[0]["id"]
            if not kind:
                self.replacements.append((name_start,self.i,'Place('+json.dumps(identity,ensure_ascii=False)+')'))
            if self.ignore_geography:
                return None, []
            return (
                "EXISTS(SELECT 1 FROM media_places smp WHERE smp.media_id=m.id AND (smp.country_id=? OR smp.city_id=?))",
                [identity, identity],
            )
        if locations and persons:
            raise ValueError(f'Use Person("{name}") or Place("{name}") to disambiguate')
        identity = self.person(name)
        self.replacements.append((name_start,self.i,'Includes('+json.dumps(name,ensure_ascii=False)+')'))
        return self.exists(identity)


def compile_search(text, ignore_geography=False, canonical=False):
    if not text.strip():
        return ("1", [], "") if canonical else ("1", [])
    try:
        with db() as c:
            parser = Parser(text, c, ignore_geography)
            result = parser.expression()
            if parser.peek():
                raise ValueError("Expected AND or OR; quote names containing spaces")
            result = ("1", []) if result[0] is None else result
            return (*result, parser.canonical_text()) if canonical else result
    except (ValueError, RecursionError) as error:
        raise HTTPException(422, str(error)) from error
