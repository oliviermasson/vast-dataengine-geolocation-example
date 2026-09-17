# Vast DataEngine - Geolocation Example

Fonction serverless [VAST DataEngine](https://support.vastdata.com/s/topic/0TO5e000000cN2AGAU/vast-dataengine) déclenchée par le dépôt d'une photo dans un bucket S3. Elle extrait les données EXIF de l'image (date, appareil, dimensions, coordonnées GPS), effectue une géolocalisation inverse (ville, région, pays, continent) puis enregistre le tout dans une table [VastDB](https://vastdata.com/vastdb).

> Exemple pédagogique : il illustre comment structurer, builder, déployer et faire évoluer une fonction VAST DataEngine avec le CLI `vastde`.

## Sommaire

- [Comment ça marche](#comment-ça-marche)
- [Contenu du dépôt](#contenu-du-dépôt)
- [⚠️ Sécurité / secrets](#️-sécurité--secrets)
- [Prérequis](#prérequis)
- [Récupérer le projet](#récupérer-le-projet)
- [Configuration](#configuration)
- [Créer la fonction sur VAST DataEngine](#créer-la-fonction-sur-vast-dataengine)
- [Déclencher la fonction (trigger S3)](#déclencher-la-fonction-trigger-s3)
- [Tester en local](#tester-en-local)
- [Publier une nouvelle release du code](#publier-une-nouvelle-release-du-code)
- [Push manuel de l'image Docker (sans `--push`)](#push-manuel-de-limage-docker-sans---push)
- [Uploader des photos dans le bucket](#uploader-des-photos-dans-le-bucket)
- [Schéma de la table VastDB](#schéma-de-la-table-vastdb)
- [Documentation officielle](#documentation-officielle)

## Comment ça marche

```
Upload photo (S3 bucket)
        │
        ▼  (trigger "element" sur ObjectCreated:*)
Fonction VAST DataEngine (main.py)
        │
        ├─ lit l'image depuis S3 (boto3)
        ├─ extrait les tags EXIF (exifread)
        ├─ géolocalisation inverse des coord. GPS (geolocation.py, reverse_geocode)
        └─ insère une ligne dans VastDB (vastdb / pyarrow)
```

`geolocation.py` contient la logique de reverse-geocoding pure (aucune dépendance à VAST DataEngine) : distance de Haversine, résolution ville/pays/continent à partir de coordonnées GPS, avec des seuils de distance pour éviter de renvoyer une ville ou un pays absurde quand la photo a été prise en pleine mer ou dans une zone polaire.

`main.py` est le handler de la fonction : lecture de l'événement S3, extraction EXIF, appel à `geolocation.py`, puis écriture du résultat dans VastDB (déduplication sur `source_photo`).

## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `main.py` | Handler de la fonction (`init` + `handler`) |
| `geolocation.py` | Reverse geocoding GPS → ville/région/pays/continent |
| `project.toml` | Configuration buildpack (schema-version, variables de build) |
| `requirements.txt` | Dépendances Python |
| `constraints.txt` | Contraintes de versions pour pip (opentelemetry) |
| `Aptfile` | Paquets apt additionnels (vide ici) |
| `customDeps` | Modules Python custom additionnels (vide ici) |
| `config.yaml.example` | Modèle des variables d'environnement non secrètes de la fonction déployée |
| `config_localrun.yaml.example` | Modèle du fichier utilisé par `vastde functions localrun -c ...` |
| `omgeoloc-secrets.yaml.example` | Modèle du bundle de secrets (credentials AWS/VastDB) monté sous `/secrets` |

Les trois fichiers `*.example` doivent être copiés **sans le suffixe `.example`** et remplis avec vos propres valeurs (voir [Configuration](#configuration)). Les copies remplies ne doivent jamais être committées — elles sont dans `.gitignore`.

## ⚠️ Sécurité / secrets

Le code Python (`main.py`, `geolocation.py`) ne contient **aucun secret en dur** : les identifiants AWS/VastDB sont lus depuis des fichiers montés sous `/secrets` ou, à défaut, depuis les variables d'environnement (fonction `read_secret`), et les endpoints viennent aussi de variables d'environnement. C'est cette raison qui permet de garder ces deux fichiers publics tels quels.

En revanche, les fichiers `config.yaml`, `config_localrun.yaml` et `omgeoloc-secrets.yaml` d'origine contenaient des **valeurs réelles** (access key / secret key AWS et VastDB, IP interne, hostname interne). Ils ont été retirés du dépôt public et remplacés par des versions `*.example` avec des valeurs bidons (`X.X.X.X`, `xxxxxxxxx`). Si vous retrouvez ces fichiers en local, ne les committez jamais (ils sont listés dans `.gitignore`).

## Prérequis

Sur la machine qui va builder/déployer/tester cette fonction :

- **VAST DataEngine CLI (`vastde`)** installé et **configuré** contre votre cluster VAST DataEngine (voir [installation](#documentation-officielle)).
- **Docker** (utilisé par `vastde functions build`/`localrun` pour construire et exécuter l'image de la fonction).
- Un accès à un bucket S3 (compatible S3, exposé par VAST) et à une base VastDB, avec les credentials associés.
- Python 3.12 en local uniquement si vous voulez exécuter/tester `geolocation.py` hors du conteneur (le build embarque déjà son propre runtime Python).

## Récupérer le projet

```bash
git clone https://github.com/oliviermasson/vast-dataengine-geolocation-example.git
cd vast-dataengine-geolocation-example
```

## Configuration

Copiez les modèles et remplissez-les avec vos propres valeurs :

```bash
cp config.yaml.example config.yaml
cp config_localrun.yaml.example config_localrun.yaml
cp omgeoloc-secrets.yaml.example omgeoloc-secrets.yaml
```

- `config.yaml` : variables d'environnement de la fonction une fois déployée (endpoint S3, endpoint VastDB, nom du bucket/schema/table VastDB). Les credentials, eux, sont fournis via le secret décrit dans `omgeoloc-secrets.yaml` et montés sous `/secrets` par VAST DataEngine.
- `omgeoloc-secrets.yaml` : définit le bundle de secrets (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `VASTDB_ACCESS_KEY`, `VASTDB_SECRET_KEY`) à créer côté VAST DataEngine et à associer à la fonction/au pipeline.
- `config_localrun.yaml` : fichier "tout-en-un" (endpoints + credentials en clair) utilisé uniquement pour les tests locaux avec `vastde functions localrun -c config_localrun.yaml`, puisqu'il n'y a pas de montage `/secrets` en local.

## Créer la fonction sur VAST DataEngine

Ces commandes supposent que `vastde` est déjà installé (voir [Prérequis](#prérequis)) et pointe vers votre cluster :

```bash
# Une seule fois par machine : configuration du CLI
vastde config init
vastde config set --vms-url https://votre-cluster-vast.example.com
vastde config set --username <votre_user> --password <votre_password> --tenant <votre_tenant>
vastde config view
```

Depuis la racine du projet :

```bash
# 1. Build de l'image de la fonction + push vers le registre configuré
vastde functions build . --handlers main.py --image-tag v1.19 --push

# 2. Création de la fonction à partir de l'image poussée
vastde functions create \
  --name omgeoloc \
  --container-registry <nom-ou-vrn-de-votre-registre> \
  --artifact-source <repo-image>/omgeoloc \
  --image-tag v1.19 \
  --publish
```

- `<nom-ou-vrn-de-votre-registre>` : un registre déjà déclaré côté VAST DataEngine (`vastde container-registries list` pour lister, `vastde container-registries link` pour en ajouter un).
- `--publish` rend cette révision immédiatement active.
- Les variables d'environnement (`config.yaml`) et le secret (`omgeoloc-secrets.yaml`) doivent être attachés à la fonction/au pipeline associé — reportez-vous à `vastde functions --help` / `vastde pipelines --help` sur votre version du CLI pour la syntaxe exacte de rattachement, celle-ci pouvant varier selon la version.

## Déclencher la fonction (trigger S3)

Pour que la fonction se déclenche automatiquement à chaque photo déposée dans le bucket :

```bash
vastde triggers create element \
  --name omgeoloc-on-upload \
  --source-bucket <nom-du-bucket-photos> \
  --event ObjectCreated:* \
  --name-suffix .jpg
```

Reliez ensuite ce trigger à la fonction `omgeoloc` via un pipeline (`vastde pipelines create --config ... --deploy`, puis `vastde pipelines deploy <nom>`) — voir la doc officielle pour le format exact du fichier de configuration du pipeline sur votre version du CLI.

## Tester en local

```bash
# Build local (sans push)
vastde functions build . --handlers main.py --image-tag dev

# Exécution locale du conteneur avec vos variables/secrets de test
vastde functions localrun . --config config_localrun.yaml --image-tag dev --port 8080

# Dans un autre terminal : envoyer un événement de test
vastde functions invoke --generate-event --url http://localhost:8080/
```

## Publier une nouvelle release du code

1. Modifiez `main.py` et/ou `geolocation.py`.
2. Incrémentez la variable `version` en tête de `main.py` (ex. `v1.19` → `v1.20`) — elle est logguée à chaque init/handler, ce qui facilite le suivi en prod.
3. Rebuild + push de l'image avec le nouveau tag :

   ```bash
   vastde functions build . --handlers main.py --image-tag v1.20 --push
   ```

4. Mettez à jour la fonction pour pointer vers la nouvelle image et publier la révision :

   ```bash
   vastde functions update omgeoloc \
     --container-registry <nom-ou-vrn-de-votre-registre> \
     --artifact-source <repo-image>/omgeoloc \
     --image-tag v1.20 \
     --publish
   ```

   Sans `--publish`, la commande crée une nouvelle révision sans la rendre active — utile pour un déploiement canary/manuel.
5. Committez le code (jamais les fichiers `config*.yaml`/`omgeoloc-secrets.yaml` réels) et taguez la release côté Git :

   ```bash
   git add main.py geolocation.py
   git commit -m "Bump function to v1.20"
   git tag v1.20
   git push origin main --tags
   ```

## Push manuel de l'image Docker (sans `--push`)

Si votre version de `vastde` ne propose pas encore l'option `--push` sur `functions build`, faites-le manuellement avec Docker :

```bash
# 1. Build local uniquement (pas de --push)
vastde functions build . --handlers main.py --image-tag v1.20

# 2. Repérez le nom/tag de l'image produite localement
docker images | grep omgeoloc

# 3. Authentifiez-vous auprès du registre cible
docker login <registre>.example.com

# 4. Re-taguez l'image vers le chemin du registre distant
docker tag omgeoloc:v1.20 <registre>.example.com/<repo-image>/omgeoloc:v1.20

# 5. Poussez l'image
docker push <registre>.example.com/<repo-image>/omgeoloc:v1.20

# 6. Puis créez/mettez à jour la fonction comme d'habitude
vastde functions update omgeoloc \
  --container-registry <nom-ou-vrn-de-votre-registre> \
  --artifact-source <repo-image>/omgeoloc \
  --image-tag v1.20 \
  --publish
```

## Uploader des photos dans le bucket

Remplacez `<endpoint>`, `<bucket>`, `<access-key>` et `<secret-key>` par vos propres valeurs (celles de votre `config.yaml`/`omgeoloc-secrets.yaml` réels, jamais celles des fichiers `.example`).

### Avec `s3cmd`

`~/.s3cfg` (extrait) :

```ini
[default]
access_key = <access-key>
secret_key = <secret-key>
host_base = <endpoint>          # ex: s3.example.com (sans http(s)://)
host_bucket = <endpoint>
use_https = True                # False si l'endpoint est en http://
signature_v2 = False
```

Upload :

```bash
s3cmd put photo.jpg s3://<bucket>/incoming/photo.jpg
s3cmd put ./photos/*.jpg s3://<bucket>/incoming/ --recursive
```

### Avec `aws s3` (AWS CLI)

```bash
export AWS_ACCESS_KEY_ID=<access-key>
export AWS_SECRET_ACCESS_KEY=<secret-key>

aws s3 --endpoint-url <endpoint> cp photo.jpg s3://<bucket>/incoming/photo.jpg
aws s3 --endpoint-url <endpoint> sync ./photos s3://<bucket>/incoming/
```

Astuce : pour éviter de répéter `--endpoint-url`, vous pouvez déclarer un profil dédié dans `~/.aws/config` avec `endpoint_url = <endpoint>` (nécessite une version récente de l'AWS CLI).

### Avec S3 Browser (client graphique Windows)

1. **Accounts → Add New Account**.
2. Type de compte : *S3 Compatible Storage*.
3. **REST Endpoint** : `<endpoint>` (décochez "Use secure transfer (SSL/TLS)" si l'endpoint est en `http://`).
4. **Access Key ID** / **Secret Access Key** : vos identifiants.
5. Une fois connecté, sélectionnez le bucket `<bucket>`, ouvrez/créez le dossier `incoming/`, puis glissez-déposez vos photos pour déclencher la fonction.

## Schéma de la table VastDB

La fonction insère une ligne par photo dans la table VastDB (`VASTDB_BUCKET` / `VASTDB_SCHEMA` / `VASTDB_TABLE`), avec déduplication sur `source_photo` :

| Colonne | Type | Description |
|---|---|---|
| `source_photo` | string | URI S3 de la photo (`s3://bucket/key`), clé de dédoublonnage |
| `maker` | string | Marque/modèle de l'appareil photo (EXIF `Make`/`Model`) |
| `date_exif` | date32 | Date de prise de vue (EXIF `DateTimeOriginal`/`DateTime`) |
| `width` / `height` | int32 | Dimensions de l'image |
| `gps_lat` / `gps_lon` | float64 | Coordonnées GPS décimales |
| `location` | string | Résumé lisible "Ville, État, Pays (Continent)" |
| `city` | string | Ville la plus proche (si dans un rayon raisonnable) |
| `region` | string | État/région |
| `country` | string | Pays |
| `continent` | string | Continent |

## Documentation officielle

- CLI VAST DataEngine (`vastde`) : https://github.com/vast-data/dataengine-cli
- Releases / binaires du CLI : https://github.com/vast-data/dataengine-cli/releases
- Référence complète des commandes : https://github.com/vast-data/dataengine-cli/blob/main/docs/references/commands/vastde.md
- Documentation VAST DataEngine (portail support VAST) : https://support.vastdata.com/s/topic/0TO5e000000cN2AGAU/vast-dataengine

Voir aussi [`MAINTENANCE.md`](MAINTENANCE.md) pour la checklist de sécurité/release de ce dépôt.
