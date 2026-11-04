# Démo Odoo 18 — Contrôle du crédit client

## Démarrer
    docker compose up -d
Puis ouvrir http://localhost:8069

## Accès locaux (base de test `demo`, uniquement sur cette machine)
- Utilisateur administrateur : `admin` / mot de passe `admin` (valeur par défaut d'Odoo à la création en ligne de commande)
- Mot de passe maître du gestionnaire de bases : voir `config/odoo.conf` (non versionné)

## Commandes utiles
- Logs : `docker compose logs -f --tail=100 odoo`
- Mettre à jour le module après un changement Python :
  `docker compose run --rm odoo odoo -d demo -u sale_credit_control --stop-after-init --no-http`
  puis `docker compose restart odoo`
- Arrêter : `docker compose down` (les données sont conservées dans les volumes)

## Plan de réalisation
Voir `../PLAN_REALISATION.md`
