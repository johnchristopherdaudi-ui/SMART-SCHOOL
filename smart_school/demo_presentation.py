"""The demo's presentation set-up, and putting it back after a rehearsal (demo sites only).

prepare():
- a Form 2 exam that is not published, with one open marks alert (Many Zero Marks), so "Publish Results" shows the
  alert dialog; the exam's other open alerts are marked reviewed (as a Headmaster would have);
- a marks CSV for teacher03 (History) for a Form 2 exam that has no History marks yet, in the home folder, with one
  row whose mark is above the exam's maximum (to show the per-row error);
- parent0128 agrees to SMS.
It records the state in private/demo_presentation.json.

reset() puts that state back without reinstalling: it undoes what a rehearsal does to the two exams (publishing,
the History marks imported, the alerts, SMS and timeline comments written since prepare) and parent0128's consent.
It never touches anything else, and never anything made before prepare. dry_run=1 lists what it would do.

    bench --site demo.localhost execute smart_school.demo_presentation.prepare
    bench --site demo.localhost execute smart_school.demo_presentation.reset
"""

import csv
import json
import os
import random

import frappe
from frappe.utils import get_datetime, now_datetime

from smart_school.demo_data import assert_demo_name

FORM = "FORM 2"
TEACHER_USER = "teacher03@demo.smartschool.test"
SUBJECT = "HISTORY"
PARENT_USER = "parent0128@demo.smartschool.test"
KEEP_OPEN = "Many Zero Marks"
TOO_HIGH = 120  # above the exam's maximum of 100: the import reports this row and imports the others
REVIEW_NOTE = "Imekaguliwa kabla ya presentation (demo)."


def state_path():
	return frappe.get_site_path("private", "demo_presentation.json")


def csv_path(exam):
	name = f"marks_{exam['class'].replace(' ', '')}_{exam.exam_name}_{exam.term.replace(' ', '')}_{SUBJECT}_teacher03.csv"
	return os.path.join(os.path.expanduser("~"), name)


def prepare():
	assert_demo_name()
	alert_exam = frappe.get_all(
		"Exam",
		filters={"class": FORM, "results_published": 0, "first_published_on": ["is", "set"]},
		fields=["name"],
		order_by="start_date desc",
		limit=1,
	)
	if not alert_exam:
		frappe.throw(f"No unpublished {FORM} exam with results to use")
	alert_exam = alert_exam[0].name
	alerts = frappe.get_all(
		"Marks Alert", filters={"exam": alert_exam, "status": "Open"}, fields=["name", "alert_type"]
	)
	keep = [a for a in alerts if a.alert_type == KEEP_OPEN]
	if not keep:
		frappe.throw(f"{alert_exam} has no open {KEEP_OPEN} alert")
	for a in alerts:
		if a.alert_type != KEEP_OPEN:
			doc = frappe.get_doc("Marks Alert", a.name)
			doc.status = "Reviewed-OK"
			doc.review_note = REVIEW_NOTE
			doc.save(ignore_permissions=True)

	import_exam = frappe.get_all(
		"Exam",
		filters={"class": FORM, "results_published": 0, "name": ["!=", alert_exam]},
		fields=["name", "exam_name", "term", "class", "max_marks"],
		order_by="start_date desc",
	)
	import_exam = next(
		(e for e in import_exam if not frappe.db.exists("Exam Result", {"exam": e.name, "subject": SUBJECT, "docstatus": 1})),
		None,
	)
	if not import_exam:
		frappe.throw(f"No {FORM} exam without {SUBJECT} marks")
	path = write_csv(import_exam, alert_exam)

	guardian = frappe.db.get_value("Guardian", {"user": PARENT_USER}, "name")
	frappe.db.set_value("Guardian", guardian, "sms_opt_in", 1)

	state = {
		"prepared_at": str(now_datetime()),
		"alert_exam": alert_exam,
		"alerts": {
			name: frappe.db.get_value("Marks Alert", name, ["status", "review_note", "reviewer", "reviewed_on"], as_dict=True)
			for name in frappe.get_all("Marks Alert", filters={"exam": alert_exam}, pluck="name")
		},
		"import_exam": import_exam.name,
		"subject": SUBJECT,
		"teacher": TEACHER_USER,
		"csv": path,
		"guardian": guardian,
	}
	with open(state_path(), "w") as f:
		json.dump(state, f, indent=1, default=str)
	frappe.db.commit()
	print(f"Publish dialog: {alert_exam} (open alert: {KEEP_OPEN})")
	print(f"CSV for {TEACHER_USER}: {path} (exam {import_exam.name}, one row at {TOO_HIGH})")
	print(f"SMS consent: {PARENT_USER} ({guardian}) agrees")
	return state


