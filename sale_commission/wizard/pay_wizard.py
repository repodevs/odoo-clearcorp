# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Original Module by SIESA (<http://www.siesacr.com>)
#    Refactored by CLEARCORP S.A. (<http://clearcorp.co.cr>)
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    license, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
##############################################################################

from openerp.osv import osv, fields
from dateutil.relativedelta import relativedelta
from datetime import datetime

class PayWizard(osv.TransientModel):

    _name = 'sale.commission.pay.wizard'

    def _get_interval_period(self, cr, uid, end_period, start_period=None, context=None):
        period_obj = self.pool.get('account.period')
        period_list = []
        # Both start and end period are available
        if start_period and end_period:
            period_list =  period_obj.search(cr, uid, [('date_start','>=',start_period.date_start),('date_stop','<=',end_period.date_start),('special','=',False),])
        # All periods going back until reaching openning period
        elif not start_period and end_period:
            fiscal_year = end_period.fiscalyear_id.id
            period_list = period_obj.search(cr, uid, [('fiscalyear_id', '=', fiscal_year),('date_stop','<=',end_period.date_stop),('special','=',False)])
        return period_list

    def _invoices_without_commission(self, cr, uid, wizard, member, rule, period_ids,context=None):
        invoice_obj =self.pool.get('account.invoice')
        rule_line_obj = self.pool.get('sale.commission.rule.line')
        commission_obj = self.pool.get('sale.commission.commission')
        try:
            # Get the invoices of the user without commission
            cr.execute("""SELECT INV.id
FROM account_invoice AS INV
WHERE
  INV.id NOT IN
    (SELECT COM.invoice_id
    FROM sale_commission_commission AS COM) AND
  INV.type = 'out_invoice' AND
  INV.user_id = %s AND
  INV.period_id IN %s""", [member.id, tuple(period_ids)])
            invoices_no_commission_ids = [item[0] for item in cr.fetchall()]
            invoices_no_commission = invoice_obj.browse(cr, uid,
                invoices_no_commission_ids, context=context)
            # Get and order the rule_lines by sequence
            rule_line_ids = rule_line_obj.search(cr, uid, [('commission_rule_id','=',rule.id)],
                order='sequence asc', context=context)
            rule_lines = rule_line_obj.browse(cr, uid, rule_line_ids, context=context)
            sales_dict = {}
            for invoice in invoices_no_commission:
                if not invoice.period_id.id in sales_dict:
                    # Get the invoices of the user
                    period_invoices_ids = invoice_obj.search(cr, uid, [('user_id','=',member.id),
                        ('period_id','=',invoice.period_id.id)], context=context)
                    #Get the total sales for the period
                    cr.execute("""SELECT SUM(INV.amount_total) AS amount_total
FROM account_invoice AS INV
WHERE
  INV.id IN %s;""",[tuple(period_invoices_ids)])
                    total_sales = cr.fetchall()[0][0]
                    sales_dict[invoice.period_id.id] = total_sales
                else:
                    total_sales = sales_dict[invoice.period_id.id]
                total_credit = 0.0
                for payment in invoice.payment_ids:
                    if payment.journal_id and payment.journal_id.pay_commission:
                        if not payment.commission:
                            total_credit += payment.credit
                            payment.write({'commission': True}, context=context)
                if total_credit > 0.0:
                    for rule_line in rule_lines:
                        result = True
                        if rule_line.partner_category_id:
                            if not rule_line.partner_category_id in invoice.partner_id.category_id:
                                result = result and False
                        if rule_line.pricelist_id:
                            if invoice.pricelist_id:
                                if not invoice.pricelist_id.id == rule_line.pricelist_id.id:
                                    result = result and False
                            else:
                                result = result and False
                        if rule_line.payment_term_id:
                            if invoice.payment_term:
                                if not invoice.payment_term.id == rule_line.payment_term_id:
                                    result = result and False
                            else:
                                result = result and False
                        if rule_line.max_discount > 0.0:
                            if invoice.invoice_discount > rule_line.max_discount:
                                result = result and False
                        if rule_line.monthly_sales > 0.0:
                            if total_sales < rule_line.monthly_sales:
                                result = result and False
                        if result:
                            if rule_line.commission_percentage and total_credit:
                                amount = total_credit * rule_line.commission_percentage / 100
                            else:
                                amount = 0.0
                            exp_days = relativedelta(days=rule.post_expiration_days)
                            if invoice.date_due:
                                inv_date = datetime.strptime(invoice.date_due, '%Y-%m-%d')
                                if datetime.today() > inv_date + exp_days:
                                    state = 'expired'
                                else:
                                    state = 'new'
                            else:
                                state = 'expired'
                            values = {
                                'invoice_id': invoice.id,
                                'state': state,
                                'user_id': member.id,
                                'amount': amount,
                                'invoice_commission_percentage': rule_line.commission_percentage,
                            }
                            commission_obj.create(cr, uid, values, context=context)
        except:
            raise osv.except_osv('Error','asdasd')

    def _invoices_with_commission(self, cr, uid, wizard, member, rule, period_ids, context=None):
        invoice_obj =self.pool.get('account.invoice')
        rule_line_obj = self.pool.get('sale.commission.rule.line')
        commission_obj = self.pool.get('sale.commission.commission')
        try:
            # Get the invoices of the user without commission
            cr.execute("""SELECT INV.id
FROM account_invoice AS INV
WHERE
  INV.id IN
    (SELECT COM.invoice_id
    FROM sale_commission_commission AS COM
    WHERE COM.state = 'new') AND
  INV.type = 'out_invoice' AND
  INV.user_id = %s AND
  INV.period_id IN %s""", [member.id, tuple(period_ids)])
            invoices_commission_ids = [item[0] for item in cr.fetchall()]
            invoices_commission = invoice_obj.browse(cr, uid,
                invoices_commission_ids, context=context)
            # Get and order the rule_lines by sequence
            rule_line_ids = rule_line_obj.search(cr, uid, [('commission_rule_id','=',rule.id)],
                order='sequence asc', context=context)
            rule_lines = rule_line_obj.browse(cr, uid, rule_line_ids, context=context)
            sales_dict = {}
            for invoice in invoices_commission:
                if not invoice.period_id.id in sales_dict:
                    # Get the invoices of the user
                    period_invoices_ids = invoice_obj.search(cr, uid, [('user_id','=',member.id),
                        ('period_id','=',invoice.period_id.id)], context=context)
                    #Get the total sales for the period
                    cr.execute("""SELECT SUM(INV.amount_total) AS amount_total
FROM account_invoice AS INV
WHERE
  INV.id IN %s;""",[tuple(period_invoices_ids)])
                    total_sales = cr.fetchall()[0][0]
                    sales_dict[invoice.period_id.id] = total_sales
                else:
                    total_sales = sales_dict[invoice.period_id.id]
                total_credit = 0.0
                for payment in invoice.payment_ids:
                    if payment.journal_id and payment.journal_id.pay_commission:
                        if not payment.commission:
                            total_credit += payment.credit
                            payment.write({'commission': True}, context=context)
                if total_credit > 0.0:
                    for rule_line in rule_lines:
                        result = True
                        if rule_line.partner_category_id:
                            if not rule_line.partner_category_id in invoice.partner_id.category_id:
                                result = result and False
                        if rule_line.pricelist_id:
                            if invoice.pricelist_id:
                                if not invoice.pricelist_id.id == rule_line.pricelist_id.id:
                                    result = result and False
                            else:
                                result = result and False
                        if rule_line.payment_term_id:
                            if invoice.payment_term:
                                if not invoice.payment_term.id == rule_line.payment_term_id:
                                    result = result and False
                            else:
                                result = result and False
                        if rule_line.max_discount > 0.0:
                            if invoice.invoice_discount > rule_line.max_discount:
                                result = result and False
                        if rule_line.monthly_sales > 0.0:
                            if total_sales < rule_line.monthly_sales:
                                result = result and False
                        if result:
                            if rule_line.commission_percentage and total_credit:
                                amount = total_credit * rule_line.commission_percentage / 100
                            else:
                                amount = 0.0
                            exp_days = relativedelta(days=rule.post_expiration_days)
                            if invoice.date_due:
                                inv_date = datetime.strptime(invoice.date_due, '%Y-%m-%d')
                                if datetime.today() > inv_date + exp_days:
                                    state = 'expired'
                                else:
                                    state = 'new'
                            else:
                                state = 'expired'
                            values = {
                                'invoice_id': invoice.id,
                                'state': state,
                                'user_id': member.id,
                                'amount': amount,
                                'invoice_commission_percentage': rule_line.commission_percentage,
                            }
                            commission_obj.create(cr, uid, values, context=context)
        except:
            raise osv.except_osv('Error', 'asdasd')
    
    def do_payment(self, cr, uid, ids, context=None):
        assert isinstance(ids,list)
        wizard = self.browse(cr, uid, ids[0], context=context)
        # Get the periods interval
        period_ids = self._get_interval_period(cr, uid, wizard.period_id, context=context)
        # Get the journals that pay commissions
        journal_obj = self.pool.get('account.journal')
        journal_ids = journal_obj.search(cr, uid, [('pay_commission','=',True)], context=context)
        journals = journal_obj.browse(cr, uid, journal_ids, context=context)
        # Get all rule if there are not selected rules
        if not wizard.rule_ids:
            rule_obj = self.pool.get('sale.commission.rule')
            rule_ids = rule_obj.search(cr, uid, [], context=context)
            rules = rule_obj.browse(cr, uid, rule_ids, context=context)
        # Use the selected rules
        else:
            rules = wizard.rule_ids
        invoice_obj =self.pool.get('account.invoice')
        for rule in rules:
            for member in rule.member_ids:
                # Invoices WITHOUT commission
                self._invoices_without_commission(cr, uid, wizard, member,
                    rule, period_ids, context=context)
                # Invoices WITH commission
                self._invoices_with_commission(cr, uid, wizard, member,
                    rule, period_ids, context=context)
        return True

    _columns = {
        'period_id': fields.many2one('account.period', string='Period', required=True),
        'rule_ids': fields.many2many('sale.commission.rule', rel='sale_commission_wizard_rule_rel', string='Rules'),
    }