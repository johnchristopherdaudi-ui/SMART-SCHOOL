"""The public admission form (/apply-online) is in Swahili: labels, descriptions, messages and the success page;
the stored values (fieldnames, Male / Female, Class names) stay as they are."""

import json
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from smart_school.tests.factory import SchoolTestCase, as_user, render

WEB_FORM = "student-admission-form"
ENGLISH = ("Full Name", "Date of Birth", "Parent Name", "Phone Number", "Class Applying", ">Save<", "Student Admission Form")


class TestAdmissionForm(SchoolTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(setattr, frappe.flags, "in_web_form", False)

	def apply(self, **values):
		"""What the form sends, as a guest (no request, so no rate limit)."""
		data = {
			"full_name": "_Test Mwombaji Juma",
			"gender": "Female",
			"date_of_birth": "2012-05-04",
			"class_applying": "_Test FORM 1",
			"parent_name": "_Test Mzazi Juma",
			"phone_number": "0754 321 000",
			"email": "",
			"sms_opt_in": 1,
			**values,
		}
		from frappe.website.doctype.web_form.web_form import accept

		with as_user("Guest"), patch.object(frappe.local, "request", None, create=True):
			return accept(WEB_FORM, json.dumps(data))

	def test_the_page_is_in_swahili(self):
		with as_user("Guest"):
			status, body, _ = render("apply-online/new")
		self.assertEqual(status, 200)
		for text in (
			"Fomu ya Maombi ya Kujiunga",
			"Jina kamili la mwanafunzi",
			"Tarehe ya kuzaliwa",
			"Kidato anachoombea",
			"Jina kamili la mzazi au mlezi",
			"Namba ya simu ya mkononi",
			"Mfano 0754 123 456",
			"Tuma Maombi",
			"Maombi yamepokelewa",
			"Asante! Maombi yako yamepokelewa",
			"Tafadhali rekebisha",  # the client script: its messages, and Frappe's own words on this page
			"Tuma maombi mengine",
			"Ingia",
			"Mwanzo",
		):
			self.assertIn(text, body)
		for text in ENGLISH:
			self.assertNotIn(text, body)

		form = json.loads(body.split("frappe.web_form_doc = ")[1].split(";\n")[0])
		options = {f["fieldname"]: f.get("options") for f in form["web_form_fields"]}
		self.assertEqual(options["gender"][1:], [{"label": "Mvulana", "value": "Male"}, {"label": "Msichana", "value": "Female"}])
		classes = {o["value"]: o["label"] for o in options["class_applying"] if o["value"]}
		self.assertEqual(classes["_Test FORM 1"], "Kidato cha Kwanza")  # the stored value is the class
		self.assertEqual(set(classes), set(frappe.get_all("Class", pluck="name")))
		fieldtypes = {f["fieldname"]: f["fieldtype"] for f in form["web_form_fields"]}
		self.assertEqual(fieldtypes["phone_number"], "Data")  # no English country picker

	def test_an_application_is_saved_with_the_values_stored_as_before(self):
		self.apply(phone_number="0754 321 000")
		doc = frappe.get_last_doc("Student Admission", filters={"full_name": "_Test Mwombaji Juma"})
		self.assertEqual(
			(doc.gender, doc.class_applying, doc.phone_number, doc.status, doc.sms_opt_in),
			("Female", "_Test FORM 1", "+255-754321000", "Pending", 1),
		)

	def test_mistakes_are_explained_in_swahili(self):
		cases = [
			({"full_name": ""}, "Jaza: Jina kamili la mwanafunzi."),
			({"phone_number": ""}, "Jaza: Namba ya simu ya mkononi."),
			({"phone_number": "0754 32100"}, "Namba ya simu si sahihi. Andika namba ya simu ya mkononi ya Tanzania"),
			({"phone_number": "+254 712 345 678"}, "Namba ya simu si sahihi"),  # not Tanzanian
			({"date_of_birth": add_days(today(), 1)}, "Tarehe ya kuzaliwa haiwezi kuwa ya baadaye."),
			({"email": "mzazi@"}, "Barua pepe si sahihi"),
			({"parent_name": "M" * 141}, "Jina la mzazi au mlezi ni refu mno"),
		]
		for values, message in cases:
			frappe.clear_messages()
			with self.assertRaises(frappe.ValidationError, msg=message):
				self.apply(**values)
			shown = json.loads(frappe.local.message_log[-1]) if isinstance(frappe.local.message_log[-1], str) else frappe.local.message_log[-1]
			self.assertIn(message, shown["message"])
			self.assertEqual(shown.get("title"), "Tafadhali rekebisha")

	def test_the_desk_form_keeps_its_own_rules(self):
		"""Staff entering an admission at the desk are not held to the public form's rules (e.g. a foreign number)."""
		doc = frappe.get_doc(
			{
				"doctype": "Student Admission",
				"full_name": "_Test Desk Applicant",
				"date_of_birth": "2012-01-01",
				"parent_name": "_Test Desk Parent",
				"phone_number": "+254-712345678",
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.phone_number, "+254-712345678")
