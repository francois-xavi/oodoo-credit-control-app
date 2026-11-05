from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare
from odoo.tools.misc import formatLang

from .res_partner import CREDIT_SITUATION_FIELDS

CREDIT_MANAGER_GROUP = "sale_credit_control.group_credit_manager"
CREDIT_ACTIVITY_TYPE = "sale_credit_control.mail_activity_type_credit_override"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # ------------------------------------------------------------------
    # Blocage (étape 4)
    # ------------------------------------------------------------------
    credit_block_reason = fields.Text(
        string="Motif de blocage crédit",
        compute="_compute_credit_block_reason",
        help="Raison pour laquelle cette commande ne peut pas être confirmée "
        "sans dérogation. Vide = aucun risque crédit détecté.",
    )

    # ------------------------------------------------------------------
    # Circuit d'approbation (étape 5) : champ séparé du cycle de vie
    # natif de la commande, pour ne rien casser dans Odoo.
    # ------------------------------------------------------------------
    credit_approval_state = fields.Selection(
        [
            ("none", "Aucune"),
            ("pending", "Dérogation demandée"),
            ("approved", "Dérogation accordée"),
            ("refused", "Dérogation refusée"),
        ],
        string="Dérogation crédit",
        default="none",
        required=True,
        copy=False,
        tracking=True,
    )
    credit_request_note = fields.Text(string="Justification de la demande", copy=False, readonly=True)
    credit_approved_amount = fields.Monetary(
        string="Montant approuvé", copy=False, readonly=True,
        help="Montant de la commande au moment de l'approbation. Si la commande "
        "augmente au-delà, la dérogation ne vaut plus.",
    )
    credit_approval_valid = fields.Boolean(
        string="Dérogation valable", compute="_compute_credit_approval",
    )
    credit_can_request = fields.Boolean(compute="_compute_credit_approval")
    credit_last_decision = fields.Text(string="Dernière décision", compute="_compute_credit_approval")
    credit_override_ids = fields.One2many(
        "credit.override.log", "order_id", string="Dérogations", readonly=True,
    )

    @api.depends("partner_id", "amount_total", "currency_id", "state")
    @api.depends_context("company")
    def _compute_credit_block_reason(self):
        for order in self:
            order.credit_block_reason = (
                order._get_credit_block_reason() if order.state in ("draft", "sent") else False
            )

    @api.depends(
        "credit_approval_state", "credit_approved_amount", "amount_total",
        "credit_block_reason", "state", "credit_override_ids",
    )
    def _compute_credit_approval(self):
        for order in self:
            order.credit_approval_valid = order._credit_approval_is_valid()
            order.credit_can_request = bool(
                order.state in ("draft", "sent")
                and order.credit_block_reason
                and not order.credit_approval_valid
                and order.credit_approval_state != "pending"
            )
            last = order.credit_override_ids[:1]
            order.credit_last_decision = (
                f"{last.decision == 'approved' and 'Accordée' or 'Refusée'} par {last.user_id.name} "
                f"le {fields.Datetime.context_timestamp(order, last.date).strftime('%d/%m/%Y à %H:%M')} : "
                f"« {last.reason} »"
                if last else False
            )

    # ------------------------------------------------------------------
    # Règles de blocage
    # ------------------------------------------------------------------
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
        # Toujours décider sur l'encours à jour, jamais sur une valeur en cache
        partner.invalidate_recordset(CREDIT_SITUATION_FIELDS)

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
        order_amount = self._credit_amount_company_currency()
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

    def _credit_amount_company_currency(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        return self.currency_id._convert(
            self.amount_total, company.currency_id, company,
            self.date_order or fields.Date.context_today(self),
        )

    def _credit_approval_is_valid(self):
        """Dérogation accordée ET toujours valable : si la commande a augmenté
        depuis l'approbation, il faut une nouvelle dérogation (anti-contournement)."""
        self.ensure_one()
        return bool(
            self.credit_approval_state == "approved"
            and float_compare(
                self.amount_total, self.credit_approved_amount,
                precision_rounding=self.currency_id.rounding or 0.01,
            ) <= 0
        )

    def action_confirm(self):
        """Confirmation groupée (plusieurs commandes sélectionnées) : on
        confirme une par une, pour que chaque commande soit contrôlée avec
        l'encours qui inclut les précédentes. Sinon, trois commandes de 2 000
        pour un client à 4 000 de disponible passeraient toutes ensemble.
        En cas de blocage, l'erreur annule tout le lot."""
        if len(self) > 1:
            for order in self:
                order.action_confirm()
            return True
        return super().action_confirm()

    def _confirmation_error_message(self):
        """Point d'extension natif appelé par action_confirm() pour chaque
        commande : la règle s'applique quelle que soit l'origine de la
        confirmation (bouton, API, import, automatisation)."""
        error = super()._confirmation_error_message()
        if error:
            return error
        reason = self._get_credit_block_reason()
        if reason and not self._credit_approval_is_valid():
            if self.credit_approval_state == "pending":
                advice = "Une dérogation est déjà demandée : attendez la décision du responsable crédit."
            else:
                advice = "Demandez une dérogation au responsable crédit."
            return f"Confirmation impossible : contrôle du crédit client.\n\n{reason}\n\n{advice}"
        return False

    # ------------------------------------------------------------------
    # Sécurité : le commercial peut modifier sa commande, mais jamais
    # s'accorder lui-même une dérogation (même en écrivant via l'API).
    # ------------------------------------------------------------------
    def _check_credit_decision_vals(self, vals):
        decides = vals.get("credit_approval_state") in ("approved", "refused")
        if (decides or vals.get("credit_approved_amount")) and not self.env.su:
            self._check_credit_manager()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_credit_decision_vals(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_credit_decision_vals(vals)
        return super().write(vals)

    # ------------------------------------------------------------------
    # Boutons
    # ------------------------------------------------------------------
    def _open_credit_wizard(self, decision, title):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": "credit.decision.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_order_id": self.id, "default_decision": decision},
        }

    def action_request_credit_override(self):
        return self._open_credit_wizard("request", "Demander une dérogation crédit")

    def action_approve_credit_override(self):
        self._check_credit_manager()
        return self._open_credit_wizard("approved", "Approuver la dérogation")

    def action_refuse_credit_override(self):
        self._check_credit_manager()
        return self._open_credit_wizard("refused", "Refuser la dérogation")

    # ------------------------------------------------------------------
    # Logique du circuit (appelée par le wizard, testable directement)
    # ------------------------------------------------------------------
    def _check_credit_manager(self):
        if not self.env.user.has_group(CREDIT_MANAGER_GROUP):
            raise AccessError("Seul un responsable crédit peut décider d'une dérogation.")

    def _credit_request_override(self, note):
        """Le commercial demande une dérogation, avec une justification."""
        self.ensure_one()
        if not self.credit_can_request:
            raise UserError("Cette commande ne nécessite pas de dérogation, ou une demande est déjà en cours.")
        self.write({"credit_approval_state": "pending", "credit_request_note": note})

        # Une tâche pour chaque responsable crédit, dans sa liste d'activités
        managers = self.env.ref(CREDIT_MANAGER_GROUP).sudo().users.filtered("active")
        for manager in managers:
            self.activity_schedule(
                CREDIT_ACTIVITY_TYPE,
                user_id=manager.id,
                summary=f"Dérogation crédit : {self.partner_id.commercial_partner_id.name}",
                note=Markup("<p><b>Blocage :</b> %s</p><p><b>Justification :</b> %s</p>")
                % (self.credit_block_reason, note),
            )
        self.message_post(
            body=Markup("<p><b>Dérogation crédit demandée</b></p><p>%s</p><p><i>Justification :</i> %s</p>")
            % (self.credit_block_reason, note),
        )

    def _credit_decide(self, decision, reason):
        """Le responsable approuve ou refuse. La décision est figée dans le
        journal d'audit avec la situation du client à cet instant."""
        self.ensure_one()
        self._check_credit_manager()
        if self.credit_approval_state != "pending":
            raise UserError("Aucune demande de dérogation en attente sur cette commande.")

        company = self.company_id or self.env.company
        partner = self.partner_id.commercial_partner_id.with_company(company)
        # sudo() : personne ne peut créer de ligne de journal à la main,
        # elles ne naissent que d'une décision vérifiée ci-dessus.
        self.env["credit.override.log"].sudo().create({
            "order_id": self.id,
            "partner_id": partner.id,
            "salesperson_id": self.user_id.id,
            "user_id": self.env.user.id,
            "decision": decision,
            "request_note": self.credit_request_note,
            "reason": reason,
            "block_reason": self.credit_block_reason,
            "currency_id": self.currency_id.id,
            "order_amount": self.amount_total,
            "company_currency_id": company.currency_id.id,
            "exposure_at_decision": partner.credit_exposure,
            "limit_at_decision": partner.sale_credit_limit,
        })
        self.write({
            "credit_approval_state": decision,
            "credit_approved_amount": self.amount_total if decision == "approved" else 0.0,
        })

        label = "accordée" if decision == "approved" else "refusée"
        self.activity_feedback([CREDIT_ACTIVITY_TYPE], feedback=f"Dérogation {label} : {reason}")
        notify = self.user_id.partner_id.ids if self.user_id else []
        self.message_post(
            body=Markup("<p><b>Dérogation %s</b> pour %s</p><p><i>Motif :</i> %s</p>")
            % (label, formatLang(self.env, self.amount_total, currency_obj=self.currency_id), reason),
            partner_ids=notify,
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
