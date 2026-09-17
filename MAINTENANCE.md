# Maintenance du dépôt

Checklist courte pour toute personne (ou tout agent Claude Code) qui intervient sur ce dépôt.

## Avant chaque commit / push

- [ ] `git status` : vérifier qu'aucun des fichiers suivants n'est suivi/ajouté : `config.yaml`, `config_localrun.yaml`, `omgeoloc-secrets.yaml` (ils sont dans `.gitignore`, mais un `git add -f` accidentel reste possible).
- [ ] Ne jamais coller une IP interne, un hostname interne ou une access/secret key en dur dans `main.py`, `geolocation.py`, `README.md` ou tout autre fichier versionné. Si un exemple est nécessaire, utiliser `X.X.X.X` pour une IP et `xxxxxxxxx` pour une clé (voir les fichiers `*.example`).
- [ ] Si un des fichiers `*.example` doit changer de forme (nouvelle variable d'env par ex.), répercuter le changement dans le fichier réel correspondant ET dans le `README.md`.

## Processus de release d'une nouvelle version de la fonction

Voir la section ["Publier une nouvelle release du code"](README.md#publier-une-nouvelle-release-du-code) du README. Résumé :

1. Modifier `main.py` / `geolocation.py`.
2. Incrémenter la variable `version` dans `main.py`.
3. `vastde functions build . --handlers main.py --image-tag vX.Y --push` (ou build+push manuel Docker si `--push` indisponible, voir README).
4. `vastde functions update omgeoloc --image-tag vX.Y --publish`.
5. Commit + tag Git (`git tag vX.Y`) + push.

## Rotation des secrets

Les credentials présents dans les anciens fichiers `config_localrun.yaml` et `omgeoloc-secrets.yaml` (avant leur retrait du suivi Git) doivent être considérés comme potentiellement exposés s'ils ont un jour été poussés sur un dépôt, même privé. En cas de doute, régénérer :

- l'access/secret key AWS S3 côté VAST,
- l'access/secret key VastDB côté VAST,

puis mettre à jour uniquement les copies locales non versionnées (`config_localrun.yaml`, `omgeoloc-secrets.yaml`) et le secret déployé côté VAST DataEngine.

## Fichiers à ne jamais committer

| Fichier | Contient |
|---|---|
| `config.yaml` | Endpoint S3, endpoint VastDB (infra interne) |
| `config_localrun.yaml` | Endpoints + access/secret keys AWS & VastDB en clair |
| `omgeoloc-secrets.yaml` | Access/secret keys AWS & VastDB en clair |

Ces trois fichiers ont leur pendant `*.example` versionné, qui sert de documentation/template.
