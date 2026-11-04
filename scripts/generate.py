#!/usr/bin/env python3
"""Génère catalog.json à partir des sources OFFICIELLES de chaque distro.

Pour chaque entrée :
  - le nom exact de l'ISO et sa somme de contrôle sont lus dans le fichier
    de sommes publié par la distro (SHA256SUMS, CHECKSUM, *.sha256, …) ;
  - l'URL est vérifiée (HTTP 200 après redirections, taille > 100 Mio) ;
  - la date de publication vient de l'en-tête Last-Modified.
Une source en échec est ignorée (avec un avertissement) sans bloquer les
autres ; l'entrée précédente de catalog.json est alors conservée telle
quelle si elle existe.

Usage : python3 scripts/generate.py [--out catalog.json]
Bibliothèque standard uniquement.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import re
import sys
import urllib.request
from pathlib import Path

UA = "distrhope-catalog-generator/1 (+https://github.com/)"
MIN_ISO = 100 * 1024 * 1024


def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def head(url: str) -> tuple[str, int, str | None]:
    """(URL finale, taille, date ISO 8601 ou None) ; lève en cas d'échec."""
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        size = int(r.headers.get("Content-Length") or 0)
        lm = r.headers.get("Last-Modified")
        date = email.utils.parsedate_to_datetime(lm).date().isoformat() if lm else None
        return r.geturl(), size, date


