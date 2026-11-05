# Démo Odoo 18 — Contrôle du crédit client

## Démarrer
    docker compose up -d
Puis ouvrir http://localhost:8069

## Accès locaux (base de test `demo`, uniquement sur cette machine)
- Utilisateur administrateur : `admin` / mot de passe `admin` (valeur par défaut d'Odoo à la création en ligne de commande)
- Commercial de démo : `paul` / mot de passe dans `scripts/seed_demo.py` (constante `PAUL_PASSWORD`)
- Mot de passe maître du gestionnaire de bases : voir `config/odoo.conf` (non versionné)

## Données de démo
| Client | Statut | Plafond | Situation | Ce qu'il démontre |
|---|---|---|---|---|
| Boulangerie Martin | Normal | 10 000 | 2 000 dus, pas de retard | Client sain : la commande passe |
| BTP Express | Normal | 5 000 | 4 500 dus | Une commande de 2 000 est bloquée (dépassement) |
| Garage Durand | Normal | 20 000 | 3 200 en retard de 60 jours | Bloqué pour retard malgré un gros plafond |
| Groupe Atlas | Exempté | — | 50 000 dus | Client stratégique, jamais bloqué |

- Créer les données (idempotent, relançable sans doublons) :
  `docker compose run --rm -T odoo odoo shell -d demo --no-http < scripts/seed_demo.py`
- Sauvegarde de référence : `backups/demo_etape5.zip` (la plus récente) (non versionnée).
  Restaurer : http://localhost:8069/web/database/manager → « Restaurer une base », avec le mot de passe maître.
  Attention : les retards sont relatifs à la date de création des factures.

## Commandes utiles
- Logs : `docker compose logs -f --tail=100 odoo`
- Mettre à jour le module après un changement Python :
  `docker compose run --rm odoo odoo -d demo -u sale_credit_control --stop-after-init --no-http`
  puis `docker compose restart odoo`
- Arrêter : `docker compose down` (les données sont conservées dans les volumes)

## Plan de réalisation
Voir `../PLAN_REALISATION.md`
