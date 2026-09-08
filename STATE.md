# TASHIL DOCUMENT HUB — WEB EDITION
## Documentation de traçabilité — v2.8.0

**Copyright :** ILINE TECH 2026 BY FERAK ALADDIN
**Date :** 2026-09-07

---

## 0. ⚠️ Pourquoi ce changement radical

La version précédente (CustomTkinter, application Windows native) a
échoué de façon répétée : écran figé au démarrage, bugs de positionnement
manuel des widgets (`place()`), erreurs PyInstaller liées à l'icône,
exceptions Windows/Tkinter avalées silencieusement sans jamais s'afficher.
Chaque correctif réglait un symptôme sans résoudre le problème de fond :
**une interface construite pixel par pixel avec Tkinter est intrinsèquement
fragile et difficile à déboguer à distance.**

**Nouvelle architecture : application web locale.**
- Un serveur Python (Flask) tourne en arrière-plan.
- L'interface est une page web standard (HTML/CSS/JS) — le moteur de
  rendu du navigateur gère TOUT le positionnement, plus aucun bug de
  géométrie possible.
- **Le même code fonctionne à l'identique sur Windows ET sur Android**
  (via Termux) — un seul projet, deux plateformes, sans réécriture.
- "Interface standard par défaut" : boutons, formulaires, défilement —
  aucun chrome de fenêtre personnalisé, uniquement des conventions web
  normales.
- Testé et vérifié dans ce sandbox : chaque route API a été exécutée
  réellement (pas seulement relue) — voir section 5.

---

## 1. Vue d'ensemble

- **Nom :** TASHIL DOCUMENT HUB — Web Edition
- **Type :** Application web locale (Flask + HTML/CSS/JS), responsive
- **Stack :** Python 3.11 + Flask + SQLite + JS vanilla (aucun build step,
  compatible Termux sans Node.js)
- **Windows :** `desktop_launcher.py` → compilé en `.exe` via PyInstaller,
  démarre le serveur puis ouvre le navigateur par défaut automatiquement