def sums(text: str) -> dict[str, str]:
    """Analyse les formats GNU (`hash  nom`, `hash *nom`) et BSD
    (`SHA256 (nom) = hash`)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^(?:SHA(?:256|512)) \((.+)\) = ([0-9a-fA-F]+)$", line)
        if m:
            out[m.group(1)] = m.group(2).lower()
            continue
        m = re.match(r"^([0-9a-fA-F]{64}|[0-9a-fA-F]{128})\s+\*?(.+)$", line)
        if m:
            out[m.group(2).strip()] = m.group(1).lower()
    return out


def algo(h: str) -> str:
    return {64: "sha256", 128: "sha512"}[len(h)]


def links(html: str, pattern: str) -> list[str]:
    return sorted(set(re.findall(pattern, html)))


def vkey(s: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]


def latest(items):
    return sorted(items, key=vkey)[-1]


ENTRIES = []


def source(fn):
    ENTRIES.append(fn)
    return fn


def entry(id, name, version, url, checksum, *, edition=None, desktop=None, wm=None,
          profile=None, mirrors=None, signature_url=None, min_gib=20, rec_gib=40,
          homepage=None, tags=(), notes=None):
    final, size, date = head(url)
    if size < MIN_ISO:
        raise RuntimeError(f"{url} : taille suspecte ({size} octets)")
    e = {
        "id": id,
        "name": name,
        "version": version,
        "arch": "x86_64",
        "iso": {
            "url": url,
            "size_bytes": size,
            "checksum": {"algo": algo(checksum), "value": checksum},
        },
        "min_size_gib": min_gib,
        "recommended_size_gib": rec_gib,
        "tags": list(tags),
    }
    for k, v in (("edition", edition), ("desktop", desktop), ("wm", wm), ("profile", profile),
                 ("release_date", date), ("homepage", homepage), ("notes", notes)):
        if v:
            e[k] = v
    if mirrors:
        e["iso"]["mirrors"] = mirrors
    if signature_url:
        e["iso"]["signature_url"] = signature_url
    # Ordre de clés stable et lisible.
    order = ["id", "name", "version", "edition", "desktop", "wm", "arch", "profile", "iso",
             "min_size_gib", "recommended_size_gib", "release_date", "homepage", "tags", "notes"]
    return {k: e[k] for k in order if k in e}


# ------------------------------------------------------------------ Arch ----

@source
def arch():
    base = "https://geo.mirror.pkgbuild.com/iso/latest/"
    s = sums(fetch(base + "sha256sums.txt"))
    name = next(n for n in s if re.match(r"archlinux-\d{4}\.\d\d\.\d\d-x86_64\.iso$", n))
    ver = name.split("-")[1]
    path = f"iso/{ver}/{name}"
    yield entry(
        "archlinux", "Arch Linux", ver, f"https://geo.mirror.pkgbuild.com/{path}", s[name],
        edition="Minimal", profile="arch-mkinitcpio",
        mirrors=[f"https://mirrors.kernel.org/archlinux/{path}", f"https://mirror.rackspace.com/archlinux/{path}"],
        signature_url=f"https://geo.mirror.pkgbuild.com/{path}.sig",
        homepage="https://archlinux.org", tags=["rolling", "minimal"],
        notes="Pas d'installeur graphique : installation à la main ou avec archinstall dans la VM.",
    )


@source
def cachyos():
    base = "https://mirror.cachyos.org/ISO/desktop/"
    ver = latest(links(fetch(base), r'href="(\d{6})/"'))
    name = f"cachyos-desktop-linux-{ver}.iso"
    h = fetch(f"{base}{ver}/{name}.sha256").split()[0].lower()
    yield entry(
        "cachyos-desktop", "CachyOS", ver, f"{base}{ver}/{name}", h,
        edition="Desktop", desktop="KDE Plasma (par défaut, au choix)", profile="arch-mkinitcpio",
        mirrors=[f"https://cdn77.cachyos.org/ISO/desktop/{ver}/{name}"],
        signature_url=f"{base}{ver}/{name}.sig", min_gib=30, rec_gib=60,
        homepage="https://cachyos.org", tags=["rolling", "gaming", "performance"],
    )


@source
def endeavouros():
    base = "https://mirror.alpix.eu/endeavouros/iso/"
    name = latest(links(fetch(base), r'href="(EndeavourOS_[^"/]+\.iso)"'))
    ver = re.search(r"(\d{4}\.\d\d\.\d\d)", name).group(1)
    h = fetch(base + name + ".sha512sum").split()[0].lower()
    yield entry(
        "endeavouros", "EndeavourOS", ver, base + name, h,
        edition="Desktop", desktop="KDE Plasma (par défaut, au choix)", profile="arch-dracut",
        mirrors=[f"https://mirrors.gigenet.com/endeavouros/iso/{name}"],
        signature_url=base + name + ".sig", min_gib=30, rec_gib=60,
        homepage="https://endeavouros.com", tags=["rolling"],
    )


@source
def manjaro():
    html = fetch("https://manjaro.org/products/download/x86")
    for de, desktop in (("kde", "KDE Plasma"), ("gnome", "GNOME"), ("xfce", "Xfce")):
        urls = links(html, rf"https://download\.manjaro\.org/{de}/[^\"']+?\.iso")
        url = latest([u for u in urls if "minimal" not in u])
        name = url.rsplit("/", 1)[1]
        ver = url.split("/")[4]
        h = fetch(url + ".sha256").split()[0].lower()
        yield entry(
            f"manjaro-{de}", "Manjaro", ver, url, h,
            edition="Desktop", desktop=desktop, profile="arch-mkinitcpio",
            signature_url=url + ".sig", min_gib=30, rec_gib=50,
            homepage="https://manjaro.org", tags=["rolling", "beginner"],
        )


@source
def garuda():
    for ed, desktop, wm, tags in (
        ("dr460nized", "KDE Plasma", None, ["rolling", "gaming"]),
        ("gnome", "GNOME", None, ["rolling"]),
        ("hyprland", None, "Hyprland", ["rolling", "tiling"]),
    ):
        base = f"https://iso.builds.garudalinux.org/iso/latest/garuda/{ed}/"
        line = fetch(base + "latest.iso.sha256").split()
        h, name = line[0].lower(), line[1].lstrip("*")
        ver = re.search(r"-(\d{6})\.iso$", name).group(1)
        url = f"https://iso.builds.garudalinux.org/iso/garuda/{ed}/{ver}/{name}"
        yield entry(
            f"garuda-{ed}", "Garuda Linux", ver, url, h,
            edition=ed.capitalize(), desktop=desktop, wm=wm, min_gib=30, rec_gib=60,
            homepage="https://garudalinux.org", tags=tags,
        )


# ---------------------------------------------------------------- Fedora ----

@source
def fedora():
    rel = latest(links(fetch("https://dl.fedoraproject.org/pub/fedora/linux/releases/"), r'href="(\d+)/"'))
    root = f"pub/fedora/linux/releases/{rel}"
    variants = [
        ("Workstation", "Workstation", "fedora-workstation", "Workstation", "GNOME", None),
        ("KDE", "KDE", "fedora-kde", "KDE Plasma Desktop", "KDE Plasma", None),
        ("Spins", "Xfce", "fedora-xfce", "Spin Xfce", "Xfce", None),
        ("Spins", "Cinnamon", "fedora-cinnamon", "Spin Cinnamon", "Cinnamon", None),
        ("Spins", "COSMIC", "fedora-cosmic", "Spin COSMIC", "COSMIC", None),
        ("Spins", "Sway", "fedora-sway", "Spin Sway", None, "Sway"),
        ("Spins", "i3", "fedora-i3", "Spin i3", None, "i3"),
    ]
    for d, key, id, edition, desktop, wm in variants:
        listing = fetch(f"https://dl.fedoraproject.org/{root}/{d}/x86_64/iso/")
        cks = links(listing, r'href="(Fedora-[^"]*-CHECKSUM)"')
        s = sums(fetch(f"https://dl.fedoraproject.org/{root}/{d}/x86_64/iso/{cks[0]}"))
        name = next(n for n in s if re.match(rf"Fedora-{re.escape(key)}(-Desktop)?-Live-", n) and n.endswith(".iso"))
        path = f"{root}/{d}/x86_64/iso/{name}"
        yield entry(
            id, "Fedora", rel, f"https://download.fedoraproject.org/{path}", s[name],
            edition=edition, desktop=desktop, wm=wm, profile="fedora",
            mirrors=[f"https://dl.fedoraproject.org/{path}"],
            homepage="https://fedoraproject.org", tags=["stable"] + (["tiling"] if wm else []),
        )


# ---------------------------------------------------------------- Ubuntu ----

def ubuntu_releases():
    vs = links(fetch("https://releases.ubuntu.com/"), r'href="(\d\d\.\d\d(?:\.\d+)?)/"')
    lts = latest([v for v in vs if v.split(".")[1] == "04" and int(v[:2]) % 2 == 0])
    regular = latest(vs)
    return lts, regular


@source
def ubuntu():
    lts, regular = ubuntu_releases()
    for rel, id, ed, tags in ((lts, "ubuntu-lts", "Desktop LTS", ["lts", "beginner"]),
                              (regular, "ubuntu", "Desktop", ["stable"])):
        if rel == lts and id == "ubuntu":
            continue
        s = sums(fetch(f"https://releases.ubuntu.com/{rel}/SHA256SUMS"))
        name = latest([n for n in s if re.match(r"ubuntu-[\d.]+-desktop-amd64\.iso$", n)])
        ver = name.split("-")[1]
        yield entry(
            id, "Ubuntu", ver, f"https://releases.ubuntu.com/{rel}/{name}", s[name],
            edition=ed, desktop="GNOME", profile="debian", min_gib=25, rec_gib=50,
            homepage="https://ubuntu.com", tags=tags,
        )


@source
def ubuntu_flavours():
    lts, _ = ubuntu_releases()
    for fl, name_, desktop in (("kubuntu", "Kubuntu", "KDE Plasma"), ("xubuntu", "Xubuntu", "Xfce"),
                               ("lubuntu", "Lubuntu", "LXQt"), ("ubuntu-budgie", "Ubuntu Budgie", "Budgie")):
        base = f"https://cdimage.ubuntu.com/{fl}/releases/{lts}/release/"
        s = sums(fetch(base + "SHA256SUMS"))
        n = latest([x for x in s if re.match(rf"{fl}-[\d.]+-desktop-amd64\.iso$", x)])
        yield entry(
            f"{fl}-lts", name_, n.split("-")[-3], base + n, s[n],
            edition="Desktop LTS", desktop=desktop, profile="debian", min_gib=25, rec_gib=50,
            homepage=f"https://{fl.replace('-', '')}.org" if fl != "ubuntu-budgie" else "https://ubuntubudgie.org",
            tags=["lts"],
        )


# ---------------------------------------------------------------- Debian ----

@source
def debian():
    live = "https://cdimage.debian.org/debian-cd/current-live/amd64/iso-hybrid/"
    s = sums(fetch(live + "SHA256SUMS"))
    for de, desktop in (("gnome", "GNOME"), ("kde", "KDE Plasma"), ("xfce", "Xfce"), ("cinnamon", "Cinnamon")):
        n = next(x for x in s if re.match(rf"debian-live-[\d.]+-amd64-{de}\.iso$", x))
        ver = n.split("-")[2]
        yield entry(
            f"debian-live-{de}", "Debian", ver, live + n, s[n],
            edition="Live", desktop=desktop, profile="debian",
            homepage="https://www.debian.org", tags=["stable"],
            notes="Installer via l'icône « Install Debian » (Calamares) de la session live.",
        )
    net = "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"
    s = sums(fetch(net + "SHA256SUMS"))
    n = next(x for x in s if re.match(r"debian-[\d.]+-amd64-netinst\.iso$", x))
    yield entry(
        "debian-netinst", "Debian", n.split("-")[1], net + n, s[n],
        edition="Netinst", profile="debian", homepage="https://www.debian.org",
        tags=["stable", "minimal"],
        notes="Installeur Debian ; choisir le partitionnement « tout dans une seule partition » (sans LVM).",
    )


@source
def mint():
    base = "https://mirrors.edge.kernel.org/linuxmint/stable/"
    rel = latest(links(fetch(base), r'href="(\d+(?:\.\d+)?)/"'))
    s = sums(fetch(f"{base}{rel}/sha256sum.txt"))
    for de, desktop in (("cinnamon", "Cinnamon"), ("mate", "MATE"), ("xfce", "Xfce")):
        n = f"linuxmint-{rel}-{de}-64bit.iso"
        yield entry(
            f"linuxmint-{de}", "Linux Mint", rel, f"{base}{rel}/{n}", s[n],
            edition="Desktop", desktop=desktop, profile="debian", min_gib=25, rec_gib=50,
            mirrors=[f"https://ftp.fau.de/mint/iso/stable/{rel}/{n}",
                     f"https://mirrors.layeronline.com/linuxmint/stable/{rel}/{n}"],
            homepage="https://linuxmint.com", tags=["stable", "beginner"],
        )


@source
def popos():
    for chan, ed in (("intel", "Intel/AMD"), ("nvidia", "NVIDIA")):
        j = json.loads(fetch(f"https://api.pop-os.org/builds/24.04/{chan}?arch=amd64"))
        yield entry(
            f"popos-{chan}", "Pop!_OS", f"{j['version']}-{j['build']}", j["url"], j["sha_sum"].lower(),
            edition=ed, desktop="COSMIC", profile="debian", min_gib=25, rec_gib=50,
            homepage="https://system76.com/pop", tags=["stable", "beginner"] + (["nvidia"] if chan == "nvidia" else []),
            notes="Décocher le chiffrement du disque dans l'installeur (LUKS non géré en v1).",
        )


@source
def kali():
    base = "https://cdimage.kali.org/current/"
    s = sums(fetch(base + "SHA256SUMS"))
    n = next(x for x in s if re.match(r"kali-linux-[\d.]+-installer-amd64\.iso$", x))
    yield entry(
        "kali-installer", "Kali Linux", n.split("-")[2], base + n, s[n],
        edition="Installer", desktop="Xfce", profile="debian", min_gib=25, rec_gib=50,
        homepage="https://www.kali.org", tags=["security", "rolling"],
    )


# --------------------------------------------------------------- openSUSE ---

@source
def opensuse_tumbleweed():
    base = "https://download.opensuse.org/tumbleweed/iso/"
    for ed, id, desktop in (("DVD", "opensuse-tumbleweed", None),
                            ("KDE-Live", "opensuse-tumbleweed-kde", "KDE Plasma"),
                            ("GNOME-Live", "opensuse-tumbleweed-gnome", "GNOME")):
        line = fetch(f"{base}openSUSE-Tumbleweed-{ed}-x86_64-Current.iso.sha256").split()
        h, name = line[0].lower(), line[1]
        snap = re.search(r"Snapshot(\d{8})", name).group(1)
        # URL principale : serveur d'origine (le redirecteur peut envoyer
        # vers un miroir pas encore synchronisé avec le nouvel instantané).
        yield entry(
            id, "openSUSE Tumbleweed", snap, f"https://downloadcontent.opensuse.org/tumbleweed/iso/{name}", h,
            mirrors=[base + name, f"https://ftp.fau.de/opensuse/tumbleweed/iso/{name}"],
            edition="DVD (installeur)" if ed == "DVD" else "Live", desktop=desktop, profile="opensuse",
            homepage="https://www.opensuse.org", tags=["rolling"], min_gib=30, rec_gib=50,
            notes="Instantané quotidien : l'entrée est régénérée automatiquement.",
        )


@source
def opensuse_leap():
    base = "https://download.opensuse.org/distribution/leap/16.0/offline/"
    n = latest(links(fetch(base), r'href="\.?/?(Leap-16\.0-offline-installer-x86_64-Build[\d.]+\.install\.iso)"'))
    h = fetch(base + n + ".sha512").split()[0].lower()
    yield entry(
        "opensuse-leap", "openSUSE Leap", "16.0",
        f"https://downloadcontent.opensuse.org/distribution/leap/16.0/offline/{n}", h,
        mirrors=[base + n, f"https://ftp.fau.de/opensuse/distribution/leap/16.0/offline/{n}"],
        edition="Offline installer", profile="opensuse", homepage="https://www.opensuse.org",
        tags=["stable"], min_gib=30, rec_gib=50,
    )


# ----------------------------------------------------------- NixOS, Void ----

@source
def nixos():
    # Versions publiées en mai (.05) et novembre (.11) : on essaie les plus
    # récentes d'abord.
    y = dt.date.today().year % 100
    candidates = [f"{yy:02d}.{mm}" for yy in (y, y - 1) for mm in ("11", "05")]
    for rel in candidates:
        try:
            final, _, _ = head(f"https://channels.nixos.org/nixos-{rel}/latest-nixos-graphical-x86_64-linux.iso")
        except Exception:
            continue
        h = fetch(final + ".sha256").split()[0].lower()
        ver = re.search(r"nixos-graphical-([\d.]+\.[0-9a-f]+)-", final).group(1)
        yield entry(
            "nixos-graphical", "NixOS", ver, final, h,
            edition="Graphical", desktop="GNOME / KDE Plasma (au choix)", profile="nixos",
            homepage="https://nixos.org", tags=["declarative"], min_gib=30, rec_gib=60,
            notes="Best-effort (§15) : liste d'apps et migration limitées par la configuration déclarative.",
        )
        return


@source
def void():
    base = "https://repo-default.voidlinux.org/live/current/"
    s = sums(fetch(base + "sha256sum.txt"))
    for ed, desktop in (("xfce", "Xfce"), ("base", None)):
        n = next(x for x in s if re.match(rf"void-live-x86_64-\d+-{ed}\.iso$", x))
        date = re.search(r"-(\d{8})-", n).group(1)
        yield entry(
            f"void-{ed}", "Void Linux", date, f"https://repo-default.voidlinux.org/live/{date}/{n}", s[n],
            edition="Live" if ed == "xfce" else "Base", desktop=desktop, profile="void",
            mirrors=[f"https://repo-fi.voidlinux.org/live/{date}/{n}",
                     f"https://mirrors.dotsrc.org/voidlinux/live/{date}/{n}"],
            homepage="https://voidlinux.org", tags=["rolling", "runit"] + (["minimal"] if ed == "base" else []),
            notes="Installer avec « void-installer » depuis la session live.",
        )


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "catalog.json"))
    args = ap.parse_args()
    out = Path(args.out)
    previous = {}
    if out.exists():
        previous = {d["id"]: d for d in json.loads(out.read_text())["distros"]}
    distros, failed = [], []
    for src in ENTRIES:
        try:
            got = list(src())
            if not got:
                raise RuntimeError("aucune entrée")
            distros.extend(got)
            for d in got:
                print(f"  ✔ {d['id']:<28} {d['version']:<22} {d['iso']['size_bytes'] / 2**30:5.2f} Gio", file=sys.stderr)
        except Exception as e:  # source en échec : on garde l'ancienne entrée
            failed.append(src.__name__)
            print(f"  ✘ {src.__name__} : {e}", file=sys.stderr)
            kept = [d for i, d in previous.items() if i.split("-")[0] == src.__name__.split("_")[0]]
            distros.extend(kept)
    ids = [d["id"] for d in distros]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        sys.exit(f"identifiants dupliqués : {dup}")
    cat = {
        "schema_version": 1,
        "updated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "distros": distros,
    }
    out.write_text(json.dumps(cat, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(distros)} entrées écrites dans {out}" + (f" ; sources en échec : {failed}" if failed else ""),
          file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
