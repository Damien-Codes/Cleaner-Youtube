# Cleaner YouTube

Retrouvez **toutes les vidéos YouTube que vous avez likées**, filtrez-les par chaîne, par année ou par mot-clé, et rouvrez-les par lots de 5 onglets.

Le projet se présente sous deux formes indépendantes :

| | Site web statique | CLI locale |
|---|---|---|
| Fichiers | `index.html`, `assets/` | `main.py`, `src/` |
| Hébergement | **GitHub Pages** (aucun serveur) | votre ordinateur (Python 3.11+) |
| Connexion | Google Identity Services, dans le navigateur | OAuth « Application de bureau » + `token.json` |
| Données | cache dans **votre navigateur** (IndexedDB) | `data/likes_cache.json` |
| Extras | — | rapports par chaîne (`channels.txt`), nettoyage de l'historique (Playwright) |

```
.
├── index.html               # Site statique (GitHub Pages)
├── assets/
│   ├── app.js               # Connexion Google, API YouTube, cache IndexedDB, tableau de bord
│   ├── config.js            # GOOGLE_CLIENT_ID du site
│   └── style.css            # Thème sombre
├── main.py                  # Point d'entrée de la CLI
├── src/                     # Modules de la CLI
│   ├── auth.py              # OAuth 2.0 (application de bureau) + token.json
│   ├── youtube_client.py    # Résolution des chaînes, likes paginés, cache JSON
│   ├── report_generator.py  # Tableau de bord et rapports HTML
│   ├── browser_opener.py    # Ouverture par lots depuis le terminal
│   └── history_cleaner.py   # Nettoyage de l'historique (Playwright, optionnel)
├── channels.txt             # Chaînes suivies (exemple)
├── client_secrets.example.json
├── requirements.txt
├── data/  output/           # Données locales de la CLI (ignorées par Git)
└── LICENSE
```

> 🔒 **Confidentialité** : le dépôt ne contient aucune donnée personnelle. `client_secrets.json`, `token.json`, `.env`, `data/*` et `output/*` sont ignorés par Git. Ne les ajoutez jamais à un commit.

---

## Partie A — Site web sur GitHub Pages

Le site est **100 % statique** (HTML, CSS, JavaScript). Chaque visiteur se connecte avec **son propre compte YouTube** :

1. le navigateur obtient un jeton d'accès en lecture seule (`youtube.readonly`) via **Google Identity Services** (`google.accounts.oauth2.initTokenClient`) ;
2. les likes (playlist `LL`, 50 par page) sont lus directement sur `https://www.googleapis.com/youtube/v3/playlistItems`, avec une barre de progression ;
3. ils sont mis en cache **uniquement dans le navigateur du visiteur** (IndexedDB). Aucun serveur ne voit ses données ;
4. le tableau de bord sombre s'affiche : statistiques, chaînes triées par nombre de likes avec recherche, filtres par année (de publication ou de like) et par mot-clé, sections repliables par année, ouverture par lots de 5 onglets, export CSV/JSON ;
5. **Actualiser** relit les likes. **Supprimer mes données locales** vide le cache du navigateur et révoque le jeton (`google.accounts.oauth2.revoke`).

Le jeton d'accès reste en mémoire (jamais stocké) et expire au bout d'environ une heure. Un clic sur **Actualiser** en redemande un.

### A.1 Créer le projet Google Cloud

1. <https://console.cloud.google.com/projectcreate> → nommez le projet (ex. `cleaner-youtube`) → **Créer**.
2. **API et services → Bibliothèque** → **YouTube Data API v3** → **Activer**.
3. **Google Auth Platform → Présentation → Commencer** (écran de consentement) :
   - nom de l'application et adresse e-mail d'assistance ;
   - Cible : **Externe** ;
   - coordonnées du développeur, puis acceptez le règlement des services d'API Google.
4. **Google Auth Platform → Audience → Utilisateurs tests → + Add users** : ajoutez **votre adresse Gmail et celles des personnes autorisées** à utiliser le site.
   Tant que l'application est en mode « Test », **seuls ces comptes (100 au maximum) peuvent se connecter**. Les autres voient « Accès bloqué ». Pour ouvrir le site à tout le monde, il faut **publier** l'application et passer la **validation Google** (obligatoire pour le scope `youtube.readonly`).

### A.2 Créer l'ID client « Application Web »

