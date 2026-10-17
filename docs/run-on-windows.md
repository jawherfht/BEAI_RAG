# Lancer BEAI RAG sur Windows (mode local, tout dans Docker)

Ce guide permet de lancer **tout le projet** sur un PC Windows et de le tester à la main
dans le navigateur (écran « Knowledge Base & RAG »). Vous avez seulement besoin de
**Docker Desktop** et de **Git**. Pas de Python, pas de Node, pas de WSL à utiliser vous-même.

Toutes les commandes se tapent dans **PowerShell**.

---

## 1. Ce qu'il faut sur le PC

| Élément | Minimum |
|---|---|
| Windows | Windows 10 (22H2) ou Windows 11, 64 bits |
| Mémoire (RAM) | **16 Go** dans le PC (Docker doit pouvoir utiliser **8 Go**) |
| Disque libre | **15 Go** (images Docker ≈ 6 Go, modèles d'IA ≈ 3 Go, données) |
| Internet | pour le premier lancement (téléchargement des images et des modèles) |

Avec 8 Go de RAM au total, le projet peut démarrer mais l'indexation des PDF sera très lente
ou s'arrêtera (manque de mémoire).

## 2. Installer les outils (une seule fois)

1. **Docker Desktop** : téléchargez-le sur https://www.docker.com/products/docker-desktop/
   et installez-le avec les options par défaut (moteur « WSL 2 »). Redémarrez le PC si demandé.
   Ouvrez Docker Desktop et attendez le message **« Engine running »** (en bas à gauche).
2. **Git** : téléchargez-le sur https://git-scm.com/download/win et installez-le avec les
   options par défaut.

Vérifiez dans PowerShell :

```powershell
docker --version
docker compose version
git --version
```

Les trois commandes doivent afficher un numéro de version.

## 3. Récupérer le projet

Choisissez un dossier (par exemple `C:\dev`) puis :

```powershell
mkdir C:\dev -Force
cd C:\dev
git clone --branch claude/new-session-dsncdj https://github.com/jawherfht/BEAI_RAG.git
cd BEAI_RAG
```

Le dépôt est privé : Git ouvre une fenêtre de connexion GitHub la première fois. Connectez-vous
avec votre compte.

## 4. Créer le fichier `.env` (votre clé reste sur votre PC)

```powershell
Copy-Item .env.windows.example .env
notepad .env
```

Dans le Bloc-notes, modifiez **une seule ligne** :

```
LLM_API_KEY=PASTE_YOUR_GOOGLE_AI_STUDIO_KEY_HERE
```

Remplacez `PASTE_YOUR_GOOGLE_AI_STUDIO_KEY_HERE` par votre clé Google AI Studio
(créez-la sur https://aistudio.google.com/apikey). Enregistrez et fermez.

Les autres lignes sont déjà prêtes :

```
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_MODEL=gemini-3.8-flash
LLM_THINKING_SWITCH=reasoning_effort
LLM_REASONING_EFFORT=low
```

- `gemini-3.8-flash` est le modèle Flash actuel de Google. Les modèles Gemini 3 ne permettent
  pas de couper complètement la « réflexion » : on la met au niveau le plus bas (`low`), ce qui
  garde des réponses rapides.
- Le fichier `.env` est ignoré par Git : **il n'est jamais envoyé sur GitHub**. Ne mettez
  jamais votre clé dans un autre fichier.

**Option Groq à la place de Gemini** : dans `.env`, mettez un `#` devant les 5 lignes Gemini et
enlevez le `#` devant les 5 lignes Groq, puis mettez votre clé Groq :

```
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=qwen/qwen3.8-27b
LLM_API_KEY=votre_cle_groq
LLM_THINKING_SWITCH=reasoning_effort
LLM_REASONING_EFFORT=none
```

## 5. Démarrer (une seule commande)

```powershell
docker compose -f docker-compose.windows.yml up -d --build
```

- **Premier lancement : 15 à 30 minutes.** Docker construit les images et télécharge le modèle
  d'embedding (≈ 1,2 Go). Au premier PDF, le worker télécharge aussi les modèles Docling.
- Les lancements suivants prennent environ 1 minute.
- La commande rend la main quand tout est démarré.

Vérifier l'état :

```powershell
docker compose -f docker-compose.windows.yml ps
```

Tous les services doivent être `Up` (ou `healthy`). Le service `migrate` doit être
`Exited (0)` : c'est normal, il prépare la base de données puis s'arrête.

## 6. Ouvrir l'application

```powershell
Start-Process http://localhost:3000
```

L'écran **Knowledge Base & RAG** s'ouvre (toujours le même agent de test : vos documents
restent là entre deux lancements).

L'écran est en français si votre navigateur est en français (sinon en anglais).

Test rapide :
1. Dans **« Fonder les réponses sur »**, glissez un fichier (PDF, DOCX, PPTX, TXT, MD, HTML)
   ou cliquez sur **« parcourir »**. Vous pouvez aussi utiliser **« + Ajouter une URL »**.
   Exemple fourni : `C:\dev\BEAI_RAG\eval\datasets\kb1_retail\returns-policy.pdf`.
2. Attendez que le statut du fichier passe à **Prêt** (quelques secondes à 1 minute
   sur CPU ; le tout premier PDF est plus long car les modèles Docling se téléchargent).
3. Dans **« Tester cet agent »**, posez une question, par exemple
   *What's your return policy?* puis **« Demander »** → réponse + source (fichier + page)
   + niveau de confiance.
4. Posez une question hors sujet → la **réponse de repli** s'affiche (« Aucun passage
   correspondant »).

La documentation de l'API est sur http://localhost:8000/docs.

## 7. Arrêter

```powershell
docker compose -f docker-compose.windows.yml down
```

Vos documents et les modèles téléchargés sont gardés. Pour **tout effacer** (base de données,
documents, modèles) :

```powershell
docker compose -f docker-compose.windows.yml down -v
```

## 8. Voir les journaux (logs)

```powershell
docker compose -f docker-compose.windows.yml logs -f rag-api
docker compose -f docker-compose.windows.yml logs -f ingestion-worker
```

`Ctrl + C` pour quitter l'affichage (les services continuent de tourner).

Après une mise à jour du code (`git pull`), relancez la commande de démarrage avec `--build`.

## 9. Erreurs fréquentes

| Message ou problème | Solution |
|---|---|
| `error during connect` / `Cannot connect to the Docker daemon` | Docker Desktop n'est pas démarré. Ouvrez-le et attendez « Engine running ». |
| `env file ... .env not found` | Le fichier `.env` manque : refaites l'étape 4 (dans le dossier `BEAI_RAG`). |
| `port is already allocated` (3000 ou 8000) | Un autre programme utilise ce port. Fermez-le, ou arrêtez l'autre conteneur (`docker ps` puis `docker stop <nom>`). |
| Le statut d'un document reste **Erreur** | Regardez `logs ingestion-worker`. Souvent : manque de mémoire. Dans Docker Desktop → Settings → Resources, donnez au moins 8 Go. Sur WSL 2, la limite se règle dans `%UserProfile%\.wslconfig` (`[wsl2]` puis `memory=8GB`), puis `wsl --shutdown`. |
| La réponse est toujours le message de repli, même pour une bonne question | Vérifiez la clé dans `.env` puis redémarrez : `docker compose -f docker-compose.windows.yml up -d`. Les logs de `rag-api` montrent `LLM returned 401` (clé fausse) ou `429` (quota gratuit dépassé : attendez ou passez à Groq). |
| `LLM returned 400` avec `reasoning_effort` | Le modèle n'accepte pas ce niveau. Mettez `LLM_REASONING_EFFORT=low` (Gemini 3) ou `none` (Gemini 2.5 / Groq). |
| `LLM returned 404` (modèle) | Le nom du modèle a changé chez Google. Vérifiez la liste sur https://ai.google.dev/gemini-api/docs/models et corrigez `LLM_MODEL`. |
| Le premier démarrage s'arrête sur `embed-server` (unhealthy) | Le téléchargement du modèle a été coupé (connexion). Relancez la commande de démarrage : il reprend. |
| `no space left on device` | Libérez de l'espace disque, puis `docker system prune` (supprime les images inutilisées). |
| `429 Too Many Requests` en téléchargeant une image Docker | Limite de Docker Hub. Attendez quelques minutes ou connectez-vous : `docker login`. |

## 10. Bon à savoir

- Le **re-ranker** est désactivé par défaut (trop lent sur CPU : plusieurs secondes par
  question). Pour l'essayer, ajoutez `RERANK_PROVIDER=local` dans `.env`, relancez la commande
  de démarrage, puis activez **« Reclassement haute précision (plus lent) »** dans l'écran.
- Ce mode est fait pour des **tests manuels sur un PC**. La production utilise le GPU, Vault et
  Helm (voir `docs/before-production.md`).
- Les secrets locaux (`JWT_SECRET`, clé Qdrant) dans `docker-compose.windows.yml` servent
  uniquement à ce mode local : aucun port de base de données n'est ouvert sur le réseau ;
  seuls `localhost:3000` et `localhost:8000` sont accessibles, depuis votre PC uniquement.

Pour les développeurs : `deploy/local/compose.test.yml` remplace le LLM par un faux LLM local
(sans clé ni quota) pour les tests automatiques du mode Docker.
