"""Merge duplicate records and flag shared (department / generic) email addresses."""
from __future__ import annotations

import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
URL_RE = re.compile(r"^https?://\S+$", re.I)
IMAGE_RE = re.compile(r"\.(png|jpe?g|gif|webp|svg)(\?|$)", re.I)

NOTE_KEY = "_email_note"
NOTE_LABEL = "邮箱备注"
SHARED = "公共邮箱"


def _name_key(value: str) -> str:
    """Order-insensitive name key: 'Chan, Andrew Chi-fai' == 'Andrew Chi-fai Chan'."""
    return " ".join(sorted(re.findall(r"\w+", value.lower())))


def _identifiers(rec: dict, keys: list[str]) -> list[str]:
    out = []
    for k in keys:
        v = str(rec.get(k, "") or "").strip()
        if EMAIL_RE.match(v):
            out.append("mail:" + v.lower())
        elif URL_RE.match(v) and not IMAGE_RE.search(v):
            out.append("url:" + v.rstrip("/").lower())
    return out


def _norm(v) -> str:
    return " ".join(str(v or "").split()).lower()


def _merge_same_name(records: list[dict], keys: list[str], name_field: str) -> list[dict]:
    """Merge records with the same name whose other fields never disagree, e.g. a list-page
    row (name + title) and the profile-page row of the same person (name + email)."""
    out: list[dict] = []
    by_name: dict[str, list[dict]] = {}
    for r in records:
        name = _name_key(str(r.get(name_field, "") or ""))
        target = None
        if name:
            for cand in by_name.get(name, []):
                if all(not _norm(r.get(k)) or not _norm(cand.get(k)) or _norm(r.get(k)) == _norm(cand.get(k))
                       for k in keys):
                    target = cand
                    break
        if target is None:
            rec = dict(r)
            out.append(rec)
            if name:
                by_name.setdefault(name, []).append(rec)
            continue
        for k, v in r.items():
            if v and not target.get(k):
                target[k] = v
    return out


def dedupe(records: list[dict], field_keys: list[str]) -> tuple[list[dict], int, int]:
    """Return (merged records, number of duplicates removed, number flagged as shared email).

    Records are merged when they share an identifying email / detail URL, are identical, or
    have the same name and no conflicting field values.
    A value counts as identifying only if it never appears with two different names (first
    field), so department-wide emails or links do not glue different people together.
    """
    keys = [k for k in field_keys if not k.startswith("_")]
    if not records or not keys:
        return records, 0, 0
    name_field = keys[0]

    names_by_ident: dict[str, set[str]] = {}
    for r in records:
        name = _name_key(str(r.get(name_field, "") or ""))
        for ident in _identifiers(r, keys):
            names_by_ident.setdefault(ident, set())
            if name:
                names_by_ident[ident].add(name)
    identifying = {i for i, names in names_by_ident.items() if len(names) <= 1}

    # Union-find over records that share an identifying value or are exact duplicates
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first_seen: dict[str, int] = {}
    for idx, r in enumerate(records):
        sig = "sig:" + "\x1f".join(str(r.get(k, "") or "").strip().lower() for k in keys)
        for ident in [i for i in _identifiers(r, keys) if i in identifying] + [sig]:
            if ident in first_seen:
                parent[find(idx)] = find(first_seen[ident])
            else:
                first_seen[ident] = idx

    groups: dict[int, dict] = {}
    order: list[int] = []
    for idx, r in enumerate(records):
        root = find(idx)
        if root not in groups:
            groups[root] = dict(r)
            order.append(root)
            continue
        merged = groups[root]
        for k, v in r.items():
            if v and not merged.get(k):
                merged[k] = v
    result = _merge_same_name([groups[i] for i in order], keys, name_field)

    # Flag emails shared by several different people
    flagged = 0
    for r in result:
        r.pop(NOTE_KEY, None)
        for k in keys:
            v = str(r.get(k, "") or "").strip()
            if EMAIL_RE.match(v) and len(names_by_ident.get("mail:" + v.lower(), ())) > 1:
                r[NOTE_KEY] = SHARED
                flagged += 1
                break
    return result, len(records) - len(result), flagged
