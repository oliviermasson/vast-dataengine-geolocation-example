---
name: vast-dataengine-release
description: Procédure pour builder, déployer et publier une nouvelle release de la fonction VAST DataEngine "omgeoloc" de ce dépôt (geolocalisation EXIF/VastDB), et pour vérifier l'absence de secrets avant tout commit.
---

# Release de la fonction omgeoloc (VAST DataEngine)

Ce skill décrit la procédure à suivre dans ce dépôt (`vast-dataengine-geolocation-example`) pour :
1. builder et publier une nouvelle version de la fonction,
2. vérifier l'hygiène des secrets avant de committer/pousser.

Se référer à `README.md` (sections "Créer la fonction sur VAST DataEngine", "Publier une nouvelle release du code", "Push manuel de l'image Docker") et à `MAINTENANCE.md` pour le détail complet ; ce fichier n'est qu'un aide-mémoire opérationnel pour un agent.

## Avant toute chose : vérifier les secrets

Ne jamais committer `config.yaml`, `config_localrun.yaml` ou `omgeoloc-secrets.yaml` (fichiers réels, avec vraies valeurs). Ils sont dans `.gitignore`. Avant un commit :

```bash
git status
git diff --cached -- config.yaml config_localrun.yaml omgeoloc-secrets.yaml
```

Si l'un de ces fichiers apparaît en staged, le `reset` avant de continuer. Ne jamais introduire d'IP interne / hostname interne / access-key / secret-key en clair dans un fichier versionné (`main.py`, `geolocation.py`, `README.md`, etc.) — utiliser `X.X.X.X` / `xxxxxxxxx` comme dans les fichiers `*.example`.

## Étapes de release

1. Modifier `main.py` et/ou `geolocation.py`.
2. Incrémenter la variable `version` en tête de `main.py` (ex. `v1.19` → `v1.20`).
3. Builder et pousser l'image :
   ```bash
   vastde functions build . --handlers main.py --image-tag vX.Y --push
   ```
   Si le CLI installé n'a pas l'option `--push` (versions anciennes de `vastde`), builder sans `--push` puis pousser à la main avec Docker (voir README, section "Push manuel de l'image Docker").
4. Publier la nouvelle révision de la fonction :
   ```bash
   vastde functions update omgeoloc \
     --container-registry <registre> \
     --artifact-source <repo-image>/omgeoloc \
     --image-tag vX.Y \
     --publish
   ```
5. Committer uniquement le code (jamais les fichiers de config réels) :
   ```bash
   git add main.py geolocation.py
   git commit -m "Bump function to vX.Y"
   git tag vX.Y
   git push origin main --tags
   ```

## Notes

- Les commandes `vastde` exactes (flags disponibles) peuvent varier selon la version du CLI installée sur la machine — vérifier avec `vastde functions build --help` / `vastde functions update --help` si une commande échoue.
- `vastde functions localrun . --config config_localrun.yaml --image-tag <tag> --port 8080` permet de tester en local avant de publier.
