from odoo import api, fields, models

PARAM_ENABLED = "sale_credit_control.enabled"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Pas de config_parameter ici : une case décochée ferait supprimer le
    # paramètre par Odoo, et le contrôle retomberait sur sa valeur par
    # défaut (actif). On enregistre donc explicitement "True" / "False".
    credit_control_enabled = fields.Boolean(
        string="Contrôle du crédit client",
        help="Bloque la confirmation des commandes à risque et impose une dérogation.",
    )
    credit_overdue_tolerance_days = fields.Integer(
        string="Tolérance de retard (jours)",
        config_parameter="sale_credit_control.overdue_tolerance_days",
        default=30,
        help="Au-delà de ce nombre de jours de retard sur une facture, les commandes du client sont bloquées.",
    )
    credit_tolerance_pct = fields.Float(
        string="Tolérance de dépassement (%)",
        config_parameter="sale_credit_control.tolerance_pct",
        default=0.0,
        help="Dépassement du plafond accepté sans dérogation. Ex. : 5 % sur un plafond de 10 000 = 10 500.",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        value = self.env["ir.config_parameter"].sudo().get_param(PARAM_ENABLED, "True")
        res["credit_control_enabled"] = value == "True"
        return res

    def set_values(self):
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            PARAM_ENABLED, "True" if self.credit_control_enabled else "False"
        )
