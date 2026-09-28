import re

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, today, validate_email_address

APPROVER_ROLES = ("Headmaster", "System Manager")


# What a parent must fill in on the public form (/apply-online), with the Swahili labels they see
REQUIRED = {
	"full_name": "Jina kamili la mwanafunzi",
	"date_of_birth": "Tarehe ya kuzaliwa",
	"parent_name": "Jina kamili la mzazi au mlezi",
	"phone_number": "Namba ya simu ya mkononi",
}
MAX_LENGTH = {"full_name": "Jina la mwanafunzi", "parent_name": "Jina la mzazi au mlezi", "email": "Barua pepe"}


class StudentAdmission(Document):
	def validate(self):
		if frappe.flags.in_web_form and self.is_new():
			self.validate_application()
		self.validate_status_change()

	def validate_application(self):
		"""The public form is for parents: their mistakes are explained in Swahili, before Frappe's own (English)
		checks run. The phone number is kept as +255-7XXXXXXXX, the format Frappe's Phone field accepts."""
		from smart_school.portal_utils import normalize_tz_mobile

		problems = [f"Jaza: {label}." for fieldname, label in REQUIRED.items() if not str(self.get(fieldname) or "").strip()]
		problems += [
			f"{label} ni refu mno: herufi 140 ndizo nyingi zaidi."
			for fieldname, label in MAX_LENGTH.items()
			if len(str(self.get(fieldname) or "")) > 140
		]
		if self.phone_number:
			phone = normalize_tz_mobile(self.phone_number)
			if phone and is_valid_phone(f"+{phone}"):
				self.phone_number = f"+255-{phone[3:]}"
			else:
				problems.append(
					"Namba ya simu si sahihi. Andika namba ya simu ya mkononi ya Tanzania, mfano 0754 123 456."
				)
		if self.date_of_birth and getdate(self.date_of_birth) > getdate(today()):
			problems.append("Tarehe ya kuzaliwa haiwezi kuwa ya baadaye.")
		if self.email:
			self.email = self.email.strip()
			if not validate_email_address(self.email):
				problems.append("Barua pepe si sahihi, mfano jina@mfano.com.")
		if problems:
			frappe.throw("<br>".join(problems), title="Tafadhali rekebisha")

	def validate_status_change(self):
		# Status is also settable through the API, so enforce approvers here, not only via doctype permissions
		if self.status == "Pending" or not self.has_value_changed("status"):
			return

		if not set(APPROVER_ROLES) & set(frappe.get_roles()):
			frappe.throw(
				"Only a Headmaster or System Manager can approve or reject an admission",
				frappe.PermissionError,
			)

		if self.status == "Approved" and not (self.birth_certificate or self.birth_certificate_verified):
			frappe.throw("Attach the birth certificate or tick Birth Certificate Verified before approving")

	def on_update(self):
		if self.status == "Approved" and not self.student:
			student = self.create_student()
			self.db_set("student", student)
			guardian = self.link_guardian(student)
			frappe.msgprint(f"Student record created: {student} (Guardian {guardian})")

	def create_student(self):
		student = frappe.new_doc("Student")
		student.full_name = self.full_name
		student.date_of_birth = self.date_of_birth
		student.gender = self.gender
		student.status = "Active"
		student.admission_date = frappe.utils.today()
		student.current_class = self.class_applying
		student.admission_reference = self.name
		student.insert(ignore_permissions=True)
		return student.name

	def link_guardian(self, student):
		guardian_name = self.find_guardian()
		if guardian_name:
			guardian = frappe.get_doc("Guardian", guardian_name)
		else:
			guardian = frappe.new_doc("Guardian")
			guardian.full_name = self.parent_name
			guardian.phone = self.phone_number
			guardian.email = self.email

		guardian.append("students", {"student": student, "relationship": "Guardian"})
		if self.sms_opt_in:  # an unticked box is not a refusal: an existing guardian's choice stays
			guardian.sms_opt_in = 1
			guardian.flags.sms_consent = frappe._dict(source="Admission", date=getdate(self.creation))
		guardian.save(ignore_permissions=True)
		return guardian.name

	def find_guardian(self):
		if self.email:
			guardian = frappe.db.get_value("Guardian", {"email": self.email.strip()}, "name")
			if guardian:
				return guardian

		phone = normalize_phone(self.phone_number)
		if not phone:
			return None

		for guardian in frappe.get_all(
			"Guardian", filters={"phone": ["is", "set"]}, fields=["name", "phone"]
		):
			if normalize_phone(guardian.phone) == phone:
				return guardian.name


def is_valid_phone(phone):
	"""The same check as Frappe's Phone field, so an accepted number never fails there in English."""
	from phonenumbers import NumberParseException, is_valid_number, parse

	try:
		return is_valid_number(parse(phone))
	except NumberParseException:
		return False


def normalize_phone(phone):
	# Compare the last 9 digits so +255-7XX..., 2557XX... and 07XX... match
	digits = re.sub(r"\D", "", phone or "")
	return digits[-9:] if len(digits) >= 9 else None
