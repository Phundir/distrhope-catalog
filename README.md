# distrhope-catalog

Catalogue des ISO proposées par distrhope (cahier des charges §6). distrhope
lit `catalog.json` à l'adresse brute de ce dépôt et en embarque un instantané
pour fonctionner hors ligne.

```
https://raw.githubusercontent.com/<compte>/distrhope-catalog/main/catalog.json
```

## Contenu

| Fichier | Rôle |
| --- | --- |
| `catalog.json` | le catalogue (généré, ne pas éditer à la main sauf ajout ponctuel) |
| `catalog.schema.json` | schéma JSON (draft 2020-12) du format |
| `scripts/generate.py` | régénère le catalogue depuis les sources officielles |
| `scripts/verify.py` | vérifie schéma, URLs et sommes de contrôle |
| `.github/workflows/verify.yml` | CI à chaque modification |
| `.github/workflows/update.yml` | mise à jour quotidienne automatique |

## Distros (40 entrées)

Arch Linux · CachyOS · EndeavourOS · Manjaro (KDE, GNOME, Xfce) · Garuda
(Dr460nized, GNOME, Hyprland) · Fedora (Workstation, KDE, Xfce, Cinnamon,
COSMIC, Sway, i3) · Ubuntu (LTS et dernière version) · Kubuntu · Xubuntu ·
Lubuntu · Ubuntu Budgie · Debian (live GNOME, KDE, Xfce, Cinnamon, netinst) ·
Linux Mint (Cinnamon, MATE, Xfce) · Pop!_OS (Intel/AMD, NVIDIA) · Kali ·
openSUSE Tumbleweed (DVD, KDE, GNOME) · openSUSE Leap · NixOS · Void (Xfce,
base).

## Comment chaque entrée est vérifiée

1. **Source officielle** : le nom de l'ISO et sa somme sont lus dans le
   fichier de sommes publié par la distro (`SHA256SUMS`, `CHECKSUM`,
   `*.sha256`, `*.sha512sum`, API de Pop!_OS…), jamais recopiés à la main.
2. **URL** : HTTP 200 après redirections, taille cohérente, idem pour chaque
   miroir et l'URL de signature (`verify.py`).
3. **Somme** : toute entrée nouvelle ou modifiée est entièrement téléchargée
   en flux par la CI (rien n'est écrit sur disque) et sa somme recalculée
   (`verify.py --full --changed-since`).
4. **Schéma** : validation `jsonschema` + règles (identifiants uniques,
   HTTPS, profil connu, taille minimale du slot cohérente).

Les signatures GPG (`signature_url`) sont renseignées quand la distro publie
une signature détachée de l'ISO ; distrhope les vérifie s'il connaît la clé.

## Utilisation

```sh
python3 scripts/generate.py           # régénère catalog.json
python3 scripts/verify.py             # schéma + URLs
python3 scripts/verify.py --full      # + téléchargement complet de TOUTES les ISO (~135 Go)
python3 scripts/verify.py --full --only archlinux,debian-netinst
```

## Ajouter une distro

Ajouter une fonction décorée par `@source` dans `scripts/generate.py` qui lit
le fichier de sommes officiel de la distro et renvoie `entry(...)`. Champs :
voir `catalog.schema.json`. `profile` est facultatif (détecté après
installation sinon) ; valeurs : `arch-mkinitcpio`, `arch-dracut`, `fedora`,
`debian`, `opensuse`, `void`, `nixos`.

Les distros dont l'installeur impose le chiffrement ou LVM, ou qui sont
« image-based » (ostree, bootc), ne sont pas incluses en v1 (§15).