- **Android :** `python app.py` dans Termux, puis ouvrir
  `http://127.0.0.1:5000` dans Chrome — installable en PWA ("Ajouter à
  l'écran d'accueil") pour un rendu plein écran type application native
- **CI/CD :** GitHub Actions (Windows runner), `permissions: contents:
  write` déjà configuré pour que la création de Release fonctionne

---

## 2. Architecture fichiers

```
TASHIL-Web/
├── app.py                     # Backend Flask complet (routes + DB + logique métier)
├── desktop_launcher.py        # Lanceur Windows : démarre app.py + ouvre le navigateur
├── requirements.txt
├── tashil_web.spec            # PyInstaller config (icône optionnelle, ne casse jamais le build)
├── templates/
│   └── index.html             # Page unique (SPA), responsive
├── static/
│   ├── css/style.css          # Thème clair/sombre, sidebar desktop / barre mobile en bas
│   ├── js/app.js              # Logique frontend (fetch API, navigation, formulaires)
│   ├── manifest.json          # PWA — installable sur Android
│   └── assets/
│       ├── logo.png           # Emblème Ministère de la Santé (fourni par l'utilisateur)
│       └── icon.ico           # Icône .exe Windows
└── .github/workflows/
    └── build_windows.yml      # Build + Release automatique sur tag v*
```

---

## 3. Données — emplacement portable (plus de C:\TASHIL\...)

L'ancienne version écrivait dans `C:\TASHIL\...`, un chemin qui exige des
droits administrateur sur beaucoup de postes Windows verrouillés — cause
probable de plusieurs échecs silencieux. La nouvelle version utilise :

```
~/TASHIL_DATA/
├── tashil.db
└── archives/
    ├── Courrier_Sortant/   (YYYYMMDD_HHMMSS_[INSTITUTION]_[FICHIER])
    └── Courrier_Entrant/
```

`~` = `os.path.expanduser("~")`, qui résout vers `C:\Users\<utilisateur>\`
sur Windows et `/data/data/com.termux/files/home/` sur Termux/Android —
**aucun droit spécial requis, identique sur les deux plateformes.**

---

## 4. Fonctionnalités actuelles

| Module | Statut |
|--------|--------|
| Onboarding (Wilaya/Institution/Clé série) | ✅ Testé — génère une vraie clé HMAC, confirmé sur build Windows réel |
| Tableau de Bord (stats + activité récente) | ✅ Testé, confirmé sur build Windows réel |
| Messagerie — Envoi (upload + archivage + tracking) | ✅ Testé end-to-end, confirmé sur build Windows réel |
| Messagerie — Réception (avec accusé de réception) | ✅ Testé — voir section 8 |
| Accès réseau (URL LAN pour ouvrir depuis un téléphone) | ✅ Fonctionnel |
| Registre officiel (filtrable Entrant/Sortant/Tous) | ✅ Testé, confirmé sur build Windows réel |
| Téléchargement + suppression (Tableau de Bord, Réception, Registre) | ✅ Testé — voir section 8 |
| Notifications (toast + navigateur) envoi/réception | ✅ Testé — voir section 8 |
| Verrouillage / changement d'établissement (multi-profils) | ✅ Testé — voir section 10 |
| Code PIN par établissement + écran de verrouillage | ✅ Testé — voir section 10 |
| Isolation stricte des données entre établissements | ✅ Testé — voir section 10 |
| Dropdown dynamique Nom de l'établissement (onboarding) | ✅ Testé — voir section 10 |
| Thème clair/sombre | ✅ Fonctionnel, persisté en base + localStorage |
| PWA installable sur Android | ✅ manifest.json présent |
| Fenêtre native de bureau (pywebview) | ✅ Confirmé fonctionnel sur build Windows réel (v2.1.0) |
| Autocomplétion Institution destinataire | ✅ Confirmé fonctionnel (v2.1.0) |
| Vérification des mises à jour (GitHub Releases) | ✅ Confirmé fonctionnel — affiche "TASHIL est à jour" (v2.1.0) |
| Pied de page copyright | ✅ Ajouté — voir section 8 |

---

## 5. Vérification réelle effectuée (2026-08-25)

Contrairement aux versions précédentes, cette architecture a été
**réellement exécutée et testée** dans l'environnement de développement
(pas seulement relue) :
- `python3 app.py` démarre sans erreur
- `GET /` → 200, page HTML complète (6097 octets)
- `GET /static/css/style.css`, `/static/js/app.js`, `/static/assets/logo.png` → 200
- `GET /api/meta`, `/api/profile` → 200, JSON valide
- `POST /api/profile` (onboarding) → crée un profil réel avec clé série générée
- `POST /api/messages/send` avec upload de fichier → tracking number généré,
  fichier archivé avec le nommage standardisé, entrée DB créée
- `GET /api/dashboard`, `/api/messages`, `/api/registre` → reflètent les
  données réelles insérées

---

## 6. Prochaines étapes

1. ~~Tester le build Windows~~ — ✅ Fait, confirmé par l'utilisateur (fenêtre
   native pywebview fonctionnelle, envoi/dashboard/registre/paramètres
   tous opérationnels).
2. **Tester sur Android/Termux** : `pip install flask`, `python app.py`,
   ouvrir Chrome → `http://127.0.0.1:5000/` — reste à confirmer avec le
   navigateur (le serveur Termux a démarré avec succès, l'ouverture dans
   le navigateur du téléphone n'a pas encore été confirmée explicitement).
3. Décider du vrai mécanisme de transmission inter-institutions distant
   (au-delà du réseau local). Le point 2 (ci-dessous, validation
   utilisateur du 2026-08-26) propose GitHub (API/Releases/Actions) comme
   "Cloud Bridge" — **encore à concevoir et implémenter**, non fait à ce
   jour. Pistes : un dépôt privé faisant office de file d'attente de
   messages (chaque institution pousse/tire via l'API GitHub), ou un vrai
   service cloud dédié si le volume devient trop important pour GitHub.
4. Optionnel : ajouter un service worker pour un mode hors-ligne plus
   complet sur mobile (actuellement le manifest permet l'installation
   mais pas la mise en cache hors-ligne).
5. Le répertoire d'institutions (`INSTITUTIONS_DIRECTORY` dans `app.py`)
   reste un point de départ générique — à enrichir avec de vrais contacts
   au fur et à mesure (voir avertissement section 9).

---

## 7. Validation utilisateur (2026-08-26) + v2.1.0

L'architecture Web Edition a été validée par l'utilisateur après un test
réel sur build Windows (fenêtre native, envoi de document, dashboard,
registre, paramètres — tous confirmés fonctionnels par capture d'écran).

**Trois fonctionnalités ajoutées et testées (v2.1.0) :**
1. **Fenêtre de bureau native (pywebview)** — remplace l'onglet navigateur
   externe. `desktop_launcher.py` tente `pywebview` en premier ; en cas
   d'échec (WebView2 manquant, DLL non empaquetée), bascule
   automatiquement sur l'ouverture du navigateur par défaut — testé en
   simulant l'absence de pywebview, confirmé qu'aucune exception ne
   remonte. `tashil_web.spec` utilise `collect_all('webview')` pour
   empaqueter correctement les DLLs de la plateforme.
2. **Autocomplétion Institution destinataire** — `<input list="...">` +
   `<datalist>` standard HTML, alimenté par `/api/institutions` (192
   entrées : les 7 vraies polycliniques EPSP ES-SENIA + un gabarit
   générique `<Type> <Wilaya>` pour EPSP/EPH/Polyclinique + CHU limité aux
   11 wilayas qui en possèdent réellement un). **Répertoire de départ, pas
   un registre officiel vérifié** — à éditer avec de vrais contacts.
3. **Vérificateur de mise à jour intégré** — dans Paramètres, appelle
   `https://api.github.com/repos/Aladdinweb/TASHIL-ES/releases/latest`,
   compare les versions sémantiquement (pas une comparaison de chaînes),
   affiche une bannière de téléchargement si une version plus récente
   existe. Confirmé fonctionnel par l'utilisateur ("TASHIL est à jour").

**Point de transmission Cloud Bridge (noté, pas encore implémenté) :**
pour la transmission inter-institutions distante (hors réseau local),
l'utilisateur propose d'utiliser le dépôt GitHub (API/Releases/Actions)
comme pont de transmission sécurisé. Ceci reste à concevoir — voir
section 6, point 3.

---

## 8. v2.2.0 — Notifications, actions de liste, déconnexion, copyright (2026-08-27)

Quatre ajouts, tous testés réellement (serveur lancé, routes appelées via
`curl`, réponses JSON vérifiées) avant livraison :

1. **Notifications + accusé de réception**
   - Système de toasts en haut à droite (`showToast()`), déclenché à
     l'envoi d'un document ET à la réception d'un nouveau message.
   - Sondage en arrière-plan (`startBackgroundPolling()`, toutes les 8s)
     qui compare `total_received` au dernier total connu — si un nouveau
     message est arrivé, affiche un toast même si l'utilisateur n'est pas
     sur l'onglet Messagerie.
   - Notifications navigateur natives en complément (`Notification` API),
     avec détection de compatibilité et repli silencieux si indisponible
     (pywebview/WebView2 ne supporte pas toujours cette API).
   - **Accusé de réception** : bouton "✅ Accusé" sur chaque message reçu
     dans la Boîte de réception → `POST /api/messages/<id>/status` avec
     `{"status": "accuse"}` → le badge devient "✅ accusé" une fois
     confirmé. Testé via `curl`, changement de statut vérifié en base.
   - ⚠️ Limite actuelle : tout tourne sur la même base SQLite locale — il
     n'existe pas encore de vraie séparation réseau entre "expéditeur" et
     "destinataire" sur deux machines distinctes (voir point Cloud Bridge,
     section 6). L'accusé de réception fonctionne dès aujourd'hui pour un
     usage sur un même appareil/réseau local ; sa portée inter-
     institutions dépendra de l'implémentation du Cloud Bridge.

2. **Téléchargement et suppression** — Tableau de Bord (Activité Récente),
   Boîte de réception, et Registre affichent maintenant, par ligne :
   - 📥 Télécharger → ouvre `/api/messages/<id>/download` (route déjà
     existante en backend mais jamais reliée au frontend jusqu'ici — gap
     comblé).
   - 🗑️ Supprimer → confirmation, puis `DELETE /api/messages/<id>` qui
     retire l'entrée de la base ET le fichier archivé du disque. Testé :
     suppression confirmée en base ET absence du fichier vérifiée.

3. **Pied de page copyright** — `© ILINE TECH BY FERAK ALADDIN`, visible
   en bas de chaque vue (dans `<main>`, après Paramètres, donc toujours
   présent quel que soit l'onglet actif). Sur mobile, reste au-dessus de
   la barre d'onglets fixe grâce au padding déjà existant.

4. **Déconnexion / réinitialisation du profil** — carte "Session" dans
   Paramètres avec bouton de confirmation → `POST /api/profile/logout`
   supprime la ligne `profile` (mais PAS les messages/archives, décision
   délibérée : la déconnexion réinitialise l'identité de l'appareil, pas
   les données). Après confirmation, la page se recharge et l'assistant
   d'onboarding réapparaît. Testé via `curl` : `first_launch` repasse à
   `true` après l'appel.

**Fichiers modifiés :** `app.py`, `templates/index.html`,
`static/css/style.css`, `static/js/app.js`. Aucun fichier supprimé,
aucune fonctionnalité antérieure retirée.

---

## 9. ⚠️ Rappel — répertoire d'institutions non officiel

`INSTITUTIONS_DIRECTORY` dans `app.py` (utilisé par l'autocomplétion) est
un point de départ générique, PAS un registre national vérifié. Il
contient les 7 vraies polycliniques EPSP ES-SENIA et un gabarit
`<Type> <Wilaya>` pour le reste. À éditer avec de vrais contacts au fur
et à mesure — le champ accepte aussi la saisie libre pour tout ce qui
n'y figure pas encore.

---

## 10. v2.3.0 — Multi-tenant, code PIN, écran de verrouillage (2026-08-28)

Changement d'architecture significatif, entièrement testé en réel (serveur
lancé, chaque route/scénario vérifié via `curl` avant livraison — voir le
détail des tests en fin de section) : l'appareil peut désormais héberger
**plusieurs profils d'établissement isolés**, chacun protégé par son propre
code PIN.

### 10.1 Répertoire d'onboarding dynamique (dropdown)

Le champ "Nom de l'établissement" de l'assistant de configuration est
maintenant un `<select>` peuplé dynamiquement selon la Wilaya + le Type
choisis (`GET /api/institutions/onboarding?wilaya_code=&institution_type=`).
Seule la Wilaya 31 (Oran) contient des entrées réelles confirmées :
- **EPSP / Polyclinique** → les 7 vraies polycliniques EPSP ES-SENIA.
- **EPH** → `EPH AIN TURCK`.
- **CHU** → `CHU ORAN`.
- **EHU** → `EHU ORAN`.

Toute autre combinaison Wilaya/Type retombe sur une entrée générique
`<Type> <Wilaya>`. Une option **"Autre (saisir manuellement)"** est
toujours présente en dernier recours, avec un champ texte qui apparaît
dynamiquement — personne n'est jamais bloqué par une liste incomplète.
⚠️ Toujours pas un registre officiel vérifié, même remarque qu'en section 9.

### 10.2 Code PIN & écran de verrouillage

- Le formulaire d'onboarding exige désormais un **code PIN à 4-6 chiffres**
  (+ confirmation), stocké **hashé** (`werkzeug.security.generate_password_hash`
  — jamais en clair) dans la table `profiles` du registre.
- **Écran de verrouillage** (`lock-overlay`) affiché à chaque démarrage de
  l'application tant qu'aucun profil n'est déverrouillé : liste des
  établissements enregistrés sur l'appareil → sélection → saisie du PIN.
- Bouton 🔒 dans la barre supérieure + carte "Session" dans Paramètres
  permettent de verrouiller manuellement à tout moment sans fermer
  l'application (SPA — pas de rechargement de page).
- ⚠️ **Honnêteté sur le niveau de sécurité** : ce PIN est un verrou d'écran
  contre le survol/accès physique occasionnel sur un appareil partagé — ce
  n'est **pas** un chiffrement des données. Quiconque a un accès direct au
  système de fichiers (`~/TASHIL_DATA/profiles/<clé>/`) peut toujours lire
  les archives et la base SQLite directement, PIN ou non.
- ⚠️ **Limite de concurrence** : la session active est une simple variable
  en mémoire côté serveur — conçu pour une personne, un appareil, qui
  change de casquette, pas pour plusieurs utilisateurs simultanés sur le
  même processus serveur.

### 10.3 Isolation stricte multi-tenant

Nouvelle architecture de stockage :
```
~/TASHIL_DATA/
├── registry.db                          # Registre maître (profils, PIN hashés, thème)
└── profiles/
    └── <institution_key>/
        ├── tashil.db                    # Base de messages ISOLÉE à ce profil
        └── archives/
            ├── Courrier_Sortant/
            └── Courrier_Entrant/
```
`institution_key` est dérivé de la Wilaya + du Type + du nom (ex.
`31_EP_EPSP_ES_SENIA`), avec suffixe anti-collision si nécessaire.

**Déconnexion repensée** : "Déconnexion" ne supprime plus le profil (ancien
comportement v2.0-v2.2, jugé destructif). Elle **verrouille** simplement la
session — les données de l'établissement restent intactes et isolées,
récupérables en se reconnectant avec le PIN. Une nouvelle route
`POST /api/session/lock` remplace `POST /api/profile/logout` (supprimée).

**Migration automatique** : si une ancienne base `~/TASHIL_DATA/tashil.db`
(structure mono-profil pré-v2.3.0) est détectée au démarrage et qu'aucun
profil n'existe encore dans le registre, elle est **déplacée** (pas copiée)
vers `profiles/<clé>/` avec ses archives, sans PIN initial — l'écran de
verrouillage détecte ce cas (`pin_set: false`) et invite à **créer** un PIN
plutôt que d'en demander un qui n'a jamais existé. Rien n'est perdu.

### 10.4 Tests réels effectués avant livraison

Tous testés en lançant le serveur réel et en appelant les routes via `curl`
(pas seulement relus) :
- ✅ Session vide → `first_launch: true`
- ✅ Dropdown onboarding Oran/EPSP → 7 vraies polycliniques ; Oran/EPH →
  `EPH AIN TURCK` seul ; Adrar/EPSP → repli générique `EPSP Adrar`
- ✅ Création de profil A avec PIN → activation automatique, `pin_hash`
  jamais renvoyé au frontend
- ✅ Accès aux routes de données pendant que la session est verrouillée →
  `423` partout
- ✅ Mauvais PIN → `401` ; bon PIN → déverrouillage réussi
- ✅ **Isolation croisée** : création du profil B (CHU ORAN) → tableau de
  bord immédiatement à 0 message (aucune fuite depuis A) ; reverrouillage
  puis redéverrouillage de A → son message envoyé plus tôt est toujours là
- ✅ Séparation physique des dossiers vérifiée sur disque
  (`profiles/31_EP_.../` vs `profiles/31_CU_.../`)
- ✅ Migration héritée : base + archives pré-v2.3.0 simulées, migration
  automatique confirmée (fichiers physiquement déplacés, message hérité
  intact, PIN à créer détecté correctement, ancien chemin bien supprimé)
- ✅ Vérification statique croisée : chaque `getElementById(...)` de
  `app.js` correspond à un `id` réellement présent dans `index.html` (0
  référence orpheline — script de vérification automatisé, pas juste une
  relecture)
- ✅ Bug de listeners dupliqués anticipé et corrigé : comme le
  verrouillage/déverrouillage ne recharge plus la page, le câblage des
  événements (`setupNav`, `setupMessaging`, etc.) et `startBackgroundPolling`
  ne s'exécutent maintenant qu'**une seule fois** (`state.appInitialized`),
  pour éviter l'empilement de gestionnaires d'événements ou d'intervalles
  concurrents au fil des changements de profil dans une même session
  d'application.

**Fichiers modifiés :** `app.py` (réécriture substantielle),
`templates/index.html`, `static/css/style.css`, `static/js/app.js`.
Aucune fonctionnalité antérieure retirée — voir sections 1 à 9 pour
l'historique complet, toujours valable.

---

## 11. v2.3.1 — Corrections réelles suite à retour utilisateur (2026-08-28)

Deux signalements utilisateur après test sur build Windows réel, tous deux
identifiés comme de **vrais bugs**, pas des préférences cosmétiques.

### 11.1 🐛 Champs PIN non stylés (bug CSS réel)

**Cause :** la règle CSS de style des champs de formulaire ne ciblait que
`input[type="text"]` — or les 4 champs de code PIN utilisent
`type="password"`, donc ils ne recevaient AUCUN style personnalisé et
s'affichaient avec l'apparence par défaut du navigateur/WebView.

**Correctif :**
- Sélecteur CSS élargi à `input[type="password"]`, `input[type="tel"]`,
  `input[type="number"]`, `input[type="email"]` (pas seulement `text`).
- Nouvelle classe `.pin-input` appliquée aux 4 champs PIN (onboarding +
  écran de verrouillage) : grande taille de police, espacement des
  lettres, police monospace, centré — apparence "code d'accès" moderne
  plutôt qu'un champ texte générique.

### 11.2 🐛 Accès réseau non fonctionnel sur le build Windows (bug réel, pas juste UX)

**Cause racine :** `desktop_launcher.py` démarrait le serveur Flask avec
`host="127.0.0.1"` (boucle locale uniquement) — alors que
`app.py` (utilisé pour `python app.py` en Termux) utilise correctement
`host="0.0.0.0"`. Résultat : **sur le build Windows réel testé par
l'utilisateur, aucun appareil du réseau local ne pouvait jamais atteindre
le serveur**, quel que soit le Wi-Fi. Ce n'était pas "une mauvaise
méthode" comme perçu, mais un vrai bug de liaison réseau introduit lors
de l'écriture du lanceur desktop.

**Correctifs :**
1. `desktop_launcher.py` : `host="127.0.0.1"` → `host="0.0.0.0"`.
2. **QR code ajouté** (nouvelle demande implicite : "façon simple d'envoyer
   depuis mon téléphone sans tracas") — nouvelle route
   `GET /api/network-qr.png` qui génère à la volée un QR code encodant
   l'URL LAN (bibliothèque `qrcode` + `Pillow`, déjà utilisées avec succès
   dans l'ancienne version CustomTkinter du projet). L'onglet "Accès
   réseau" affiche maintenant ce QR code à scanner directement, plus un
   bouton "📋 Copier le lien" (Clipboard API), en plus du texte de l'URL
   conservé en repli.
3. Import `qrcode` protégé par `try/except ImportError` — si la
   dépendance venait à manquer sur un build, la route retourne `501`
   proprement au lieu de faire planter toute l'application au démarrage
   (leçon tirée des incidents précédents : ne jamais laisser une
   dépendance optionnelle bloquer tout le reste).
4. Note ajoutée dans l'interface : au tout premier lancement, **Windows
   Defender Firewall peut bloquer la connexion entrante** et afficher une
   invite — l'utilisateur doit cliquer "Autoriser l'accès" (réseaux
   privés) pour que le téléphone puisse réellement se connecter, même
   après le correctif de liaison réseau. Ce point était probablement une
   partie du problème observé, en plus du bug `127.0.0.1`.
5. `tashil_web.spec` : ajout de `collect_all('qrcode')` et
   `collect_all('PIL')`, même traitement que pour `pywebview` — évite les
   problèmes de sous-modules manquants dans l'exe empaqueté.

### 11.3 Tests effectués

- ✅ Route `/api/network-qr.png` testée réellement : HTTP 200, bon
  `Content-Type: image/png`, image PNG valide et décodable (vérifié avec
  Pillow). La bibliothèque `qrcode` elle-même n'a pas pu être installée
  dans le bac à sable de développement (pas d'accès PyPI en direct) — un
  module de substitution local a été utilisé uniquement pour valider la
  mécanique de la route Flask (BytesIO, mimetype, `send_file`). La
  bibliothèque réelle est la même que celle déjà éprouvée dans la version
  CustomTkinter précédente du projet.
- ✅ Comportement de repli sans `qrcode` installé : l'application démarre
  normalement, toutes les autres routes fonctionnent, seule la route QR
  renvoie `501` proprement (pas de plantage global).
- ✅ Vérification croisée de tous les `getElementById(...)` de `app.js`
  contre les `id` réels de `index.html` — 0 référence orpheline, refaite
  après ces modifications.
- ✅ Piège de listener dupliqué anticipé pendant cette modification même :
  `setupCopyLanUrl()` a été placé par erreur en dehors du bloc
  d'initialisation unique (`state.appInitialized`) puis corrigé avant
  livraison — sans ce correctif, chaque verrouillage/déverrouillage aurait
  réempilé un gestionnaire de clic supplémentaire sur le bouton copier.
- ⚠️ **Reste à vérifier par l'utilisateur** : le scan réel du QR code
  depuis un téléphone (impossible à tester depuis cet environnement de
  développement sans caméra/téléphone physique) — c'est le test le plus
  important restant avant de considérer ce correctif définitivement validé.

**Fichiers modifiés :** `app.py`, `desktop_launcher.py`,
`templates/index.html`, `static/css/style.css`, `static/js/app.js`,
`requirements.txt`, `tashil_web.spec`. Aucune fonctionnalité antérieure
retirée.

---

## 12. v2.4.0 — Livraison réelle des messages entre institutions (2026-08-29)

Signalement utilisateur : un message envoyé de EPSP ES SENIA vers
POLYCLINIQUE AADL AIN BEIDA MABROUK LOUCIF n'apparaissait jamais dans la
boîte de réception du destinataire. **Diagnostic confirmé : ce n'était pas
un bug, mais une fonctionnalité jamais construite.** L'isolation stricte
multi-tenant (v2.3.0) empêchait délibérément toute fuite entre profils,
mais la contrepartie — livrer réellement un message envoyé dans la boîte
du destinataire — n'existait pas encore. Envoyer un document n'écrivait
que dans le journal ET l'archive de l'expéditeur ; rien n'était jamais
transmis nulle part.

Deux mécanismes de livraison ont été ajoutés, correspondant aux deux
scénarios réels identifiés avec l'utilisateur.

### 12.1 Livraison locale (même appareil)

Quand l'expéditeur et le destinataire sont deux profils configurés sur
**le même ordinateur**, `POST /api/messages/send` recherche maintenant si
le nom du destinataire correspond à un autre profil enregistré localement
(`find_local_profile_by_name`, comparaison insensible à la casse/espaces).
Si trouvé :
- Le fichier est copié physiquement dans le `Courrier_Entrant` isolé du
  destinataire.
- Une entrée `entrant` est insérée dans la base SQLite propre au
  destinataire (complètement séparée de celle de l'expéditeur).
- Le même numéro de suivi (`tracking_number`) est utilisé des deux côtés
  pour la traçabilité — avec repli automatique en cas de collision rare
  entre deux bases indépendantes (`sqlite3.IntegrityError` → suffixe
  aléatoire, testé).

**Correctif de fond associé** : les numéros de suivi intègrent maintenant
un code d'institution court (`TASHIL-31EP-S-2026-000001` au lieu de
`TASHIL-S-2026-000001`) — nécessaire car un même numéro généré
indépendamment par deux institutions différentes aurait pu entrer en
collision une fois copié dans la base d'une seconde institution (les
compteurs `COUNT(*)` sont locaux à chaque base isolée).

**Testé réellement** : profil A créé, profil B créé, message envoyé de A
vers B, confirmé dans le tableau de bord de B (`total_received: 1`),
confirmé dans sa boîte de réception (expéditeur/objet corrects), fichier
physiquement présent dans son dossier d'archive isolé.

### 12.2 Cloud Bridge — livraison distante via GitHub (institutions sur des ordinateurs différents)

Pour les institutions sur des machines séparées, nouveau mécanisme de
transport utilisant un dépôt GitHub **privé** dédié comme file d'attente,
implémenté avec `urllib` de la bibliothèque standard uniquement (aucune
nouvelle dépendance pip, pour éviter tout nouveau risque d'empaquetage
PyInstaller comme rencontré avec pywebview).

**⚠️ Modèle de sécurité — à comprendre clairement avant utilisation :**
- Les documents sont commités en clair dans le dépôt — **aucun chiffrement
  de bout en bout**. La confidentialité du dépôt (privé) et le contrôle
  des accès qui y ont droit constituent la SEULE protection.
- L'application **refuse de sauvegarder une configuration pointant vers un
  dépôt public** — vérifié en direct via l'API GitHub
  (`GET /repos/{owner}/{repo}`, champ `private`) avant tout enregistrement.
  Testé : tentative contre un dépôt public simulé → rejetée avec `HTTP 400`
  et message explicite.
- Le jeton d'accès personnel GitHub est stocké tel quel (non chiffré) dans
  `registry.db` local — jamais renvoyé au frontend une fois enregistré
  (vérifié : `GET /api/bridge/config` n'inclut jamais `github_token`).
- Recommandation donnée à l'utilisateur : dépôt séparé et dédié,
  **jamais** le dépôt de code source `TASHIL-ES` lui-même (mélange de
  préoccupations, risque d'exposition si le dépôt de code est public).

**Fonctionnement :**
- `bridge_slug()` normalise le nom d'établissement en une adresse stable
  (ex. `POLYCLINIQUE_AADL_AIN_BEIDA_MABROUK_LOUCIF`) — chaque établissement
  possède ainsi un "dossier" prévisible dans le dépôt
  (`bridge/<adresse>/`), sans étape d'appairage manuelle. ⚠️ Adressage par
  nom uniquement (même limite que la livraison locale) — deux
  établissements différents portant exactement le même nom entreraient en
  collision ; à corriger si le sélecteur de destinataire devient un jour
  structuré (Wilaya + Type + Nom) plutôt qu'un texte libre.
- À l'envoi (`push_to_bridge`), si aucun profil local ne correspond ET que
  le Cloud Bridge est activé : métadonnées (JSON) + pièce jointe (base64)
  sont commitées dans `bridge/<adresse_destinataire>/<tracking>.json` et
  `bridge/<adresse_destinataire>/<tracking><ext>`.
- Côté destinataire (`POST /api/bridge/poll`, manuel ou automatique toutes
  les 45s en arrière-plan tant que le Bridge est activé) : liste le
  dossier `bridge/<sa_propre_adresse>/`, télécharge chaque entrée non
  déjà connue (vérification par `tracking_number` — idempotent, sûr à
  rappeler), l'insère comme message entrant isolé, PUIS supprime les
  fichiers consommés du dépôt (évite une file d'attente qui grossit
  indéfiniment).

**Nouvelle carte Paramètres** : "🌉 Cloud Bridge" — configuration
Propriétaire/Dépôt/Jeton, statut, bouton de vérification manuelle,
bouton de désactivation. Avertissement de sécurité affiché directement
dans l'interface, pas seulement en documentation.

**Testé réellement (avec un serveur GitHub Contents API factice construit
spécifiquement pour ce test, car cet environnement de développement n'a
pas d'accès réseau réel à api.github.com) :**
- ✅ Configuration acceptée contre un dépôt "privé" simulé
- ✅ Jeton jamais renvoyé par `GET /api/bridge/config`
- ✅ Envoi vers un destinataire SANS profil local → `delivered_via_bridge:
  true`, fichiers effectivement "commités" (stockés) sur le faux serveur
- ✅ **Cycle complet aller-retour** : profil A envoie → profil B (créé
  après coup, simulant un second appareil) interroge le Bridge → message
  correctement inséré dans SA propre base isolée avec expéditeur/objet/
  corps corrects → fichier physiquement présent dans son archive
- ✅ Re-sondage après réception → `new_messages: 0` (idempotence + nettoyage
  confirmés, pas de doublons)
- ✅ Configuration contre un dépôt PUBLIC simulé → refusée (`HTTP 400`)
- ✅ Non-régression : la livraison locale (section 12.1) fonctionne
  toujours après ces changements
- ⚠️ **Ce qui reste à vérifier par l'utilisateur, impossible à tester
  depuis ce bac à sable sans accès réseau réel** : le comportement contre
  la vraie API `api.github.com` (formats de réponse réels, limites de
  débit réelles, comportement du jeton réel). Le serveur factice reproduit
  fidèlement la forme des réponses GitHub documentées, mais un test avec
  un vrai dépôt privé et un vrai jeton reste la validation finale
  nécessaire avant usage en production.

**Fichiers modifiés :** `app.py` (ajouts substantiels : livraison locale,
client GitHub minimal, configuration et sondage du Cloud Bridge),
`templates/index.html`, `static/js/app.js`. Aucune fonctionnalité
antérieure retirée.

---

## 13. v2.5.0 — Provisioning QR (refus explicite du hardcoding) + routage par ID (2026-08-30)

### 13.1 ⚠️ Demande refusée, avec justification concrète

L'utilisateur a demandé d'intégrer directement dans `app.py` / les
fichiers de configuration un jeton GitHub et des identifiants
d'authentification **partagés et codés en dur**, pour que le Cloud Bridge
soit actif "out-of-the-box" sans configuration utilisateur.

**Cette demande a été refusée telle quelle**, et une alternative sûre a
été proposée puis construite à la place. Raisonnement, explicité
directement à l'utilisateur :
- L'application est distribuée sous forme d'exécutable Windows (`.exe`)
  installé sur les postes de plusieurs établissements de santé distincts.
  Un jeton codé en dur dans `app.py` se retrouve identique dans **chaque**
  copie distribuée.
- Extraction triviale : `strings TASHIL_DOCUMENT.exe | grep ghp_`, ou
  simple désassemblage du bundle PyInstaller, révèle la chaîne en quelques
  secondes. PyInstaller n'est pas un coffre-fort de secrets.
- Rayon d'impact total : un seul exécutable copié, volé, ou partagé lors
  d'un dépannage à distance suffit à compromettre l'accès en
  lecture/écriture à **tous** les documents de **tous** les établissements
  du réseau — l'exact opposé du modèle d'isolation stricte construit en
  v2.3.0.
- Un token compromis nécessiterait de le régénérer ET de redistribuer une
  nouvelle version à chaque poste pour le corriger — aucune révocation
  ciblée possible avec un secret partagé unique.

Deux alternatives ont été présentées : (A) provisioning par QR/code —
retenue et construite ci-dessous ; (B) un serveur relais dédié détenant
le vrai jeton côté serveur uniquement, avec une clé légère par
installation révocable individuellement — architecture correcte à long
terme mais projet d'infrastructure plus large (hébergement à choisir),
non construit cette fois-ci, à reconsidérer si le réseau grandit
significativement.

### 13.2 Provisioning par code / QR (ce qui a été construit)

Objectif atteint : **aucune saisie manuelle de propriétaire/dépôt/jeton
GitHub sur les appareils suivants**, sans jamais distribuer le vrai
secret dans le binaire de l'application.

- Un seul appareil ("premier appareil") effectue la configuration
  initiale une fois (formulaire manuel, maintenant replié sous
  "⚙️ Configuration manuelle (avancé)" dans Paramètres).
- Cet appareil peut ensuite générer un **code de provisioning** (chaîne
  encodée en base64 contenant owner/repo/token) et son équivalent en
  **QR code** (`GET /api/bridge/provisioning-qr.png`, réutilise le pipeline
  qrcode+Pillow déjà éprouvé pour l'accès réseau).
- Le nouvel appareil scanne ce QR avec **n'importe quel lecteur QR natif**
  (appareil photo du téléphone, Google Lens, etc. — pas de bibliothèque de
  décodage JS embarquée dans TASHIL, choix délibéré : évite les problèmes
  de permissions caméra/HTTPS dans une fenêtre pywebview embarquée, et
  évite de devoir reproduire à la main un algorithme de décodage QR non
  testable dans cet environnement de développement), copie le texte
  révélé, puis le colle dans le champ "Importer un code" — un seul
  copier-coller, zéro frappe de propriétaire/dépôt/jeton.
- `POST /api/bridge/import-code` réutilise **exactement** la même
  fonction de validation (`_validate_and_save_bridge_config`) que la
  saisie manuelle — la vérification "dépôt privé obligatoire" s'applique
  donc identiquement, peu importe le chemin d'entrée.
- Interface simplifiée comme demandé : badge "🟢 Réseau TASHIL Connecté"
  / "⚪ Non configuré" en premier plan ; le jeton n'est plus jamais
  affiché après sa saisie initiale (déjà le cas depuis v2.4.0, confirmé
  inchangé).

**⚠️ Rappel de sécurité affiché directement dans l'interface** : le QR/
code de provisioning contient le vrai jeton en clair (le base64 encode,
il ne chiffre pas) — à traiter comme le jeton lui-même. Ne le montrer
qu'en personne, à l'appareil qu'on provisionne soi-même.

### 13.3 Routage par ID d'établissement

- Chaque profil affiche maintenant son **"ID de routage TASHIL"** dans
  Paramètres (c'est en fait l'`institution_key` déjà généré en interne
  depuis v2.3.0 — juste rendu visible pour que les établissements puissent
  se le communiquer et lever toute ambiguïté de nom).
- `find_local_profile_by_name` renommé `find_local_profile_by_recipient`
  et étendu : reconnaît maintenant soit un ID exact, soit un nom
  d'établissement en texte libre, dans le champ destinataire — la
  livraison locale (section 12.1) fonctionne donc avec les deux.
- **Bug réel trouvé et corrigé pendant cette implémentation** : le sondage
  Cloud Bridge (`api_bridge_poll`) ne vérifiait qu'un seul dossier distant,
  adressé par le NOM de l'institution. Si un expéditeur adressait son
  envoi par ID plutôt que par nom, le message aurait été poussé vers un
  dossier différent que le destinataire n'aurait jamais consulté — perte
  silencieuse. Corrigé : le sondage vérifie maintenant les deux adresses
  possibles (nom ET ID) et fusionne les résultats.

### 13.4 Tests effectués

Toujours avec le serveur GitHub Contents API factice (voir section 12.2 —
pas d'accès réseau réel à `api.github.com` depuis ce bac à sable) :
- ✅ Génération du code de provisioning + décodage local confirmé
  (round-trip base64/JSON vérifié octet pour octet)
- ✅ Génération du QR de provisioning : PNG valide, HTTP 200
- ✅ **Flux complet réaliste** : Appareil A configure manuellement →
  génère un code → Appareil B (profil différent, simulant un second
  poste) importe ce code via `/api/bridge/import-code` **sans jamais
  fournir owner/repo/token lui-même** → statut confirmé connecté, jeton
  absent de la réponse
- ✅ Code de provisioning invalide/corrompu → rejeté proprement (`HTTP
  400`), pas de crash
- ✅ Vérification croisée de tous les `getElementById(...)` de `app.js`
  contre `index.html` — 0 référence orpheline
- ✅ Non-régression : livraison locale (section 12.1) et vérification
  anti-dépôt-public (section 12.2) toujours fonctionnelles après ces
  changements

**Fichiers modifiés :** `app.py` (refactorisation de la validation bridge
en fonction partagée, nouvelles routes de provisioning, correction du bug
de sondage à adresse unique, renommage de la fonction de correspondance
locale), `templates/index.html`, `static/css/style.css`,
`static/js/app.js`. Aucune fonctionnalité antérieure retirée.

---

## 14. v2.6.0 — Suppression définitive de profil (2026-08-30)

**Validation utilisateur préalable** : le Cloud Bridge en production
(`Aladdinweb/TASHIL-PRODUCTION-BRIDGE`) a été confirmé connecté et
fonctionnel par capture d'écran — badge "🟢 Réseau TASHIL Connecté", dépôt
actif affiché, QR de provisioning généré avec succès.

### 14.1 Problème signalé

Les profils créés (ex. EPSP ES SENIA, POLYCLINIQUE AADL) restaient
définitivement enregistrés sur l'appareil, sans possibilité de
suppression — seul le verrouillage ("Déconnexion") existait, qui préserve
délibérément les données (comportement voulu depuis v2.3.0, mais aucun
moyen de vraiment nettoyer un profil de test ou obsolète).

### 14.2 Fonctionnalité ajoutée

Nouvelle route `POST /api/profile/delete`, appelée uniquement sur le
profil **actuellement déverrouillé** (pas de suppression à distance d'un
profil qu'on n'a pas soi-même authentifié) :

1. **Confirmation de sécurité** : ré-saisie obligatoire du code PIN du
   profil (pas seulement une boîte de dialogue `confirm()` navigateur,
   trop facile à valider par clic accidentel pour une action qui détruit
   des documents archivés réels et irréversiblement). Testé : mauvais PIN
   → `HTTP 401`, rien n'est touché sur le disque (vérifié explicitement
   avant de tester la suppression réelle).
2. **À la suppression confirmée** :
   - Verrouillage immédiat de la session (`_active_key = None`) avant
     toute opération destructive, pour qu'aucun accès ultérieur à ce
     profil ne soit possible même en cas d'échec partiel du nettoyage.
   - Suppression de l'entrée dans `registry.db` (le profil disparaît
     immédiatement de la liste de sélection).
   - Suppression physique de tout le dossier isolé
     `~/TASHIL_DATA/profiles/<clé>/` — base SQLite ET archives
     (Courrier_Sortant + Courrier_Entrant) en un seul `shutil.rmtree()`.
   - Si la suppression des fichiers échoue partiellement (ex. fichier
     verrouillé par un antivirus ou un autre programme sous Windows), le
     profil est quand même retiré de la liste, mais un avertissement
     explicite est renvoyé au lieu d'échouer silencieusement en laissant
     des données orphelines sans le dire à l'utilisateur.
3. **Redirection après suppression** : retour à l'écran de sélection de
   profil s'il en reste d'autres sur l'appareil ; retour à l'assistant de
   configuration initiale si c'était le dernier profil (testé : `
   first_launch` repasse à `true` après suppression du seul profil
   existant).

**Isolation vérifiée à la suppression** : un second profil créé en
parallèle, non touché par la suppression du premier — dossier intact,
déverrouillage toujours fonctionnel, aucune donnée perdue ni mélangée.

### 14.3 Interface

Nouvelle carte "⚠️ Zone dangereuse" dans Paramètres, visuellement séparée
(bordure rouge) de la carte "🚪 Session" pour ne jamais confondre
verrouillage (réversible) et suppression (définitive). Modale de
confirmation dédiée avec rappel explicite de l'irréversibilité + champ PIN
(classe `.pin-input`, cohérent avec le reste de l'application).

### 14.4 Tests effectués

- ✅ Mauvais PIN → `401`, aucun fichier touché (vérifié par inspection du
  disque avant/après)
- ✅ Bon PIN → suppression réelle confirmée : dossier disparu du disque,
  entrée disparue du registre, session verrouillée automatiquement
- ✅ Second profil non affecté (isolation préservée)
- ✅ Suppression du dernier profil restant → `first_launch: true`,
  redirection vers l'onboarding plutôt qu'un écran de sélection vide
- ✅ Vérification croisée de tous les `getElementById(...)` de `app.js`
  contre `index.html` — 0 référence orpheline

**Fichiers modifiés :** `app.py` (nouvelle route `/api/profile/delete`),
`templates/index.html`, `static/css/style.css`, `static/js/app.js`.
Aucune fonctionnalité antérieure retirée.

---

## 15. v2.7.0 — Chiffrement, fiabilité du Cloud Bridge, accusés de réception, décodage QR, diagnostic réseau (2026-08-31)

Version majeure — six ajouts substantiels, tous testés réellement (serveur
lancé, serveur GitHub factice utilisé pour les scénarios distants, chaque
propriété vérifiée par appel API réel, pas seulement relue). Chaque
section ci-dessous inclut ce qui a été testé et, quand pertinent, les
limites honnêtes de ce qui a été construit.

### 15.1 Chiffrement au repos, dérivé du code PIN

**⚠️ Honnêteté sur le niveau de sécurité réel**, affichée à l'utilisateur
avant l'implémentation : un code PIN à 4-6 chiffres n'a que 10 000 à
1 000 000 de valeurs possibles. Même avec une fonction de dérivation de
clé lente (PBKDF2-HMAC-SHA256, 480 000 itérations), un attaquant en
possession d'une copie hors-ligne des fichiers chiffrés peut le retrouver
par force brute en temps raisonnable sur du matériel moderne. Ceci protège
contre la menace réaliste du quotidien (un appareil volé ou emprunté,
parcouru sans le PIN) — pas contre un attaquant déterminé et outillé.

**⚠️ Limite de conception réelle, documentée plutôt que cachée** : le
chiffrement s'applique uniquement au contenu que le propre profil
déverrouillé écrit lui-même (ses messages envoyés, et tout ce qu'il reçoit
via le Cloud Bridge en étant déverrouillé). La **livraison locale**
(v2.4.0) écrit directement dans le stockage d'un profil destinataire
pendant qu'il est verrouillé — son PIN n'est pas disponible à ce moment,
donc ce contenu reste en clair. Documenté, pas silencieusement ignoré.

**Conception technique :**
- Nouvelle colonne `encryption_salt` sur `profiles` (migration `ALTER
  TABLE` idempotente et rétrocompatible — les profils existants restent
  `NULL` = non chiffrés, continuent de fonctionner exactement comme avant ;
  seuls les profils créés à partir de v2.7.0 en bénéficient automatiquement).
  Un profil migré qui reçoit son PIN pour la première fois (`/api/session/set-pin`)
  génère aussi son sel à ce moment — il commence alors à chiffrer.
- Clé Fernet (AES-128-CBC authentifié, bibliothèque `cryptography`) dérivée
  via PBKDF2HMAC(PIN, sel, 480 000 itérations), mise en cache en mémoire
  UNIQUEMENT pendant la session déverrouillée (`_active_fernet`), effacée
  au verrouillage — jamais persistée sur disque.
- Fichiers archivés : chiffrés avant écriture, déchiffrés à la volée au
  téléchargement. Champs `subject`/`body` en base : chiffrés avant
  `INSERT`, déchiffrés systématiquement avant tout retour JSON
  (`decrypt_message_row`, appliqué à Tableau de Bord, Boîte de réception,
  Registre).
- **Bug de conception réel trouvé et corrigé pendant l'implémentation** :
  la copie propre de l'expéditeur est chiffrée avec SA clé — mais cette
  copie ne doit JAMAIS être celle transmise à la livraison locale ou au
  Cloud Bridge (le destinataire a une clé différente, ou aucune). Corrigé
  en lisant les octets originaux UNE SEULE FOIS à l'envoi et en les
  réutilisant tels quels pour toute autre destination — seule la copie
  propre de l'expéditeur passe par le chiffrement.

**Tests réels effectués :**
- ✅ Dérivation de clé déterministe (même PIN+sel → même clé), clés
  différentes pour PIN différents
- ✅ Chiffrement réel vérifié : contenu du fichier ET des colonnes
  subject/body sur disque confirmé illisible (jetons Fernet, pas du texte
  brut) — inspection directe des fichiers, pas seulement via l'API
- ✅ Cycle complet via l'API réelle : envoi avec sujet/corps sensibles →
  lecture via Tableau de Bord → contenu correctement déchiffré et lisible
- ✅ Téléchargement déchiffre correctement le fichier
- ✅ Mauvais PIN → `401`, déverrouillage refusé (pas de tentative de
  déchiffrement avec une mauvaise clé exposée à l'utilisateur)

### 15.2 Correction du bogue d'écran figé au verrouillage/déconnexion

**Cause trouvée par audit de code** (le bogue précis n'a pas pu être
reproduit littéralement dans cet environnement de développement, sans
pywebview réel) : `showLockScreen()` n'avait aucune gestion d'erreur
autour de son appel `fetch("/api/session")`, et ne réinitialisait jamais
explicitement la visibilité de ses éléments internes. Si cet appel
échouait pour une raison quelconque (aléa réseau, timing), l'exécution
s'arrêtait net, laissant l'écran de verrouillage affiché mais vide — sauf
le titre statique "TASHIL DOCUMENT HUB" déjà présent dans le HTML, ce qui
correspond exactement au symptôme décrit ("écran gris... affichant TASHIL
DOCUMENT HUB").

**Corrections :**
- `showLockScreen()` réinitialise maintenant explicitement l'état visible
  de tous ses sous-éléments à chaque appel, et enveloppe l'appel réseau
  dans un `try/catch` avec un bouton "🔄 Réessayer" en cas d'échec — plus
  jamais d'écran bloqué sans issue.
- `lockSession()` attend maintenant correctement `showLockScreen()`
  (`await` manquant auparavant).
- Même traitement appliqué à `confirmDeleteProfile()`, qui avait le même
  motif non protégé — et dont la logique a été restructurée pour que tout
  aléa réseau sur la redirection ne soit plus jamais rapporté comme un
  échec de la suppression elle-même (qui, à ce stade, a déjà réussi).

### 15.3 Notifications de bureau + son + accusés de réception via le Bridge

- **Son de notification** : généré programmatiquement via l'API Web
  Audio (deux tonalités brèves) — aucun fichier audio externe à empaqueter.
  ⚠️ Les navigateurs exigent une interaction préalable de l'utilisateur
  avant qu'`AudioContext` puisse jouer un son (politique anti-autoplay) —
  la toute première notification après le lancement pourrait donc rester
  silencieuse ; limitation connue du navigateur, pas un bogue. Le toast
  visuel et la notification système fonctionnent dans tous les cas.
- **Accusé de réception — routage réel, pas seulement un statut local** :
  - Si le message reçu provient d'une **livraison locale** (même
    appareil) : mise à jour instantanée et directe du statut côté
    expéditeur — testé réellement, confirmé en base de données.
  - Si le message provient du **Cloud Bridge** (appareil distant) : un
    petit objet "accusé" est poussé dans
    `bridge/<adresse_expéditeur>/receipts/<numéro>.json`. Au prochain
    sondage de l'expéditeur, l'accusé est appliqué à son message envoyé
    et une notification "📄 Le document [N°] a été consulté / réceptionné
    par [Établissement]" s'affiche (toast + son + notification système).
  - **Testé en conditions réelles simulant deux appareils séparés** :
    envoi → réception distante → accusé → sondage de l'expéditeur → statut
    mis à jour ET message de notification exact retourné par l'API.
  - Nouvelle colonne `delivery_method` sur `messages` (`local`/`bridge`/
    `NULL`) — c'est elle qui détermine vers où router l'accusé.

### 15.4 Retry-on-delete-failure (fiabilité du Cloud Bridge)

Nouvelle table `bridge_pending_cleanup` par profil : si une suppression
GitHub échoue juste après l'import réussi d'un message ou d'un accusé
(aléa réseau ponctuel), l'entrée est mise en file d'attente au lieu
d'être simplement abandonnée — car une fois importée, son numéro de suivi
est déjà connu localement, donc les sondages suivants l'auraient sinon
ignorée indéfiniment, laissant une copie orpheline invisible dans le
dépôt. Chaque sondage retente d'abord le nettoyage en attente avant de
traiter les nouvelles entrées. **Testé réellement** : entrée de nettoyage
injectée manuellement, confirmé nettoyée dès le sondage suivant.

### 15.5 Correction critique — erreur SSL sur le build Windows réel

**Signalée par capture d'écran réelle** : `SSL: CERTIFICATE_VERIFY_FAILED
— unable to get local issuer certificate`. Cause connue et bien
documentée dans l'écosystème PyInstaller : un exécutable Windows figé ne
retrouve souvent pas le magasin de certificats du système comme le ferait
une installation Python normale.

**Correctif** : toutes les requêtes HTTPS vers l'API GitHub utilisent
désormais explicitement le paquet de certificats racine fourni par
`certifi`, empaqueté avec l'application (`ssl.create_default_context(cafile=certifi.where())`)
— indépendant de l'état du magasin de certificats de l'OS.

⚠️ **Limite de test honnête** : cet environnement de développement a son
propre proxy réseau sortant qui intercepte le TLS avec un certificat
auto-signé, empêchant une vérification complète contre le vrai
`api.github.com` depuis ce bac à sable. Le test effectué confirme que le
code exerce réellement la vérification de certificat via `certifi` (erreur
différente et plus spécifique après le correctif : rejet correct d'un
certificat auto-signé non fiable, plutôt qu'absence totale de chaîne de
confiance) — mais la confirmation finale contre le vrai GitHub reste à
faire sur la machine réelle de l'utilisateur.

### 15.6 Décodage d'image QR (glisser-déposer + sélection de fichier)

Alternative au scan caméra natif pour le provisioning du Cloud Bridge —
utile si le QR a été enregistré/capturé en image et transféré autrement.

- **Bibliothèque retenue : `opencv-python-headless`**, pas `pyzbar`.
  Raisonnement explicite : `pyzbar` n'a pas pu être installé dans cet
  environnement de développement (pas d'accès direct à PyPI), donc son
  bon fonctionnement n'aurait jamais pu être réellement vérifié ici — alors
  qu'OpenCV, bien que nettement plus lourd et plus complexe à empaqueter
  (dépendance native la plus volumineuse de tout le projet à ce jour), a
  pu être testé pour de vrai, de bout en bout. Priorité donnée à "tester
  ce qui est réellement livré" plutôt qu'à la légèreté du paquet — compromis
  explicite, assumé et documenté plutôt que deviné.
  ⚠️ Si le futur exécutable rencontre un problème spécifiquement autour du
  décodage d'image QR, cette dépendance est la première à examiner.
- Nouvelle route `POST /api/bridge/decode-qr-image` : décode l'image
  envoyée, avec une nouvelle tentative en agrandissement (×2.5) si la
  détection échoue au premier passage (utile pour des images de petite
  taille ou peu contrastées).
- Interface : zone de glisser-déposer + bouton de sélection de fichier
  dans l'onglet Cloud Bridge non configuré ; le texte décodé alimente le
  champ existant "Coller le code" et repasse par le MÊME chemin de
  validation que la saisie manuelle (vérification anti-dépôt-public
  incluse).
- **Testé réellement, bout en bout, sans mock** : QR généré et encodé via
  l'encodeur natif d'OpenCV (car `qrcode` n'a pas non plus pu être
  installé ici) → agrandi avec zone de silence blanche → envoyé en tant
  que vrai fichier PNG via une vraie requête HTTP → décodé par la vraie
  route Flask → texte décodé identique à l'original, octet pour octet →
  réinjecté dans `/api/bridge/import-code` → Cloud Bridge réellement
  configuré au bout de la chaîne complète. Le cas d'échec (image sans QR)
  a aussi été testé : `HTTP 400` propre avec message clair, pas de crash.

### 15.7 Test de connectivité réseau (diagnostic Cloud Bridge)

Nouveau bouton "🔌 Tester la connexion à GitHub" dans la configuration
avancée — envoie une requête HTTPS minimale vers `api.github.com`
**sans en-tête d'authentification** (délibérément séparé de
`_github_request`, pour ne jamais confondre un problème réseau/SSL avec
un problème d'identifiants). Affiche le résultat avec un indice contextuel
selon le type d'erreur (certificat SSL, délai dépassé, DNS, connexion
refusée) — pensé spécifiquement pour aider à diagnostiquer rapidement les
postes bloqués par un pare-feu d'entreprise. **Testé réellement** :
détecte et rapporte correctement l'interception SSL de cet environnement
de développement, avec l'indice approprié.

**Fichiers modifiés :** `app.py` (ajouts substantiels sur tous les points
ci-dessus), `templates/index.html`, `static/css/style.css`,
`static/js/app.js`, `requirements.txt` (+ `cryptography`, `certifi`,
`opencv-python-headless`), `tashil_web.spec` (+ `collect_all` pour ces
trois nouvelles dépendances). Aucune fonctionnalité antérieure retirée.

---

## 16. v2.7.1 — Correctifs suite à validation réelle sur build Windows (2026-09-02)

Retour utilisateur avec captures d'écran du build v2.7.0 réellement
installé et testé.

### 16.1 ✅ Correctif SSL confirmé fonctionnel en conditions réelles

Le correctif certifi de la section 15.5 est **confirmé résolu** :
"Connexion à api.github.com réussie. (7264 ms)" — capture d'écran réelle
sur le poste de l'utilisateur, chose que cet environnement de
développement ne pouvait pas prouver lui-même (son propre proxy réseau
sortant intercepte le TLS). C'est la validation finale qui manquait.

### 16.2 🐛 Décodage d'image QR : échec confirmé en production, remplacé

**Signalé avec capture d'écran** : "⛔ Le décodage d'image QR n'est pas
disponible sur ce build" — `opencv-python-headless` (section 15.6) a
échoué à l'import dans l'exécutable réellement construit, malgré des
tests locaux réussis dans cet environnement de développement à chaque
étape. Ceci confirme précisément le risque documenté au moment de son
introduction ("dépendance native la plus volumineuse du projet à ce
jour... premier suspect en cas de problème").

**Décision : abandon d'OpenCV, remplacé par `pyzbar`.** Plutôt que de
continuer à deviner quel réglage PyInstaller pourrait réparer
l'empaquetage d'OpenCV (cycle de test coûteux : chaque tentative exige une
reconstruction Windows complète par l'utilisateur), remplacement par une
dépendance native fondamentalement plus simple et plus légère :
- `pyzbar` encapsule uniquement la bibliothèque C `zbar` — beaucoup moins
  de surface que le volumineux OpenCV, et son paquet Windows sur PyPI
  embarque directement la DLL nécessaire (`libzbar-64.dll`), sans
  installation système séparée requise.
- Réutilise **Pillow**, déjà confirmé fonctionnel dans ce build exact (la
  génération du QR de provisioning en dépend déjà avec succès en
  production) — préférable à l'introduction d'une nouvelle bibliothèque
  d'image.

**Amélioration de diagnostic ajoutée en parallèle** : l'échec silencieux
précédent ("non disponible sur ce build", sans aucune indication de la
cause réelle) est corrigé. Le message d'erreur `ImportError` réel est
maintenant capturé (`_QR_DECODE_IMPORT_ERROR`) et inclus dans la réponse
si le décodage échoue à nouveau — testé explicitement : le message
devient par exemple *"...(détail technique : No module named 'pyzbar')"*
au lieu d'un message générique. Si `pyzbar` rencontre lui aussi un
problème d'empaquetage, la cause sera visible immédiatement plutôt que de
nécessiter un nouveau cycle de capture d'écran et de diagnostic à
distance.

**⚠️ Limite de test honnête, à nouveau** : `pyzbar` n'a pas pu être
installé dans cet environnement de développement (pas d'accès PyPI en
direct) — impossible de garantir à 100% qu'il s'empaquette correctement
avant un vrai test sur le build Windows réel. La mécanique de la route
Flask (upload multipart, ouverture d'image PIL, gestion des erreurs) a
été testée avec un module de substitution local reproduisant l'interface
de `pyzbar.decode()`, mais pas la bibliothèque réelle elle-même — même
limite méthodologique que pour OpenCV précédemment, qui s'est avérée
insuffisante à elle seule pour garantir un empaquetage réussi. **Le test
le plus important restant : glisser une vraie image QR sur le prochain
build reconstruit.**

**Fichiers modifiés :** `app.py` (remplacement OpenCV → pyzbar + capture
du message d'erreur d'import réel), `requirements.txt`
(`opencv-python-headless` → `pyzbar`), `tashil_web.spec` (collection
PyInstaller mise à jour en conséquence). Aucune fonctionnalité antérieure
retirée.

---

## 17. v2.8.0 — Gestion d'erreurs JSON, Établissements Connectés, actualisation manuelle, cycle de vie "En attente" (2026-09-07)

### 17.1 🐛 Correctif critique : erreur JSON à l'envoi (PC bureau)

**Cause confirmée** : aucune gestion d'erreur globale n'existait sur les
routes `/api/` — toute exception non interceptée, ou tout dépassement de
la limite de taille de fichier (413), tombait dans la page d'erreur HTML
par défaut de Flask/Werkzeug. Le frontend appelait `res.json()` dessus,
provoquant exactement l'erreur rapportée : `Unexpected token '<',
"<!doctype "... is not valid JSON`.

**Correctif** : trois gestionnaires d'erreur globaux (`413`, `404`,
`Exception`) enregistrés au niveau de l'application — toute route `/api/`
renvoie désormais systématiquement du JSON, quoi qu'il arrive à
l'intérieur. La vraie exception est toujours journalisée côté serveur
pour diagnostic, jamais exposée telle quelle au frontend. Remplace
avantageusement l'idée initiale d'un `try/except` local à la seule route
d'envoi : la couverture est désormais totale, présente et future, sur
toutes les routes.

**Testé réellement** :
- ✅ Upload de fichier > 64 Mo → `HTTP 413`, JSON propre (au lieu de HTML)
- ✅ Route inexistante → `HTTP 404`, JSON propre
- ✅ Exception Python délibérément déclenchée dans une route de test →
  `HTTP 500`, JSON propre contenant le message d'erreur réel

**Bug réel supplémentaire trouvé et corrigé dans la foulée** : le
frontend ne vérifiait que `data.delivered_locally` après un envoi — si
`false`, il affichait systématiquement "archivé, non transmis", **même
si la transmission via le Cloud Bridge avait réellement réussi**
(`data.delivered_via_bridge` n'était jamais consulté). C'est très
probablement la cause de la confusion précédente de l'utilisateur face à
ce message. Corrigé : la logique distingue maintenant explicitement trois
cas — livré localement / livré via le Réseau TASHIL / réellement non
transmis — avec un message juste dans chaque cas.

Ajout d'un utilitaire `parseJsonResponse()` côté frontend (défense en
profondeur pour toute réponse non-JSON inattendue) — appliqué au flux
d'envoi, le plus critique ; les autres appels `fetch` du fichier
continuent d'utiliser `res.json()` directement, la couverture provenant
désormais principalement du correctif backend qui s'applique déjà à
toutes les routes.

### 17.2 Section "Établissements Connectés"

**⚠️ Contrainte de conception réelle, à comprendre** : le dépôt du Cloud
Bridge ne contenait jusqu'ici aucun registre des établissements — un
dossier `bridge/<adresse>/` n'apparaît que lorsqu'un envoi y a
effectivement été poussé. Impossible de répondre à "quels établissements
sont configurés/actifs" avec la seule structure existante. Un mécanisme
de présence explicite a été ajouté :
- Chaque appareil déverrouillé écrit périodiquement son propre fichier de
  présence dans `directory/<institution_key>.json`, greffé sur le cycle
  de sondage existant (aucune minuterie supplémentaire, donc aucun coût
  API GitHub additionnel au-delà du sondage déjà en place).
- Nouvelle route `GET /api/bridge/directory` : liste `directory/`, calcule
  "en ligne" si la dernière annonce date de moins de 3 minutes environ
  (~4 cycles de sondage de 45s manqués).
- **"Connecté" signifie concrètement "a annoncé sa présence récemment"** —
  un appareil resté fermé un moment repassera correctement "hors ligne"
  simplement parce qu'il a cessé de s'annoncer, pas parce qu'une panne a
  été détectée.
- Nouvel onglet "🏥 Établissements" dans la barre latérale, avec indicateur
  visuel (point vert/gris, réutilise le style déjà existant du badge Cloud
  Bridge) et horodatage relatif ("vu il y a X min").

**Testé réellement** : heartbeat émis lors d'un sondage → apparaît dans
l'annuaire comme "en ligne" ; second établissement simulé rejoint → les
deux apparaissent ; horodatage manuellement antidaté → passe
correctement à "hors ligne" au sondage suivant.

### 17.3 Bouton d'actualisation manuelle

Nouveau bouton "🔄" dans la barre supérieure — sonde le Cloud Bridge (sans
effet si non configuré) puis rafraîchit les données propres à la vue
actuellement affichée (Tableau de Bord, Boîte de réception + statistiques,
Registre avec son filtre actif, ou statut du Réseau TASHIL en
Paramètres), sans jamais nécessiter de redémarrage de l'application.
Animation de rotation pendant le chargement.

### 17.4 Cycle de vie du statut "En attente"

**Bug de fond trouvé** : le compteur "En Attente" du Tableau de Bord
comptait `status = 'en_attente'` — une valeur que rien, nulle part dans
le code, n'insérait jamais réellement (tout message sortant est créé
avec `status = 'envoye'`). Ce compteur affichait donc silencieusement
zéro depuis toujours.

**Redéfinition, testée et confirmée fonctionnelle** : "En Attente" compte
désormais les messages sortants dont le statut n'est PAS encore
`'accuse'` — c'est-à-dire "envoyés mais pas encore consultés/accusés par
le destinataire". `Total Envoyés` reste un compteur honnête et cumulatif
de tous les envois, indépendamment de leur état d'accusé (choix
délibéré : un "Total Envoyés" qui diminuerait ou ne compterait que les
messages accusés serait un intitulé trompeur).

**Testé réellement, cycle complet** : envoi → `pending: 1` → destinataire
accuse réception → `pending: 0`, `total_sent` toujours à `1`.

**Fichiers modifiés :** `app.py` (gestionnaires d'erreur globaux, requête
`pending` corrigée, mécanisme de heartbeat/annuaire), `templates/index.html`,
`static/css/style.css`, `static/js/app.js`. Aucune fonctionnalité
antérieure retirée.
