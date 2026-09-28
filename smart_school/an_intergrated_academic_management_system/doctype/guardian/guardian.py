import frappe
from frappe.model.document import Document

from smart_school.users import assert_user_not_linked, ensure_role, ensure_user_with_role


class Guardian(Document):
	def validate(self):
		if self.email:
			self.email = self.email.strip()
			other = frappe.db.get_value("Guardian", {"email": self.email, "name": ["!=", self.name]}, "name")
			if other:
				frappe.throw(f"Guardian {other} already uses the email {self.email}")

		if self.user:
			assert_user_not_linked("Guardian", self.user, self.name)
		self.record_sms_consent()

	def record_sms_consent(self):
		"""Who changed the SMS consent, how and when. smart_school.sms.set_consent passes the source (Admission,
		Portal, Staff for paper) and date; a tick on this form counts as Staff, today."""
		consent = self.flags.sms_consent
		if not (consent or self.has_value_changed("sms_opt_in")) or (self.is_new() and not self.sms_opt_in):
			return
		consent = consent or frappe._dict(source="Staff", date=frappe.utils.today())
		self.sms_opt_in_source = consent.source
		self.sms_opt_in_date = consent.date
		self.sms_opt_in_by = frappe.session.user

	def on_update(self):
		if self.email and not self.user:
			self.create_portal_user()
		elif self.user:
			ensure_role(self.user, "Parent")

	def create_portal_user(self):
		user_name = ensure_user_with_role(self.email, self.full_name, "Parent")
		assert_user_not_linked("Guardian", user_name, self.name)
		self.db_set("user", user_name)
