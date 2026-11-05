from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCreditControl(TransactionCase):
    """Règles métier du contrôle de crédit client."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env.user)
        ICP = cls.env["ir.config_parameter"].sudo()
        ICP.set_param("sale_credit_control.enabled", "True")
        ICP.set_param("sale_credit_control.overdue_tolerance_days", "30")
        ICP.set_param("sale_credit_control.tolerance_pct", "0.0")

        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.salesman = Users.create({
            "name": "Commercial Test",
            "login": "test_credit_salesman",
            "email": "salesman@example.com",
            "groups_id": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("sales_team.group_sale_salesman_all_leads").id,
                cls.env.ref("base.group_partner_manager").id,
            ])],
        })
        cls.manager = Users.create({
            "name": "Responsable Crédit Test",
            "login": "test_credit_manager",
            "email": "manager@example.com",
            "groups_id": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("sale_credit_control.group_credit_manager").id,
            ])],
        })
        cls.product = cls.env["product.product"].create({
            "name": "Produit test crédit",
            "list_price": 1000.0,
            "taxes_id": [(6, 0, [])],
        })
        cls.customer = cls.env["res.partner"].create({
            "name": "Client Test SA",
            "is_company": True,
            "sale_credit_limit": 5000.0,
        })
        cls.contact = cls.env["res.partner"].create({"name": "Contact Test", "parent_id": cls.customer.id})

    # ------------------------------------------------------------------
    # Outils
    # ------------------------------------------------------------------
    def _invoice(self, amount, partner=None, days_ago=0, due_in=30, move_type="out_invoice"):
        move = self.env["account.move"].create({
            "move_type": move_type,
            "partner_id": (partner or self.customer).id,
            "invoice_date": self.today - timedelta(days=days_ago),
            "invoice_date_due": self.today + timedelta(days=due_in),
            "invoice_payment_term_id": False,
            "invoice_line_ids": [(0, 0, {
                "product_id": self.product.id,
                "quantity": 1,
                "price_unit": amount,
                "tax_ids": [(6, 0, [])],
            })],
        })
        move.action_post()
        return move

    def _order(self, amount, partner=None, user=None):
        return self.env["sale.order"].with_user(user or self.salesman).create({
            "partner_id": (partner or self.customer).id,
            "order_line": [(0, 0, {
                "product_id": self.product.id,
                "product_uom_qty": 1,
                "price_unit": amount,
                "tax_id": [(6, 0, [])],
            })],
        })

    def _situation(self, partner=None):
        partner = partner or self.customer
        partner.invalidate_recordset()
        return partner

    # ------------------------------------------------------------------
    # Calcul de l'encours
    # ------------------------------------------------------------------
    def test_exposure_invoices_payments_and_orders(self):
        invoice = self._invoice(1000, partner=self.contact)  # facturé via le contact
        self.assertEqual(self._situation().credit_exposure, 1000)

        self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids
        ).create({"amount": 400})._create_payments()
        self.assertEqual(self._situation().credit_exposure, 600, "Le paiement partiel réduit l'encours")

        self._order(3000, user=self.manager).action_confirm()
        customer = self._situation()
        self.assertEqual(customer.credit_uninvoiced_orders, 3000, "Commande confirmée non facturée")
        self.assertEqual(customer.credit_exposure, 3600)
        self.assertEqual(customer.credit_available, 1400)

    def test_contact_inherits_company_policy(self):
        self.assertEqual(self.contact.sale_credit_limit, 5000)
        self._invoice(1000)
        self.assertEqual(self._situation(self.contact).credit_exposure, 1000)

    def test_unreconciled_refund_offsets_overdue(self):
        self._invoice(2000, days_ago=60, due_in=-60)
        self._invoice(2000, move_type="out_refund")
        customer = self._situation()
        self.assertEqual(customer.credit_exposure, 0)
        self.assertEqual(customer.credit_overdue_count, 0, "Un avoir non lettré compense le retard")

    # ------------------------------------------------------------------
    # Règles de blocage
    # ------------------------------------------------------------------
    def test_order_under_limit_is_confirmed(self):
        self._invoice(2000)
        order = self._order(2000)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_order_over_limit_is_blocked(self):
        self._invoice(4500)
        order = self._order(2000)
        self.assertTrue(order.credit_block_reason)
        with self.assertRaises(UserError):
            order.action_confirm()
        self.assertEqual(order.state, "draft")

    def test_overdue_invoice_blocks_even_with_high_limit(self):
        self.customer.sale_credit_limit = 100000
        self._invoice(3200, days_ago=60, due_in=-60)
        with self.assertRaises(UserError):
            self._order(1000).action_confirm()

    def test_overdue_within_tolerance_is_accepted(self):
        self._invoice(1000, days_ago=10, due_in=-10)
        order = self._order(1000)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_blocked_and_exempt_policies(self):
        self.customer.credit_policy = "blocked"
        with self.assertRaises(UserError):
            self._order(10).action_confirm()

        self.customer.credit_policy = "exempt"
        self._invoice(50000)
        order = self._order(10000)
        order.action_confirm()
        self.assertEqual(order.state, "sale", "Un client exempté n'est jamais bloqué")

    def test_batch_confirmation_counts_previous_orders(self):
        orders = self._order(2000) | self._order(2000) | self._order(2000)  # 6000 > 5000
        with self.assertRaises(UserError):
            orders.action_confirm()

    def test_disabled_control_blocks_nothing(self):
        self.env["ir.config_parameter"].sudo().set_param("sale_credit_control.enabled", "False")
        self._invoice(4500)
        order = self._order(2000)
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    # ------------------------------------------------------------------
    # Circuit d'approbation
    # ------------------------------------------------------------------
    def _request_and_decide(self, order, decision, reason="Motif de test"):
        order.with_user(self.salesman)._credit_request_override("Justification de test")
        order.with_user(self.manager)._credit_decide(decision, reason)

    def test_request_creates_activity_for_manager(self):
        self._invoice(4500)
        order = self._order(2000)
        self.assertTrue(order.credit_can_request)
        order.with_user(self.salesman)._credit_request_override("Paiement promis vendredi")
        self.assertEqual(order.credit_approval_state, "pending")
        activity_type = self.env.ref("sale_credit_control.mail_activity_type_credit_override")
        activities = order.activity_ids.filtered(lambda a: a.activity_type_id == activity_type)
        self.assertIn(self.manager, activities.user_id)

    def test_approved_order_can_be_confirmed_and_is_logged(self):
        self._invoice(4500)
        order = self._order(2000)
        self._request_and_decide(order, "approved")
        self.assertTrue(order.credit_approval_valid)
        order.with_user(self.salesman).action_confirm()
        self.assertEqual(order.state, "sale")

        log = order.credit_override_ids
        self.assertEqual(len(log), 1)
        self.assertEqual(log.decision, "approved")
        self.assertEqual(log.user_id, self.manager)
        self.assertEqual(log.exposure_at_decision, 4500)
        self.assertEqual(log.limit_at_decision, 5000)
        self.assertFalse(order.activity_ids, "L'activité du responsable est clôturée")

    def test_approval_is_void_when_order_increases(self):
        self._invoice(4500)
        order = self._order(2000)
        self._request_and_decide(order, "approved")
        order.with_user(self.salesman).order_line.price_unit = 5000
        self.assertFalse(order.credit_approval_valid)
        self.assertEqual(order.credit_approval_badge, "exceeded", "Le badge signale la dérogation dépassée")
        self.assertTrue(order.credit_can_request)
        with self.assertRaises(UserError):
            order.with_user(self.salesman).action_confirm()

    def test_refused_order_stays_blocked(self):
        self._invoice(4500)
        order = self._order(2000)
        self._request_and_decide(order, "refused")
        self.assertEqual(order.credit_approval_state, "refused")
        with self.assertRaises(UserError):
            order.with_user(self.salesman).action_confirm()

    def test_copy_does_not_keep_approval(self):
        self._invoice(4500)
        order = self._order(2000)
        self._request_and_decide(order, "approved")
        copy = order.copy()
        self.assertEqual(copy.credit_approval_state, "none")
        self.assertFalse(copy.credit_override_ids)

    # ------------------------------------------------------------------
    # Sécurité et audit
    # ------------------------------------------------------------------
    def test_salesman_cannot_approve(self):
        self._invoice(4500)
        order = self._order(2000)
        order.with_user(self.salesman)._credit_request_override("Justification")
        with self.assertRaises(AccessError):
            order.with_user(self.salesman)._credit_decide("approved", "Je m'approuve")
        with self.assertRaises(AccessError):
            order.with_user(self.salesman).write({
                "credit_approval_state": "approved", "credit_approved_amount": 1e9,
            })

    def test_salesman_cannot_change_credit_policy(self):
        customer = self.customer.with_user(self.salesman)
        with self.assertRaises(AccessError):
            customer.write({"sale_credit_limit": 999999})
        with self.assertRaises(AccessError):
            customer.write({"credit_policy": "exempt"})
        customer.write({"phone": "+33 1 00 00 00 00"})  # les autres champs restent modifiables
        new_contact = self.env["res.partner"].with_user(self.salesman).create({
            "name": "Nouveau contact", "parent_id": self.customer.id,
        })
        self.assertEqual(new_contact.sale_credit_limit, 5000)

    def test_manager_can_change_credit_policy(self):
        self.customer.with_user(self.manager).write({"sale_credit_limit": 8000})
        self.assertEqual(self.contact.sale_credit_limit, 8000)

    def test_override_log_is_immutable(self):
        self._invoice(4500)
        order = self._order(2000)
        self._request_and_decide(order, "approved")
        log = order.credit_override_ids
        with self.assertRaises(UserError):
            log.write({"reason": "falsifié"})
        with self.assertRaises(UserError):
            log.unlink()
        with self.assertRaises(AccessError):
            self.env["credit.override.log"].with_user(self.manager).create({
                "order_id": order.id,
                "partner_id": self.customer.id,
                "user_id": self.manager.id,
                "decision": "approved",
                "reason": "création manuelle",
            })
