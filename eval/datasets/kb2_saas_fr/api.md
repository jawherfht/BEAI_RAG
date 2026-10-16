# Nuvio - Référence de l'API

## Accès à l'API

L'URL de base de l'API est https://api.nuvio.example/v2. Chaque requête doit inclure un jeton personnel dans l'en-tête Authorization: Bearer. Les jetons personnels se créent dans Profil > Jetons d'API et expirent après un an.

## Limites

L'API autorise 600 requêtes par minute et par jeton. Au-delà de la limite, l'API renvoie le code HTTP 429 avec un en-tête Retry-After.

## Pagination

Les listes sont paginées par curseur avec 100 éléments au maximum par page.

## Webhooks

Les webhooks envoient les événements task.created, task.updated et project.archived. Chaque webhook est signé avec HMAC-SHA256 dans l'en-tête X-Nuvio-Signature. Un webhook en échec est renvoyé jusqu'à 5 fois avec un délai croissant.

## Codes d'erreur

Le code E-4031 signifie que le quota de stockage de l'espace est atteint. Le code E-4012 indique un jeton expiré ou révoqué. Le code E-4220 signale un champ obligatoire manquant dans le corps de la requête.

## Versions

La version v1 de l'API sera arrêtée le 31 mars 2027.

## SDK

Des SDK officiels existent pour JavaScript, Python et Go.

## Formats

Toutes les dates sont échangées au format ISO 8601 en UTC. Le corps des requêtes ne doit pas dépasser 1 Mo.

## Idempotence

L'en-tête Idempotency-Key évite de créer deux fois la même tâche lors d'une nouvelle tentative.

## Environnement de test

Un bac à sable est disponible sur https://sandbox.api.nuvio.example/v2 et ses données sont réinitialisées chaque dimanche.

## Recherche

Le paramètre updated_since filtre les tâches modifiées après une date donnée.
