"""Resolve saved device names despite case, spacing and punctuation differences."""
import unicodedata


def device_key(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',value.casefold()) if c.isalnum())


def matching_devices(connection,name):
    key=device_key(name)
    return [r[0] for r in connection.execute("SELECT DISTINCT phone FROM media WHERE phone IS NOT NULL AND phone!=''") if device_key(r[0])==key]
