from odoo import fields, models


class CreditDecisionWizard(models.TransientModel):
    """Fenêtre unique pour les trois actions du circuit :
    demande du commercial, approbation ou refus du responsable.
    Le texte est obligatoire dans les trois cas."""

    _name = "credit.decision.wizard"
    _description = "Demande ou décision de dérogation crédit"

    order_id = fields.Many2one("sale.order", string="Commande", required=True, readonly=True)
    decision = fields.Selection(
        [
            ("request", "Demande de dérogation"),
            ("approved", "Approbation"),
            ("refused", "Refus"),
        ],
        string="Action", required=True, readonly=True,
    )
    reason = fields.Text(string="Motif", required=True)

    # Rappel du contexte pour décider en connaissance de cause
    block_reason = fields.Text(related="order_id.credit_block_reason", string="Motif du blocage")
    request_note = fields.Text(related="order_id.credit_request_note", string="Justification du commercial")
    currency_id = fields.Many2one(related="order_id.currency_id")
    amount_total = fields.Monetary(related="order_id.amount_total", string="Montant de la commande")
    salesperson_id = fields.Many2one(related="order_id.user_id", string="Commercial")

    def action_validate(self):
        self.ensure_one()
        if self.decision == "request":
            self.order_id._credit_request_override(self.reason)
        else:
            self.order_id._credit_decide(self.decision, self.reason)
        return {"type": "ir.actions.act_window_close"}