def write_csv(exam, earlier_exam):
	"""Wide format (as "Upload Wide CSV" in Exam Result): Admission Number, then the subject. Marks near each student's
	History mark in the earlier exam; the fourth row is above the maximum on purpose."""
	rng = random.Random(f"presentation-{exam.name}")
	students = frappe.get_all(
		"Student", filters={"current_class": exam["class"], "status": "Active"}, pluck="name", order_by="name asc"
	)
	before = dict(
		frappe.get_all(
			"Exam Result",
			filters={"exam": earlier_exam, "subject": SUBJECT, "docstatus": 1},
			fields=["student", "marks"],
			as_list=True,
		)
	)
	path = csv_path(exam)
	with open(path, "w", newline="") as f:
		writer = csv.writer(f)
		writer.writerow(["Admission Number", SUBJECT])
		for i, student in enumerate(students):
			marks = TOO_HIGH if i == 3 else max(0, min(int(exam.max_marks), round(float(before.get(student, 50)) + rng.randint(-8, 8))))
			writer.writerow([student, marks])
	return path


def reset(dry_run=0):
	"""Put the presentation state back (see the module docstring). Prints what it does."""
	assert_demo_name()
	if not os.path.exists(state_path()):
		frappe.throw("Run smart_school.demo_presentation.prepare first")
	with open(state_path()) as f:
		state = json.load(f)
	since = get_datetime(state["prepared_at"])
	exams = [state["alert_exam"], state["import_exam"]]
	done = []

	def act(message, fn):
		done.append(message)
		if not int(dry_run):
			fn()

	if frappe.db.get_value("Exam", state["alert_exam"], "results_published"):
		act(
			f"unpublish {state['alert_exam']}",
			lambda: frappe.db.set_value("Exam", state["alert_exam"], {"results_published": 0, "published_on": None}),
		)
	imported = frappe.get_all(
		"Exam Result",
		filters={"exam": state["import_exam"], "subject": state["subject"], "creation": [">", since]},
		fields=["name", "docstatus"],
	)
	if imported:
		act(
			f"remove the {len(imported)} {state['subject']} marks imported into {state['import_exam']}",
			lambda: [remove_result(r) for r in imported],
		)
	changed = frappe.get_all(
		"Exam Result", filters={"exam": state["alert_exam"], "creation": [">", since]}, pluck="name"
	)
	if changed:
		done.append(f"NOT undone: {len(changed)} marks of {state['alert_exam']} changed during the rehearsal ({', '.join(changed[:5])})")

	for name, before in state["alerts"].items():
		if frappe.db.exists("Marks Alert", name) and frappe.db.get_value("Marks Alert", name, "status") != before["status"]:
			act(f"alert {name} back to {before['status']}", lambda n=name, b=before: frappe.db.set_value("Marks Alert", n, b))
	for doctype, filters, what in (
		("Marks Alert", {"exam": ["in", exams]}, "marks alerts"),
		("SMS Outbox", {"reference_name": ["in", exams]}, "SMS (Test mode)"),
		("Comment", {"reference_doctype": "Exam", "reference_name": ["in", exams]}, "timeline comments on the two exams"),
	):
		names = frappe.get_all(doctype, filters={**filters, "creation": [">", since]}, pluck="name", order_by="creation desc")
		if names:
			act(
				f"remove {len(names)} {what} written during the rehearsal",
				lambda d=doctype, n=names: [frappe.delete_doc(d, x, force=True, ignore_permissions=True) for x in n],
			)
	if not frappe.db.get_value("Guardian", state["guardian"], "sms_opt_in"):
		act(f"{state['guardian']} agrees to SMS again", lambda: frappe.db.set_value("Guardian", state["guardian"], "sms_opt_in", 1))

	if not int(dry_run):
		frappe.db.commit()
	print(("Would do" if int(dry_run) else "Done") + (":" if done else ": nothing to put back"))
	for line in done:
		print(f"  - {line}")
	return done


def remove_result(result):
	"""Cancel (the term result is recomputed) and delete one mark imported during the rehearsal."""
	doc = frappe.get_doc("Exam Result", result.name)
	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.cancel()
	frappe.delete_doc("Exam Result", doc.name, force=True, ignore_permissions=True)
