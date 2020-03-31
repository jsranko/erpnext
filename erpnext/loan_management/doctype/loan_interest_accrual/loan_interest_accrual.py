# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals
import frappe, erpnext
from frappe import _
from frappe.model.document import Document
from frappe.utils import (nowdate, getdate, now_datetime, get_datetime, flt, date_diff, get_last_day, cint,
	get_first_day, get_datetime, add_days)
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.accounts.general_ledger import make_gl_entries

class LoanInterestAccrual(AccountsController):
	def validate(self):
		if not self.loan:
			frappe.throw(_("Loan is mandatory"))

		if not self.posting_date:
			self.posting_date = nowdate()

		if not self.interest_amount:
			frappe.throw(_("Interest Amount is mandatory"))


	def on_submit(self):
		self.make_gl_entries()

	def on_cancel(self):
		self.make_gl_entries(cancel=1)

	def make_gl_entries(self, cancel=0, adv_adj=0):
		gle_map = []

		gle_map.append(
			self.get_gl_dict({
				"account": self.loan_account,
				"party_type": self.applicant_type,
				"party": self.applicant,
				"against": self.interest_income_account,
				"debit": self.interest_amount,
				"debit_in_account_currency": self.interest_amount,
				"against_voucher_type": "Loan",
				"against_voucher": self.loan,
				"remarks": _("Against Loan:") + self.loan,
				"cost_center": erpnext.get_default_cost_center(self.company),
				"posting_date": self.posting_date
			})
		)

		gle_map.append(
			self.get_gl_dict({
				"account": self.interest_income_account,
				"party_type": self.applicant_type,
				"party": self.applicant,
				"against": self.loan_account,
				"credit": self.interest_amount,
				"credit_in_account_currency":  self.interest_amount,
				"against_voucher_type": "Loan",
				"against_voucher": self.loan,
				"remarks": _("Against Loan:") + self.loan,
				"cost_center": erpnext.get_default_cost_center(self.company),
				"posting_date": self.posting_date
			})
		)

		if gle_map:
			make_gl_entries(gle_map, cancel=cancel, adv_adj=adv_adj)


# For Eg: If Loan disbursement date is '01-09-2019' and disbursed amount is 1000000 and
# rate of interest is 13.5 then first loan interest accural will be on '01-10-2019'
# which means interest will be accrued for 30 days which should be equal to 11095.89
def calculate_accrual_amount_for_demand_loans(loan, posting_date, process_loan_interest):
	no_of_days = get_no_of_days_for_interest_accural(loan, posting_date)

	if no_of_days <= 0:
		return

	pending_principal_amount = loan.total_payment - loan.total_interest_payable \
		- loan.total_amount_paid

	interest_per_day = (pending_principal_amount * loan.rate_of_interest) / (days_in_year(get_datetime(posting_date).year) * 100)
	payable_interest = interest_per_day * no_of_days

	make_loan_interest_accrual_entry(loan.name, loan.applicant_type, loan.applicant,loan.interest_income_account,
		loan.loan_account, pending_principal_amount, payable_interest, process_loan_interest = process_loan_interest,
		 posting_date=posting_date)

def make_accrual_interest_entry_for_demand_loans(posting_date, process_loan_interest, open_loans=None, loan_type=None):
	query_filters = {
		"status": "Disbursed",
		"docstatus": 1
	}

	if loan_type:
		query_filters.update({
			"loan_type": loan_type
		})

	if not open_loans:
		open_loans = frappe.get_all("Loan",
			fields=["name", "total_payment", "total_amount_paid", "loan_account", "interest_income_account", "is_term_loan",
				"disbursement_date", "applicant_type", "applicant", "rate_of_interest", "total_interest_payable", "repayment_start_date"],
			filters=query_filters)

	for loan in open_loans:
		calculate_accrual_amount_for_demand_loans(loan, posting_date, process_loan_interest)

def make_accrual_interest_entry_for_term_loans(posting_date=None):
	curr_date = posting_date or add_days(nowdate(), 1)

	term_loans = frappe.db.sql("""SELECT l.name, l.total_payment, l.total_amount_paid, l.loan_account,
		l.interest_income_account, l.is_term_loan, l.disbursement_date, l.applicant_type, l.applicant,
		l.rate_of_interest, l.total_interest_payable, l.repayment_start_date, rs.name as payment_entry,
		rs.payment_date, rs.principal_amount, rs.interest_amount, rs.is_accrued , rs.balance_loan_amount
		FROM `tabLoan` l, `tabRepayment Schedule` rs
		WHERE rs.parent = l.name
		AND l.docstatus=1
		AND l.is_term_loan =1
		AND rs.payment_date <= %s
		AND rs.is_accrued=0
		AND l.status = 'Disbursed'""", (curr_date), as_dict=1)

	accrued_entries = []

	for loan in term_loans:
		accrued_entries.append(loan.payment_entry)
		make_loan_interest_accrual_entry(loan.name, loan.applicant_type, loan.applicant,loan.interest_income_account,
			loan.loan_account, loan.principal_amount + loan.balance_loan_amount, loan.interest_amount,
			payable_principal = loan.principal_amount , posting_date=posting_date)

	if accrued_entries:
		frappe.db.sql("""UPDATE `tabRepayment Schedule`
			SET is_accrued = 1 where name in (%s)""" #nosec
			% ", ".join(['%s']*len(accrued_entries)), tuple(accrued_entries))

def make_loan_interest_accrual_entry(loan, applicant_type, applicant, interest_income_account, loan_account,
	pending_principal_amount, interest_amount, payable_principal=None, process_loan_interest=None, posting_date=None):
		loan_interest_accrual = frappe.new_doc("Loan Interest Accrual")
		loan_interest_accrual.loan = loan
		loan_interest_accrual.applicant_type = applicant_type
		loan_interest_accrual.applicant = applicant
		loan_interest_accrual.interest_income_account = interest_income_account
		loan_interest_accrual.loan_account = loan_account
		loan_interest_accrual.pending_principal_amount = flt(pending_principal_amount, 2)
		loan_interest_accrual.interest_amount = flt(interest_amount, 2)
		loan_interest_accrual.posting_date = posting_date or nowdate()
		loan_interest_accrual.process_loan_interest_accrual = process_loan_interest

		if payable_principal:
			loan_interest_accrual.payable_principal_amount = payable_principal

		loan_interest_accrual.save()
		loan_interest_accrual.submit()


def get_no_of_days_for_interest_accural(loan, posting_date):
	last_interest_accrual_date = get_last_accural_date_in_current_month(loan)

	no_of_days = date_diff(posting_date or nowdate(), last_interest_accrual_date) + 1

	return no_of_days

def get_last_accural_date_in_current_month(loan):
	last_posting_date = frappe.db.sql(""" SELECT MAX(posting_date) from `tabLoan Interest Accrual`
		WHERE loan = %s""", (loan.name))

	if last_posting_date[0][0]:
		return last_posting_date[0][0]
	else:
		return loan.disbursement_date

def days_in_year(year):
	days = 365

	if (year % 4 == 0) and (year % 100 != 0) or (year % 400 == 0):
		days = 366

	return days