1. **Google Auth Platform → Clients → Créer un client**.
2. Type d'application : **Application Web**. Nom : `Cleaner YouTube (GitHub Pages)`.
3. **Origines JavaScript autorisées** → **Ajouter un URI** :
   - `https://<pseudo>.github.io` (votre site GitHub Pages : **l'origine seule**, sans `/nom-du-depot` ni `/` final) ;
   - facultatif, pour tester en local : `http://localhost:8000`.
4. **URI de redirection autorisés** : laissez vide (le modèle « jeton » de Google Identity Services n'en a pas besoin).
5. **Créer**, puis copiez l'**ID client** (`123456789012-xxxx.apps.googleusercontent.com`).
   Le **code secret** n'est pas utilisé par le site : ne le publiez jamais.

> Google peut mettre quelques minutes à prendre en compte une nouvelle origine (erreur `origin_mismatch` en attendant).

### A.3 Configurer et publier

1. Dans `assets/config.js`, renseignez l'ID client :
   ```js
   const GOOGLE_CLIENT_ID = "123456789012-xxxx.apps.googleusercontent.com";
   ```
   Un ID client OAuth n'est **pas un secret** : il peut être publié. Si vous laissez la valeur vide, chaque visiteur peut saisir son propre ID client dans le panneau **Configuration** du site (enregistré dans son navigateur). C'est pratique pour un fork.
2. Poussez le dépôt sur GitHub, puis **Settings → Pages → Build and deployment** :
   - Source : **Deploy from a branch** ;
   - Branche : `main`, dossier **`/ (root)`** → **Save**.
3. Le site est publié sur `https://<pseudo>.github.io/<nom-du-depot>/` au bout d'une à deux minutes.

### A.4 Tester en local

La connexion Google ne fonctionne pas depuis un fichier ouvert directement (`file://`). Servez le dossier en HTTP :

```bash
python -m http.server 8000
```

Puis ouvrez <http://localhost:8000> (l'origine `http://localhost:8000` doit figurer dans les origines JavaScript autorisées).

### A.5 Ouverture par lots et pop-ups

Les navigateurs n'autorisent qu'**un** nouvel onglet par clic tant que les pop-ups ne sont pas autorisées pour le site. Les onglets bloqués s'affichent alors en liens à cliquer un par un. Pour ouvrir 5 onglets d'un coup, cliquez sur l'icône de pop-up bloquée dans la barre d'adresse → **Toujours autoriser**.

### A.6 Quota

Toutes les requêtes des visiteurs sont décomptées du quota **du projet Google Cloud** de l'ID client : 10 000 unités par jour par défaut. Une lecture complète coûte environ 1 unité par tranche de 50 likes, plus 1 unité pour identifier la chaîne. Par exemple, environ 100 unités pour 5 000 likes.

---

## Partie B — CLI locale (Python)

La CLI récupère vos likes, génère un tableau de bord HTML autonome (`output/dashboard.html`), des rapports par chaîne pour les chaînes de `channels.txt`, ouvre les vidéos par lots depuis le terminal et peut nettoyer l'historique YouTube (Playwright).

### B.1 Prérequis et identifiants

- Python **3.11 ou plus récent**.
- Le projet Google Cloud de l'étape [A.1](#a1-créer-le-projet-google-cloud), API YouTube activée et votre adresse dans les utilisateurs tests.

Créez un second ID client : **Google Auth Platform → Clients → Créer un client → Application de bureau** → **Créer** → **Télécharger au format JSON**. Enregistrez le fichier sous **`client_secrets.json`** à la racine du projet. Le format attendu est celui de `client_secrets.example.json`.

> En mode « Test », Google fait expirer le *refresh token* au bout de 7 jours. La CLI redemande alors simplement l'autorisation dans le navigateur.

### B.2 Installation

```bash
python -m venv .venv
# Windows : .\.venv\Scripts\Activate.ps1    macOS / Linux : source .venv/bin/activate
pip install -r requirements.txt
```

Optionnel, uniquement pour `--clean-history` :

```bash
pip install playwright
python -m playwright install chromium
```

### B.3 Chaînes suivies (`channels.txt`, facultatif)

Une URL par ligne. Les lignes vides et les commentaires `#` sont ignorés, et l'exemple `@GoogleDevelopers` n'est pas pris en compte. Formats acceptés : `https://www.youtube.com/@handle`, `/channel/UC…`, `/c/NomPersonnalise`, `/user/AncienNom`, `@handle`.
Chaque URL est résolue en `channelId` exact via l'API, ce qui garde le filtrage juste même si une chaîne change de nom.

### B.4 Utilisation

```bash
python main.py
```

1. **Premier lancement :** le navigateur s'ouvre pour autoriser l'accès en lecture seule, puis `token.json` est enregistré.
2. **Likes :** ils sont téléchargés avec une barre de progression, puis mis en cache dans `data/likes_cache.json`. Les lancements suivants lisent ce cache, sans réseau.
3. **Tableau de bord :** `output/dashboard.html` est généré puis ouvert. Il offre les mêmes fonctions que le site, plus le filtre « ★ Mes chaînes suivies » si `channels.txt` contient vos propres chaînes.
4. **Chaînes suivies :** pour chacune, un rapport `output/liked_<chaine>_<AAAAMMJJ>.html` est généré, et la CLI propose d'ouvrir ses vidéos par lots (Entrée = lot suivant, `q` = arrêter).

| Option | Effet |
|---|---|
| `--refresh` | Relit les likes depuis l'API (met à jour le cache) |
| `--no-open` | N'ouvre rien dans le navigateur |
| `--serve` / `--port N` | Sert le tableau de bord sur `http://127.0.0.1:8765` (pop-ups autorisables, 5 onglets par clic) jusqu'à Ctrl+C |
| `--open` | Ouvre sans confirmation les vidéos des chaînes de `channels.txt` |
| `--batch-size N` | Onglets par lot (défaut : 5) |
| `--asc` | Rapports par chaîne du plus ancien au plus récent |
| `--clean-history` | Nettoie l'historique YouTube via Playwright (confirmation exigée) |
| `--clean-scope channels\|all` | Éléments des chaînes de `channels.txt` (défaut) ou tout l'historique |
| `--channels-file`, `--client-secrets`, `--token`, `--cache`, `--output-dir` | Chemins personnalisés |
| `-v`, `--verbose` | Journalisation détaillée |

### B.5 Nettoyage de l'historique (`--clean-history`)

L'API YouTube Data v3 ne permet pas de supprimer l'historique de visionnage. La CLI pilote donc un navigateur (profil persistant dans `data/playwright_profile`) sur <https://myactivity.google.com/product/youtube> :

1. une confirmation explicite est demandée (taper `SUPPRIMER`) ;
2. vous vous connectez **vous-même** à votre compte Google dans la fenêtre ouverte, puis appuyez sur Entrée ;
3. mode `channels` : chaque chaîne est recherchée, le nombre d'éléments est affiché et une confirmation est demandée avant suppression. Mode `all` : le menu « Supprimer → Toute la période » de Google est utilisé.

Google modifie régulièrement cette interface : si un bouton est introuvable, la CLI vous laisse terminer à la main dans la fenêtre ouverte.

---

## Dépannage

| Problème | Solution |
|---|---|
| Site : « Accès bloqué » / `access_denied` | Ajoutez l'adresse Gmail dans **Audience → Utilisateurs tests**. |
| Site : `origin_mismatch` / `idpiframe_initialization_failed` | Ajoutez l'origine exacte du site (`https://<pseudo>.github.io`) dans les **Origines JavaScript autorisées**, puis patientez quelques minutes. |
| Site : la fenêtre Google ne s'ouvre pas | Autorisez les pop-ups pour le site ; désactivez les bloqueurs qui bloquent `accounts.google.com`. |
| Site : « Aucun ID client OAuth configuré » | Renseignez `assets/config.js` ou le panneau **Configuration**. |
| CLI : `Fichier d'identifiants OAuth introuvable` | Placez `client_secrets.json` à la racine (B.1). |
| CLI : `invalid_grant` / token expiré | Supprimez `token.json` et relancez. |
| `403 accessNotConfigured` | Activez **YouTube Data API v3** dans le projet Cloud. |
| `403 quotaExceeded` | Attendez la réinitialisation du quota (minuit, heure du Pacifique). |
| Moins de likes que prévu | Les vidéos supprimées ou privées n'ont plus de chaîne associée. Elles sont regroupées sous « Vidéos indisponibles ». |

## Licence

[MIT](LICENSE).
