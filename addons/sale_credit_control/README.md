# Contrôle du crédit client (`sale_credit_control`)

Module Odoo 18 Community.

## Le problème métier

Les commerciaux confirment des commandes pour des clients qui ne paient pas.
Les impayés s'accumulent, la trésorerie se dégrade, et personne n'arbitre
entre « vendre » et « être payé ».

Odoo propose nativement une alerte de limite de crédit, mais c'est un simple
avertissement que le commercial peut ignorer. Il n'y a ni blocage, ni contrôle
des retards, ni circuit d'approbation, ni piste d'audit.

## Ce que fait le module

**Encours en temps réel, par société cliente**
- Encours = factures et avoirs non soldés + commandes confirmées non facturées.
- Calculé au niveau de la société mère : une commande passée par un contact
  compte dans l'encours de sa société.
- Un paiement débloque le client immédiatement, sans action manuelle.

**Trois règles de blocage à la confirmation**
1. Client « Bloqué » par le service financier.
2. Facture en retard au-delà de la tolérance (30 jours par défaut).
3. Encours + commande > plafond (avec une tolérance de dépassement optionnelle).

Le commercial voit le risque dès la saisie (bandeau rouge chiffré), pas
seulement au moment de confirmer.

**Circuit de dérogation**
- Le commercial demande une dérogation avec une justification.
- Une activité « Dérogation crédit » est créée pour chaque responsable crédit.
- Le responsable approuve ou refuse, avec un motif obligatoire.
- La dérogation ne vaut que pour le montant approuvé : si la commande
  augmente, il faut une nouvelle dérogation.

**Audit et pilotage**
- Journal des dérogations : chaque décision fige la situation du client
  (encours, plafond, motifs). Lignes ni modifiables ni supprimables.
- Changements de plafond et de statut tracés dans l'historique du client.
- Liste « Situation crédit clients » avec filtres « En dépassement » et
  « Factures en retard ».

**Sécurité**
- Groupe « Responsable crédit » : seul à fixer les plafonds et à décider.
- Commercial : voit l'encours, demande des dérogations, ne peut rien s'accorder.

## Choix techniques

| Choix | Pourquoi |
|---|---|
| Contrôle branché sur `_confirmation_error_message()` | Point d'extension natif appelé par `action_confirm()` : bouton, API, import, automatisation sont tous couverts |
| Règles de sécurité dans `create()` / `write()`, pas seulement dans les vues | Masquer un bouton ne protège pas d'un appel API |
| État de dérogation dans un champ séparé, pas un nouvel état de commande | Ne casse ni le cycle de vie natif, ni les rapports, ni les autres modules |
| Encours en champs calculés non stockés, une requête groupée par client | Toujours exact sans synchronisation ; reste rapide sur une liste |
| Plafond et statut déclarés en « champs commerciaux » | Odoo les recopie automatiquement de la société vers ses contacts |
| Encours relu à jour avant chaque décision | Évite une décision sur une valeur en cache |
| Confirmation groupée contrôlée commande par commande | Plusieurs commandes du même client ne peuvent pas dépasser le plafond ensemble |
| Paramètre « Activer » enregistré explicitement en « True » / « False » | Une case Odoo décochée supprime le paramètre, ce qui réactiverait le contrôle |
| Type d'activité dédié | Les demandes se distinguent des autres tâches et se clôturent sans toucher au reste |

## Limites connues et évolutions possibles

- Un paiement reçu mais non lettré n'est pas déduit de l'encours (la
  comptabilité doit lettrer, ce qui est la bonne pratique).
- Un plafond à 0 signifie « aucun crédit » : au déploiement, fixer les
  plafonds avec la finance avant d'activer le contrôle.
- Les filtres sur l'encours calculent la situation de tous les clients : au-delà
  de quelques milliers de clients, stocker l'encours et le mettre à jour à
  chaque facture et paiement.
- V2 : blocage automatique quotidien des clients à plus de 60 jours de retard,
  e-mail hebdomadaire au directeur financier, analyse par commercial,
  plafond par société en multi-société.

## Tests

19 tests automatiques (`tests/test_credit_control.py`) : calcul de l'encours,
règles de blocage, circuit d'approbation, sécurité et immuabilité du journal.

    odoo -d <base_de_test> -i sale_credit_control --test-enable --test-tags /sale_credit_control --stop-after-init
