"""Données de démonstration du module « Contrôle du crédit client ».

Crée l'utilisateur commercial Paul et 4 clients qui racontent chacun une
situation métier. Le script est idempotent : un client déjà présent n'est
pas recréé.

Lancement (depuis odoo-demo/) :
    docker compose run --rm -T odoo odoo shell -d demo --no-http < scripts/seed_demo.py
"""
from datetime import timedelta

from odoo import fields

# Compte de test local (base `demo` sur cette machine uniquement).
PAUL_LOGIN = "paul"
PAUL_EMAIL = "paul@yourcompany.example.com"
PAUL_PASSWORD = "Paul-xaIvFHTFo-HS"

today = fields.Date.context_today(env.user)
Partner = env["res.partner"]
Move = env["account.move"]

# ----------------------------------------------------------------------
# 1. Utilisateur commercial : ventes uniquement, aucun droit comptable
# ----------------------------------------------------------------------
paul = env["res.users"].with_context(active_test=False).search([("login", "=", PAUL_LOGIN)])
if not paul:
    paul = env["res.users"].create({
        "name": "Paul Commercial",
        "login": PAUL_LOGIN,
        "password": PAUL_PASSWORD,
        "email": PAUL_EMAIL,
        "lang": "fr_FR",
        "tz": env.user.tz,
        "groups_id": [(6, 0, [
            env.ref("base.group_user").id,
            env.ref("sales_team.group_sale_salesman_all_leads").id,
        ])],
    })
    print("Utilisateur créé :", paul.name)
else:
    print("Utilisateur déjà présent :", paul.name)
# Odoo exige un e-mail d'expéditeur pour notifier les activités.
if not paul.email:
    paul.email = PAUL_EMAIL

# ----------------------------------------------------------------------
# 2. Produit sans taxe : des montants ronds, faciles à suivre en démo
# ----------------------------------------------------------------------
product = env["product.product"].search([("default_code", "=", "DEMO-FOURN")], limit=1)
if not product:
    product = env["product.product"].create({
        "name": "Fournitures professionnelles (lot)",
        "default_code": "DEMO-FOURN",
        "type": "consu",
        "list_price": 1000.0,
        "taxes_id": [(6, 0, [])],
    })
    print("Produit créé :", product.display_name)


def make_invoice(partner, amount, invoice_date, due_date):
    move = Move.create({
        "move_type": "out_invoice",
        "partner_id": partner.id,
        "invoice_date": invoice_date,
        "invoice_date_due": due_date,
        "invoice_payment_term_id": False,
        "invoice_line_ids": [(0, 0, {
            "product_id": product.id,
            "quantity": amount / 1000.0,
            "price_unit": 1000.0,
            "tax_ids": [(6, 0, [])],
        })],
    })
    move.action_post()
    return move


# ----------------------------------------------------------------------
# 3. Les 4 clients de démo
# ----------------------------------------------------------------------
CLIENTS = [
    {
        "ref": "DEMO-MARTIN",
        "name": "Boulangerie Martin",
        "city": "Lyon",
        "policy": "normal",
        "limit": 10000,
        "contact": "Marie Martin",
        "invoices": [(2000, 0, 30)],  # (montant, facturée il y a N jours, échéance dans N jours)
        "story": "Client sain : la commande passe sans friction",
    },
    {
        "ref": "DEMO-BTP",
        "name": "BTP Express",
        "city": "Marseille",
        "policy": "normal",
        "limit": 5000,
        "contact": "Karim Benali",
        "invoices": [(3000, 10, 20), (1500, 5, 25)],
        "story": "Encours 4 500 / 5 000 : une commande de 2 000 est bloquée",
    },
    {
        "ref": "DEMO-DURAND",
        "name": "Garage Durand",
        "city": "Bordeaux",
        "policy": "normal",
        "limit": 20000,
        "contact": "Luc Durand",
        "invoices": [(3200, 60, -60)],
        "story": "Gros plafond mais facture en retard de 60 jours : bloqué",
    },
    {
        "ref": "DEMO-ATLAS",
        "name": "Groupe Atlas",
        "city": "Paris",
        "policy": "exempt",
        "limit": 0,
        "contact": "Sophie Atlas",
        "invoices": [(50000, 15, 15)],
        "story": "Client stratégique exempté : jamais bloqué",
    },
]

for data in CLIENTS:
    company = Partner.search([("ref", "=", data["ref"])], limit=1)
    if company:
        print(f"Déjà présent : {data['name']}")
        continue
    company = Partner.create({
        "name": data["name"],
        "ref": data["ref"],
        "is_company": True,
        "city": data["city"],
        "country_id": env.ref("base.fr").id,
        "customer_rank": 1,
        "user_id": paul.id,  # Paul est le commercial attitré
        "credit_policy": data["policy"],
        "sale_credit_limit": data["limit"],
        "comment": data["story"],
    })
    Partner.create({"name": data["contact"], "parent_id": company.id, "type": "contact"})
    for amount, days_ago, due_in in data["invoices"]:
        make_invoice(company, amount, today - timedelta(days=days_ago), today + timedelta(days=due_in))
    print(f"Créé : {data['name']}")

env.cr.commit()

# ----------------------------------------------------------------------
# 4. Contrôle : situation de chaque client
# ----------------------------------------------------------------------
print()
print(f"{'Client':<20} {'Statut':<8} {'Plafond':>9} {'Encours':>9} {'Dispo':>9} {'Retards':>8} {'Max j':>6}")
for data in CLIENTS:
    p = Partner.search([("ref", "=", data["ref"])], limit=1)
    print(f"{p.name:<20} {p.credit_policy:<8} {p.sale_credit_limit:>9.0f} {p.credit_exposure:>9.0f} "
          f"{p.credit_available:>9.0f} {p.credit_overdue_count:>8} {p.credit_overdue_max_days:>6}")
