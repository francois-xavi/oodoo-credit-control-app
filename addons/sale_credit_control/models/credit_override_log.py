from odoo import api, fields, models
from odoo.exceptions import UserError


class CreditOverrideLog(models.Model):
    """Journal d'audit des dérogations crédit.

    Chaque décision fige une photo de la situation au moment où elle est
    prise (encours, plafond, motif). Les lignes ne sont jamais modifiables
    ni supprimables : c'est une piste d'audit.
    """

    _name = "credit.override.log"
    _description = "Journal des dérogations crédit"
    _order = "date desc, id desc"
    _rec_name = "order_id"

    date = fields.Datetime(string="Date", required=True, default=fields.Datetime.now, readonly=True)
    order_id = fields.Many2one(
        "sale.order", string="Commande", required=True, readonly=True,
        ondelete="restrict", index=True,
    )
    partner_id = fields.Many2one("res.partner", string="Client", required=True, readonly=True, index=True)
    salesperson_id = fields.Many2one("res.users", string="Commercial", readonly=True)
    user_id = fields.Many2one("res.users", string="Décidé par", required=True, readonly=True)
    decision = fields.Selection(
        [("approved", "Approuvée"), ("refused", "Refusée")],
        string="Décision", required=True, readonly=True,
    )
    request_note = fields.Text(string="Justification du commercial", readonly=True)
    reason = fields.Text(string="Motif de la décision", required=True, readonly=True)
    block_reason = fields.Text(string="Motif du blocage", readonly=True)

    currency_id = fields.Many2one("res.currency", string="Devise de la commande", readonly=True)
    order_amount = fields.Monetary(string="Montant commande", currency_field="currency_id", readonly=True)
    company_currency_id = fields.Many2one("res.currency", string="Devise société", readonly=True)
    exposure_at_decision = fields.Monetary(
        string="Encours au moment de la décision", currency_field="company_currency_id", readonly=True,
    )
    limit_at_decision = fields.Monetary(
        string="Plafond au moment de la décision", currency_field="company_currency_id", readonly=True,
    )

    def write(self, vals):
        raise UserError("Le journal des dérogations est une piste d'audit : il ne peut pas être modifié.")

    @api.ondelete(at_uninstall=False)
    def _unlink_never(self):
        raise UserError("Le journal des dérogations est une piste d'audit : il ne peut pas être supprimé.")
