from odoo import api, fields, models
from odoo.tools.misc import formatLang


class SaleOrder(models.Model):
    _inherit = "sale.order"

    credit_block_reason = fields.Text(
        string="Motif de blocage crédit",
        compute="_compute_credit_block_reason",
        help="Raison pour laquelle cette commande ne peut pas être confirmée "
        "sans dérogation. Vide = aucun risque crédit détecté.",
    )

    @api.depends("partner_id", "amount_total", "currency_id", "state")
    @api.depends_context("company")
    def _compute_credit_block_reason(self):
        for order in self:
            order.credit_block_reason = (
                order._get_credit_block_reason() if order.state in ("draft", "sent") else False
            )

    def _get_credit_block_reason(self):
        """Applique la politique de crédit et renvoie la raison du blocage
        (avec les chiffres), ou False si la commande peut être confirmée."""
        self.ensure_one()
        company = self.company_id or self.env.company
        partner = self.partner_id.commercial_partner_id.with_company(company)
        if not partner:
            return False

        params = partner._get_credit_params()
        if not params["enabled"] or partner.credit_policy == "exempt":
            return False

        def fmt(amount):
            return formatLang(self.env, amount, currency_obj=company.currency_id)

        # Règle 1 : client bloqué manuellement par le service financier
        if partner.credit_policy == "blocked":
            return "Client bloqué par le service financier : toute commande nécessite une dérogation."

        # Règle 2 : factures en retard au-delà de la tolérance
        tolerance_days = params["overdue_tolerance_days"]
        if partner.credit_overdue_count and partner.credit_overdue_max_days > tolerance_days:
            return (
                f"{partner.credit_overdue_count} facture(s) en retard pour "
                f"{fmt(partner.credit_overdue_amount)}, retard maximum "
                f"{partner.credit_overdue_max_days} jours (tolérance : {tolerance_days} jours)."
            )

        # Règle 3 : l'encours, cette commande comprise, dépasse le plafond
        order_amount = self.currency_id._convert(
            self.amount_total, company.currency_id, company,
            self.date_order or fields.Date.context_today(self),
        )
        exposure = partner.credit_exposure
        limit = partner.sale_credit_limit
        tolerance_pct = params["tolerance_pct"]
        if exposure + order_amount > limit * (1 + tolerance_pct / 100.0):
            message = (
                f"Encours {fmt(exposure)} + cette commande {fmt(order_amount)} = "
                f"{fmt(exposure + order_amount)}, pour un plafond de {fmt(limit)}"
            )
            if tolerance_pct:
                message += f" (tolérance de dépassement : {tolerance_pct:g} %)"
            return message + "."

        return False

    def _credit_approval_is_valid(self):
        """Dérogation accordée et toujours valable (complété à l'étape 5)."""
        self.ensure_one()
        return False

    def _confirmation_error_message(self):
        """Point d'extension natif appelé par action_confirm() pour chaque
        commande : la règle s'applique quelle que soit l'origine de la
        confirmation (bouton, API, import, automatisation)."""
        error = super()._confirmation_error_message()
        if error:
            return error
        reason = self._get_credit_block_reason()
        if reason and not self._credit_approval_is_valid():
            return (
                "Confirmation impossible : contrôle du crédit client.\n\n"
                f"{reason}\n\n"
                "Demandez une dérogation au responsable crédit."
            )
        return False
