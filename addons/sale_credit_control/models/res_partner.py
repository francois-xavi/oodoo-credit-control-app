from odoo import api, fields, models
from odoo.exceptions import AccessError

CREDIT_MANAGER_GROUP = "sale_credit_control.group_credit_manager"
CREDIT_POLICY_FIELDS = ("sale_credit_limit", "credit_policy")


class ResPartner(models.Model):
    _inherit = "res.partner"

    # ------------------------------------------------------------------
    # Politique de crédit (saisie par le service financier)
    # ------------------------------------------------------------------
    sale_credit_limit = fields.Monetary(
        string="Plafond de crédit",
        tracking=True,
        help="Encours maximum autorisé pour ce client (factures dues + commandes "
        "confirmées non facturées). 0 = aucun crédit accordé.",
    )
    credit_policy = fields.Selection(
        [
            ("normal", "Normal"),
            ("blocked", "Bloqué"),
            ("exempt", "Exempté"),
        ],
        string="Statut crédit",
        default="normal",
        required=True,
        tracking=True,
        help="Normal : plafond et retards contrôlés.\n"
        "Bloqué : aucune commande sans dérogation.\n"
        "Exempté : client stratégique, jamais bloqué.",
    )

    # ------------------------------------------------------------------
    # Situation calculée en temps réel (non stockée : toujours à jour,
    # un paiement débloque le client sans aucune action)
    # ------------------------------------------------------------------
    credit_invoiced_due = fields.Monetary(
        string="Factures dues", compute="_compute_credit_situation",
        help="Factures et avoirs comptabilisés non encore payés.",
    )
    credit_uninvoiced_orders = fields.Monetary(
        string="Commandes non facturées", compute="_compute_credit_situation",
        help="Commandes confirmées dont une partie reste à facturer (TTC).",
    )
    credit_exposure = fields.Monetary(
        string="Encours total", compute="_compute_credit_situation",
    )
    credit_available = fields.Monetary(
        string="Crédit disponible", compute="_compute_credit_situation",
    )
    credit_overdue_amount = fields.Monetary(
        string="Montant en retard", compute="_compute_credit_situation",
    )
    credit_overdue_count = fields.Integer(
        string="Factures en retard", compute="_compute_credit_situation",
    )
    credit_overdue_max_days = fields.Integer(
        string="Retard maximum (jours)", compute="_compute_credit_situation",
    )

    # ------------------------------------------------------------------
    # Le plafond et le statut sont gérés par la société mère : Odoo les
    # recopie automatiquement sur tous ses contacts.
    # ------------------------------------------------------------------
    @api.model
    def _commercial_fields(self):
        return super()._commercial_fields() + ["sale_credit_limit", "credit_policy"]

    # ------------------------------------------------------------------
    # Sécurité : seul un responsable crédit fixe la politique de crédit.
    # Contrôle dans le Python (et pas seulement dans l'écran) : il
    # s'applique aussi aux imports, à l'API et aux automatisations.
    # ------------------------------------------------------------------
    def _is_credit_manager(self):
        return self.env.su or self.env.user.has_group(CREDIT_MANAGER_GROUP)

    def _raise_credit_policy_access(self):
        raise AccessError(
            "Seul un responsable crédit peut modifier le plafond ou le statut crédit d'un client."
        )

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_credit_manager():
            for vals in vals_list:
                # Un contact hérite des valeurs de sa société : rien à contrôler.
                if vals.get("parent_id"):
                    continue
                if vals.get("sale_credit_limit") or vals.get("credit_policy", "normal") != "normal":
                    self._raise_credit_policy_access()
        return super().create(vals_list)

    def write(self, vals):
        if not self._is_credit_manager() and any(f in vals for f in CREDIT_POLICY_FIELDS):
            # On ne contrôle que les sociétés « commerciales » : sur les
            # contacts, Odoo recopie automatiquement les valeurs de la société.
            commercial = self.filtered(lambda p: p.commercial_partner_id == p)
            for partner in commercial:
                if any(
                    f in vals and partner[f] != vals[f]
                    for f in CREDIT_POLICY_FIELDS
                ):
                    self._raise_credit_policy_access()
        return super().write(vals)

    @api.model
    def _get_credit_params(self):
        """Paramètres globaux du contrôle de crédit (modifiables à l'étape 7)."""
        get = self.env["ir.config_parameter"].sudo().get_param
        return {
            "enabled": get("sale_credit_control.enabled", "True") == "True",
            "overdue_tolerance_days": int(get("sale_credit_control.overdue_tolerance_days", 30)),
            "tolerance_pct": float(get("sale_credit_control.tolerance_pct", 0.0)),
        }

    def _get_credit_due_invoices_domain(self, commercial_partners):
        """Factures et avoirs clients comptabilisés et non soldés."""
        return [
            ("company_id", "=", self.env.company.id),
            ("commercial_partner_id", "in", commercial_partners.ids),
            ("move_type", "in", ("out_invoice", "out_refund")),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
        ]

    @api.depends_context("company")
    def _compute_credit_situation(self):
        company = self.env.company
        today = fields.Date.context_today(self)
        commercials = self.commercial_partner_id._origin

        # sudo() : seuls des totaux sont affichés, le commercial n'a pas
        # forcément accès aux pièces comptables.
        Move = self.env["account.move"].sudo()
        due_domain = self._get_credit_due_invoices_domain(commercials)

        # Une requête groupée par client plutôt qu'une par fiche : reste
        # rapide même sur une liste de centaines de clients.
        due_by_partner = {
            partner.id: amount
            for partner, amount in Move._read_group(
                due_domain, ["commercial_partner_id"], ["amount_residual_signed:sum"]
            )
        }
        overdue_by_partner = {
            partner.id: (amount, count, oldest_due)
            for partner, amount, count, oldest_due in Move._read_group(
                due_domain + [("move_type", "=", "out_invoice"), ("invoice_date_due", "<", today)],
                ["commercial_partner_id"],
                ["amount_residual_signed:sum", "__count", "invoice_date_due:min"],
            )
        }

        uninvoiced_by_partner = {}
        orders = self.env["sale.order"].sudo().search([
            ("company_id", "=", company.id),
            ("partner_id.commercial_partner_id", "in", commercials.ids),
            ("state", "=", "sale"),
        ])
        for order in orders:
            amount = order.currency_id._convert(
                order.amount_to_invoice, company.currency_id, company, order.date_order or today
            )
            key = order.partner_id.commercial_partner_id.id
            uninvoiced_by_partner[key] = uninvoiced_by_partner.get(key, 0.0) + amount

        for partner in self:
            commercial = partner.commercial_partner_id._origin
            invoiced_due = due_by_partner.get(commercial.id, 0.0)
            uninvoiced = uninvoiced_by_partner.get(commercial.id, 0.0)
            overdue_amount, overdue_count, oldest_due = overdue_by_partner.get(
                commercial.id, (0.0, 0, False)
            )
            # Un avoir non encore lettré compense les factures échues : le
            # client ne peut pas être « en retard » de plus que ce qu'il doit.
            overdue_amount = max(0.0, min(overdue_amount, invoiced_due))
            if company.currency_id.is_zero(overdue_amount):
                overdue_amount, overdue_count, oldest_due = 0.0, 0, False

            partner.credit_invoiced_due = invoiced_due
            partner.credit_uninvoiced_orders = uninvoiced
            partner.credit_exposure = invoiced_due + uninvoiced
            partner.credit_available = commercial.sale_credit_limit - partner.credit_exposure
            partner.credit_overdue_amount = overdue_amount
            partner.credit_overdue_count = overdue_count
            partner.credit_overdue_max_days = (today - oldest_due).days if oldest_due else 0

    def action_view_credit_invoices(self):
        """Bouton « Encours » : liste des factures non soldées du client."""
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("account.action_move_out_invoice_type")
        action.update({
            "name": "Factures non soldées",
            "domain": self._get_credit_due_invoices_domain(self.commercial_partner_id),
            "context": {"default_move_type": "out_invoice", "create": False},
        })
        return action
