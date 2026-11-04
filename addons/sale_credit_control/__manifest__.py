{
    "name": "Contrôle du crédit client",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "summary": "Bloque les commandes à risque (dépassement d'encours, retards de paiement) "
    "et impose une dérogation validée et tracée par le responsable financier.",
    "description": """
Contrôle du crédit client
=========================

Problème métier : les commerciaux confirment des commandes pour des clients
qui ne paient pas, les impayés s'accumulent et la trésorerie se dégrade.

Ce module :

* calcule l'encours de chaque client en temps réel (factures dues + commandes
  confirmées non facturées), au niveau de la société mère ;
* bloque la confirmation d'une commande en cas de dépassement du plafond,
  de retard de paiement ou de client bloqué ;
* impose une dérogation approuvée par un responsable crédit, avec motif
  obligatoire et journal d'audit non modifiable.
""",
    "author": "Démo entretien",
    "license": "LGPL-3",
    "depends": ["sale", "mail"],
    # Ordre de chargement : sécurité -> wizard -> vues -> menus.
    "data": [
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
    ],
    "installable": True,
    "application": False,
}
