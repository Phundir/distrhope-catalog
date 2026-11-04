#!/usr/bin/env python3
"""Vérifie catalog.json (§6 règle 5 : « une action CI vérifie chaque URL et
chaque somme de contrôle »).

  python3 scripts/verify.py                 schéma + règles + URLs (HEAD)
  python3 scripts/verify.py --full          + téléchargement en flux de chaque
                                            ISO et calcul de sa somme (aucune
                                            écriture sur disque)
  python3 scripts/verify.py --full --only archlinux,debian-netinst
  python3 scripts/verify.py --full --changed-since ancien.json
                                            téléchargement complet seulement des
                                            entrées nouvelles ou modifiées
  python3 scripts/verify.py --lenient-unchanged ancien.json
                                            une URL en échec sur une entrée NON
                                            modifiée depuis ancien.json n'est
                                            qu'un avertissement (ISO « rolling »
                                            remplacée entre deux mises à jour)
  python3 scripts/verify.py --offline       schéma + règles uniquement

Le schéma est validé avec `jsonschema` s'il est installé ; les règles
essentielles sont de toute façon vérifiées sans dépendance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = "distrhope-catalog-verify/1"
PROFILES = {"arch-mkinitcpio", "arch-dracut", "fedora", "debian", "opensuse", "void", "nixos"}


def rules(cat: dict) -> list[str]:
    errs = []
    if cat.get("schema_version") != 1:
        errs.append("schema_version doit valoir 1")
    seen = set()
    for i, d in enumerate(cat.get("distros", [])):
        w = f"distros[{i}] ({d.get('id', '?')})"
        for k in ("id", "name", "version", "arch", "iso"):
            if k not in d:
                errs.append(f"{w} : champ obligatoire « {k} » absent")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", d.get("id", "")):
            errs.append(f"{w} : id invalide")
        if d.get("id") in seen:
            errs.append(f"{w} : id dupliqué")
        seen.add(d.get("id"))
        iso = d.get("iso", {})
        if not str(iso.get("url", "")).startswith("https://"):
            errs.append(f"{w} : iso.url doit être en HTTPS")
        ck = iso.get("checksum", {})
        n = {"sha256": 64, "sha512": 128}.get(ck.get("algo"))
        if not n or not re.fullmatch(rf"[0-9a-f]{{{n}}}", ck.get("value", "")):
            errs.append(f"{w} : somme de contrôle invalide")
        if "profile" in d and d["profile"] not in PROFILES:
            errs.append(f"{w} : profil inconnu {d['profile']}")
        mn, rc = d.get("min_size_gib", 20), d.get("recommended_size_gib", 40)
        if rc < mn:
            errs.append(f"{w} : recommended_size_gib < min_size_gib")
        if iso.get("size_bytes") and iso["size_bytes"] > mn * 2**30:
            errs.append(f"{w} : l'ISO est plus grande que la taille minimale du slot")
    return errs


def schema(cat: dict) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        print("  (jsonschema absent : validation par les règles intégrées seulement)", file=sys.stderr)
        return []
    s = json.loads((ROOT / "catalog.schema.json").read_text())
    v = jsonschema.Draft202012Validator(s, format_checker=jsonschema.FormatChecker())
    return [f"schéma : {'/'.join(map(str, e.path))} : {e.message}" for e in v.iter_errors(cat)]


def open_url(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=120)


def check_head(d: dict) -> list[str]:
    errs = []
    iso = d["iso"]
    for u in [iso["url"], *iso.get("mirrors", [])]:
        try:
            with open_url(u, "HEAD") as r:
                size = int(r.headers.get("Content-Length") or 0)
            if iso.get("size_bytes") and size and size != iso["size_bytes"]:
                errs.append(f"{d['id']} : {u} : taille {size} ≠ {iso['size_bytes']}")
        except Exception as e:
            (errs if u == iso["url"] else warns).append(f"{d['id']} : {u} : {e}")
    if iso.get("signature_url"):
        try:
            with open_url(iso["signature_url"], "HEAD"):
                pass
        except Exception as e:
            warns.append(f"{d['id']} : signature : {e}")
    return errs


def check_full(d: dict) -> list[str]:
    iso = d["iso"]
    h = hashlib.new(iso["checksum"]["algo"])
    total, t0 = 0, time.time()
    with open_url(iso["url"]) as r:
        while chunk := r.read(4 << 20):
            h.update(chunk)
            total += len(chunk)
    dt = max(time.time() - t0, 0.001)
    got = h.hexdigest()
    print(f"    {d['id']}: {total / 2**30:.2f} Gio en {dt:.0f} s ({total / dt / 2**20:.0f} Mio/s)", file=sys.stderr)
    if got != iso["checksum"]["value"]:
        return [f"{d['id']} : SOMME INCORRECTE ({got})"]
    if iso.get("size_bytes") and total != iso["size_bytes"]:
        return [f"{d['id']} : taille téléchargée {total} ≠ {iso['size_bytes']}"]
    return []


warns: list[str] = []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("catalog", nargs="?", default=str(ROOT / "catalog.json"))
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--changed-since", default="")
    ap.add_argument("--lenient-unchanged", default="")
    a = ap.parse_args()
    cat = json.loads(Path(a.catalog).read_text())
    errs = rules(cat) + schema(cat)
    only = {x for x in a.only.split(",") if x}
    if a.changed_since:
        try:
            old = {d["id"]: d["iso"] for d in json.loads(Path(a.changed_since).read_text())["distros"]}
        except (OSError, ValueError, KeyError):
            old = {}
        only |= {d["id"] for d in cat["distros"] if old.get(d["id"]) != d["iso"]}
        if not only:
            print("aucune entrée modifiée", file=sys.stderr)
            sys.exit(1 if errs else 0)
    distros = [d for d in cat["distros"] if not only or d["id"] in only]
    unchanged: set[str] = set()
    if a.lenient_unchanged:
        try:
            old = {d["id"]: d for d in json.loads(Path(a.lenient_unchanged).read_text())["distros"]}
        except (OSError, ValueError, KeyError):
            old = {}
        unchanged = {d["id"] for d in cat["distros"] if old.get(d["id"]) == d}
    if not a.offline and not errs:
        for d in distros:
            e = check_head(d)
            if e and d["id"] in unchanged:
                warns.extend(f"{x} (entrée non modifiée : la mise à jour automatique la rafraîchira)" for x in e)
                e = []
            if not e and a.full:
                e = check_full(d)
            print(f"  {'✔' if not e else '✘'} {d['id']}", file=sys.stderr)
            errs += e
    for w in warns:
        print(f"  ⚠ {w}", file=sys.stderr)
    for e in errs:
        print(f"  ✘ {e}", file=sys.stderr)
    print(f"{len(distros)} entrées, {len(errs)} erreur(s), {len(warns)} avertissement(s)", file=sys.stderr)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
