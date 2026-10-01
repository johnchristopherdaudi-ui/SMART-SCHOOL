"""Marks alerts: marks that may need a second look.

Statistical checks look at one subject of one exam (the whole class, and each student against the class);
they can be switched off in Smart School Settings. Integrity checks always run: marks changed after an exam
was first published (even while it is unpublished), results being unpublished, and marks entered by someone
not assigned to the subject. Alerts only ask for a review: they never block saving or publishing, and their
wording never accuses anyone."""

import json
import statistics
from collections import Counter

import frappe
from frappe.utils import add_days, cint, flt, get_fullname, getdate, now_datetime

from smart_school.results import PUBLISHER_ROLES

IDENTICAL = "Many Identical Marks"
ZEROS = "Many Zero Marks"
LOW_SPREAD = "Very Low Spread"
ROUND = "Many Round Numbers"
CLASS_AVERAGE = "Unusual Class Average"
STUDENT_CHANGE = "Unusual Student Change"
ZERO_DROP = "Dropped To Zero"
SWAPPED = "Possibly Swapped Marks"
CHANGED_AFTER_PUBLISH = "Changed After Publish"
UNASSIGNED = "Entered By Unassigned User"
UNPUBLISHED = "Results Unpublished"

STATISTICAL_TYPES = (IDENTICAL, ZEROS, LOW_SPREAD, ROUND, CLASS_AVERAGE, STUDENT_CHANGE, ZERO_DROP, SWAPPED)
SWAP_MIN_RATIO = 0.5  # the smaller of the two moves is at least half the larger
INTEGRITY_TYPES = (CHANGED_AFTER_PUBLISH, UNASSIGNED, UNPUBLISHED)

MAD_SCALE = 0.6745  # makes the MAD comparable to a standard deviation for normally spread numbers
PREVIOUS_EXAM_WINDOW = 365  # days: a student's previous exam must be this recent to compare with
ROUND_BASE = 5

DEFAULTS = {
	"enable_marks_alerts": 1,
	"alert_min_class_size": 10,
	"alert_identical_share": 40,
	"alert_zero_share": 20,
	"alert_round_share": 80,
	"alert_min_std": 3,
	"alert_history_min_exams": 4,
	"alert_class_z": 3.5,
	"alert_class_min_diff": 10,
	"alert_student_z": 4.5,
	"alert_student_min_jump": 20,
	"alert_zero_drop_from": 30,
	"alert_swap_z": 3.5,
}


def get_settings():
	s = frappe.get_single("Smart School Settings")
	return frappe._dict(
		enabled=cint(s.enable_marks_alerts),
		min_class_size=cint(s.alert_min_class_size) or DEFAULTS["alert_min_class_size"],
		identical_share=flt(s.alert_identical_share) or DEFAULTS["alert_identical_share"],
		zero_share=flt(s.alert_zero_share) or DEFAULTS["alert_zero_share"],
		round_share=flt(s.alert_round_share) or DEFAULTS["alert_round_share"],
		min_std=flt(s.alert_min_std),
		history_min_exams=cint(s.alert_history_min_exams) or DEFAULTS["alert_history_min_exams"],
		class_z=flt(s.alert_class_z) or DEFAULTS["alert_class_z"],
		class_min_diff=flt(s.alert_class_min_diff),
		student_z=flt(s.alert_student_z) or DEFAULTS["alert_student_z"],
		student_min_jump=flt(s.alert_student_min_jump),
		zero_drop_from=flt(s.alert_zero_drop_from) or DEFAULTS["alert_zero_drop_from"],
		swap_z=flt(s.get("alert_swap_z")) or DEFAULTS["alert_swap_z"],
	)


# ---------- statistics ----------


def mad(values):
	"""Median absolute deviation from the median."""
	middle = statistics.median(values)
	return statistics.median(abs(v - middle) for v in values)


def robust_z(value, values):
	"""How far value lies from the median of values, in (scaled) MAD units; None when the MAD is 0."""
	spread = mad(values)
	if not spread:
		return None
	return MAD_SCALE * (value - statistics.median(values)) / spread


def share(count, total):
	return flt(count / total * 100, 1) if total else 0


def check_class_marks(marks, max_marks, settings):
	"""Checks on the raw marks of one subject in one exam. Returns [(alert type, severity, evidence)]."""
	n = len(marks)
	if n < settings.min_class_size:
		return []

	max_marks = flt(max_marks) or 100
	findings = []

	zeros = sum(1 for m in marks if m == 0)
	if share(zeros, n) >= settings.zero_share:
		findings.append((ZEROS, "Medium", {"students": n, "zeros": zeros, "share": share(zeros, n)}))

	# 0 and full marks are left out: many zeros have their own check, and full marks can be genuine
	middle = [flt(m, 2) for m in marks if 0 < m < max_marks]
	if middle:
		mark, count = Counter(middle).most_common(1)[0]
		if share(count, n) >= settings.identical_share:
			findings.append(
				(IDENTICAL, "Medium", {"students": n, "mark": mark, "count": count, "share": share(count, n)})
			)

	# Raw marks, not percentages: out of 40, percentages would move the ~20% base rate of multiples of 5
	if len(middle) >= settings.min_class_size:
		round_count = sum(1 for m in middle if m % ROUND_BASE == 0)
		if share(round_count, len(middle)) >= settings.round_share:
			findings.append(
				(
					ROUND,
					"Low",
					{
						"marks_checked": len(middle),
						"multiples_of_5": round_count,
						"share": share(round_count, len(middle)),
						"max_marks": max_marks,
					},
				)
			)

	std = statistics.pstdev(m / max_marks * 100 for m in marks)
	if std < settings.min_std:
		findings.append(
			(
				LOW_SPREAD,
				"Medium",
				{
					"students": n,
					"std_percentage_points": flt(std, 2),
					"mean_percentage": flt(statistics.mean(marks) / max_marks * 100, 1),
					"min_std": settings.min_std,
				},
			)
		)

	return findings


def check_class_average(mean, history, settings):
	"""The class average (percentage) against the class averages of earlier exams of the subject
	at the same level. A MAD from a few exams can be tiny, so the average must also be a number of
	points away from the usual one."""
	if mean is None or len(history) < settings.history_min_exams:
		return []
	z = robust_z(mean, history)
	if z is None or abs(z) <= settings.class_z:
		return []
	if abs(mean - statistics.median(history)) < settings.class_min_diff:
		return []
	return [
		(
			CLASS_AVERAGE,
			"Medium",
			{
				"class_average": flt(mean, 1),
				"history_median": flt(statistics.median(history), 1),
				"history_mad": flt(mad(history), 2),
				"history_exams": len(history),
				"robust_z": flt(z, 2),
				"threshold": settings.class_z,
				"min_diff": settings.class_min_diff,
			},
		)
	]


def check_student_changes(pairs, settings, class_has_many_zeros=False):
	"""pairs: {student: (previous percentage, current percentage, previous exam)}.

	A student who had at least zero_drop_from % and now has 0 always gets a Medium "Dropped To Zero" alert
	(often a missed exam or a mark not entered) instead of a statistical one, except when the whole class
	has many zeros: that has its own alert.

	Each other student's change is compared with the class's median change (the residual), so a hard exam
	that lowers everyone does not raise alerts; only students who moved much more than the class do."""
	findings, zero_drops = [], set()
	for student, (previous, now, previous_exam) in pairs.items():
		if now == 0 and previous >= settings.zero_drop_from:
			zero_drops.add(student)
			if not class_has_many_zeros:
				findings.append(
					(
						ZERO_DROP,
						"Medium",
						{
							"student": student,
							"previous_exam": previous_exam,
							"previous_percentage": flt(previous, 1),
							"current_percentage": 0,
							"zero_drop_from": settings.zero_drop_from,
						},
					)
				)

	if len(pairs) < settings.min_class_size:
		return findings

	changes = {student: now - previous for student, (previous, now, _) in pairs.items()}
	class_change = statistics.median(changes.values())
	spread = mad(list(changes.values()))
	if not spread:
		return findings

	for student, change in changes.items():
		if student in zero_drops:
			continue
		residual = change - class_change
		z = MAD_SCALE * residual / spread
		if abs(z) <= settings.student_z or abs(residual) < settings.student_min_jump:
			continue
		previous, now, previous_exam = pairs[student]
		findings.append(
			(
				STUDENT_CHANGE,
				"Medium" if abs(z) >= 2 * settings.student_z else "Low",
				{
					"student": student,
					"previous_exam": previous_exam,
					"previous_percentage": flt(previous, 1),
					"current_percentage": flt(now, 1),
					"change": flt(change, 1),
					"class_median_change": flt(class_change, 1),
					"residual": flt(residual, 1),
					"mad": flt(spread, 2),
					"robust_z": flt(z, 2),
					"students_compared": len(pairs),
				},
			)
		)
	return findings


# ---------- running the checks ----------


def find_swapped_marks(pairs, min_z, min_ratio, back_z=None, zero_drop_from=30, min_jump=0, exclusive=True):
	"""Pairs of students whose marks look typed against each other's names, from
	pairs = {student: (previous percentage, current percentage, ...)} of one subject in one exam.

	Each student's change is compared with the class's median change in robust z (as for Unusual Student Change).
	A pair is two students, one up and one down, both at least min_z, of similar size (the smaller at least
	min_ratio of the larger). back_z: also ask that, with their current marks swapped back, both would be ordinary
	(|z| at most back_z). min_jump: both must also move at least this many points more than the class. Each
	student is in one pair at most (exclusive), the most convincing first. A student who dropped to 0 from zero_drop_from %
	or more is left out (a missed exam, alerted on its own)."""
	changes = {
		s: now - previous
		for s, (previous, now, *_) in pairs.items()
		if not (now == 0 and previous >= zero_drop_from)
	}
	if len(changes) < 2:
		return []
	middle = statistics.median(changes.values())
	spread = mad(list(changes.values()))
	if not spread:
		return []
	z = {s: MAD_SCALE * (c - middle) / spread for s, c in changes.items()}
	ups = [s for s in z if z[s] >= min_z and changes[s] - middle >= min_jump]
	downs = [s for s in z if z[s] <= -min_z and middle - changes[s] >= min_jump]
	candidates = []
	for a in ups:
		for b in downs:
			small, large = sorted((abs(z[a]), abs(z[b])))
			if small < min_ratio * large:
				continue
			(prev_a, now_a), (prev_b, now_b) = pairs[a][:2], pairs[b][:2]
			back_a = MAD_SCALE * ((now_b - prev_a) - middle) / spread
			back_b = MAD_SCALE * ((now_a - prev_b) - middle) / spread
			back = max(abs(back_a), abs(back_b))
			if back_z is not None and back > back_z:
				continue
			candidates.append((back, -(abs(z[a]) + abs(z[b])), a, b, z[a], z[b], back_a, back_b))
	found, used = [], set()
	for back, _, a, b, za, zb, back_a, back_b in sorted(candidates):
		if exclusive and (a in used or b in used):
			continue
		used.update((a, b))
		found.append({"up": a, "down": b, "z_up": za, "z_down": zb, "z_up_swapped_back": back_a, "z_down_swapped_back": back_b})
	return found


def check_swapped_marks(pairs, settings):
	"""Marks typed against each other's names: pairs of students of the class, one up and one down by a similar,
	unusual amount (robust z at least swap_z, and at least student_min_jump points more than the class). One alert
	per subject of an exam, listing every such pair (a student can be in more than one: the scripts tell which).
	Measured on 30 generated schools: with the general check it finds about 4 in 5 swapped students (the general
	check alone about half) for about 3 more alerts a year in a 300-student school."""
	if len(pairs) < settings.min_class_size:
		return []
	found = find_swapped_marks(
		pairs,
		settings.swap_z,
		SWAP_MIN_RATIO,
		zero_drop_from=settings.zero_drop_from,
		min_jump=settings.student_min_jump,
		exclusive=False,
	)
	if not found:
		return []
	middle = statistics.median(now - previous for previous, now, _ in pairs.values())
	listed = []
	for f in found:
		(up_before, up_now, _), (down_before, down_now, _) = pairs[f["up"]], pairs[f["down"]]
		listed.append(
			{
				"up": f["up"],
				"down": f["down"],
				"up_marks": [flt(up_before, 1), flt(up_now, 1)],
				"down_marks": [flt(down_before, 1), flt(down_now, 1)],
				"robust_z": [flt(f["z_up"], 2), flt(f["z_down"], 2)],
				"robust_z_swapped_back": [flt(f["z_up_swapped_back"], 2), flt(f["z_down_swapped_back"], 2)],
			}
		)
	students = sorted({p["up"] for p in listed} | {p["down"] for p in listed})
	return [
		(
			SWAPPED,
			"Medium",
			{
				"pairs": listed,
				"students": students,
				"class_median_change": flt(middle, 1),
				"threshold": settings.swap_z,
			},
		)
	]


def run_exam_checks(exam, settings=None):
	"""Run the checks on one exam and save what is found. The statistical checks (and auto-resolving
	their alerts) only run when they are enabled; the integrity check always runs."""
	settings = settings or get_settings()
	exam = frappe.get_doc("Exam", exam)
	results = frappe.get_all(
		"Exam Result",
		filters={"exam": exam.name, "docstatus": 1},
		fields=["name", "student", "subject", "marks", "percentage", "owner"],
	)
	if settings.enabled:
		run_statistical_checks(exam, results, settings)
	check_unassigned_entries(exam, results)


def run_statistical_checks(exam, results, settings):
	by_subject = {}
	for r in results:
		by_subject.setdefault(r.subject, []).append(r)

	subjects = list(by_subject)
	history = get_class_average_history(exam, subjects, settings)
	previous = get_previous_percentages(exam, [r.student for r in results], subjects)

	found = set()
	for subject, rows in by_subject.items():
		findings = check_class_marks([flt(r.marks) for r in rows], exam.max_marks, settings)
		many_zeros = any(alert_type == ZEROS for alert_type, _, _ in findings)
		mean = None
		if len(rows) >= settings.min_class_size:
			mean = statistics.mean(flt(r.percentage) for r in rows)
		average = check_class_average(mean, history.get(subject, []), settings)
		for _, _, evidence in average:
			evidence["compared_with"] = history_kind(exam)
		findings += average
		pairs = {}
		for r in rows:
			if (r.student, subject) in previous:
				percentage, previous_exam = previous[(r.student, subject)]
				pairs[r.student] = (percentage, flt(r.percentage), previous_exam)
		findings += check_student_changes(pairs, settings, many_zeros)
		if not many_zeros:
			findings += check_swapped_marks(pairs, settings)

		for alert_type, severity, evidence in findings:
			student = evidence.get("student")
			key = "|".join(filter(None, [alert_type, exam.name, subject, student]))
			found.add(key)
			save_alert(
				key,
				alert_type=alert_type,
				severity=severity,
				exam=exam,
				subject=subject,
				student=student,
				evidence=evidence,
				message=statistical_message(alert_type, subject, evidence),
			)

	auto_resolve(exam.name, found)


def get_class_average_history(exam, subjects, settings):
	"""{subject: [class average of each earlier exam of the same kind at the same level]}: exams of earlier terms,
	with at least the minimum class size, of any class of the same Form. School exams are compared with school
	exams, an external exam only with earlier external exams of the same type (a District Exam with District
	Exams): a harder outside paper says nothing about the school's own marks."""
	level = frappe.db.get_value("Class", exam.get("class"), "level")
	term_start = frappe.db.get_value("Term", exam.term, "start_date")
	if not (level and term_start and subjects):
		return {}

	rows = frappe.db.sql(
		"""
		select er.subject, avg(er.percentage) as average, count(*) as students
		from `tabExam Result` er
		join `tabExam` e on e.name = er.exam
		join `tabTerm` t on t.name = e.term
		join `tabClass` c on c.name = e.`class`
		where er.docstatus = 1 and c.level = %(level)s and t.start_date < %(term_start)s
			and er.subject in %(subjects)s
			and ifnull(e.is_external, 0) = %(external)s
			and (%(external)s = 0 or e.external_exam_type = %(external_type)s)
		group by er.exam, er.subject
		""",
		{
			"level": level,
			"term_start": term_start,
			"subjects": tuple(subjects),
			"external": 1 if exam.get("is_external") else 0,
			"external_type": exam.get("external_exam_type") or "",
		},
		as_dict=True,
	)
	history = {}
	for r in rows:
		if r.students >= settings.min_class_size:
			history.setdefault(r.subject, []).append(flt(r.average))
	return history


def history_kind(exam):
	return f"earlier {exam.external_exam_type} papers" if exam.get("is_external") else "earlier school exams"


def get_previous_percentages(exam, students, subjects):
	"""{(student, subject): (percentage, exam)} from each student's latest earlier exam in that subject.
	Exams are ordered by term start, then by when the exam was created (exams have no date)."""
	term_start = frappe.db.get_value("Term", exam.term, "start_date")
	if not (term_start and students and subjects):
		return {}

	rows = frappe.db.sql(
		"""
		select er.student, er.subject, er.percentage, er.exam
		from `tabExam Result` er
		join `tabExam` e on e.name = er.exam
		join `tabTerm` t on t.name = e.term
		where er.docstatus = 1 and er.exam != %(exam)s
			and er.student in %(students)s and er.subject in %(subjects)s
			and t.start_date >= %(window_start)s
			and (t.start_date < %(term_start)s or (t.start_date = %(term_start)s and e.creation < %(creation)s))
		order by t.start_date, e.creation
		""",
		{
			"exam": exam.name,
			"students": tuple(set(students)),
			"subjects": tuple(subjects),
			"term_start": term_start,
			"window_start": add_days(getdate(term_start), -PREVIOUS_EXAM_WINDOW),
			"creation": exam.creation,
		},
		as_dict=True,
	)
	# Rows are oldest first, so the latest earlier exam wins
	return {(r.student, r.subject): (flt(r.percentage), r.exam) for r in rows}


def check_unassigned_entries(exam, results):
	"""Marks entered by a user who is not assigned to the subject in the exam's class.
	Headmaster and System Manager may enter any subject, so their entries are not checked."""
	by_user = {}
	for r in results:
		by_user.setdefault((r.subject, r.owner), []).append(r)

	for (subject, user), rows in by_user.items():
		if may_enter_any_subject(user):
			continue
		teacher = frappe.db.get_value("Teacher", {"user": user}, "name")
		if teacher and frappe.db.exists(
			"Teacher Subject Assignment",
			{"parenttype": "Teacher", "parent": teacher, "subject": subject, "class": exam.get("class")},
		):
			continue

		evidence = {
			"user": user,
			"teacher": teacher,
			"results": len(rows),
			"examples": sorted(r.name for r in rows)[:5],
		}
		save_alert(
			"|".join([UNASSIGNED, exam.name, subject, user]),
			alert_type=UNASSIGNED,
			severity="Medium",
			exam=exam,
			subject=subject,
			related_user=user,
			evidence=evidence,
			message=(
				f"{len(rows)} {subject} mark(s) in {exam.exam_name} were entered by {get_fullname(user)}, "
				f"who is not listed as teaching {subject} in {exam.get('class')}. "
				"Please confirm this was agreed, or update the teacher's subject assignments."
			),
		)


def may_enter_any_subject(user):
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & set(PUBLISHER_ROLES))


# ---------- changes after publishing ----------


def note_change_after_publish(result, action):
	"""Exam Result on_submit / on_cancel: any change to the marks of an exam that has ever been published,
	by anyone (HM included), also while its results are unpublished."""
	published, first_published_on = frappe.db.get_value(
		"Exam", result.exam, ["results_published", "first_published_on"]
	)
	if not (published or first_published_on):
		return
	previous = result.amended_from and frappe.db.get_value("Exam Result", result.amended_from, "marks")
	record_change_after_publish(
		result.exam,
		result.subject,
		result.student,
		{
			"id": f"{result.name}|{result.docstatus}",
			"result": result.name,
			"action": action,
			"marks": flt(result.marks),
			"previous_marks": None if previous is None else flt(previous),
			"by": frappe.session.user,
			"on": str(now_datetime()),
		},
	)


def find_changes_after_publish():
	"""Nightly safety net for changes the form hook cannot see (for example direct database edits).
	Measured from the first publication, so unpublishing, changing and publishing again is still seen."""
	rows = frappe.db.sql(
		"""
		select er.name, er.exam, er.subject, er.student, er.marks, er.docstatus, er.amended_from,
			er.creation, er.modified, er.modified_by, e.first_published_on
		from `tabExam Result` er
		join `tabExam` e on e.name = er.exam
		where e.first_published_on is not null
			and er.docstatus in (1, 2) and er.modified > e.first_published_on
		""",
		as_dict=True,
	)
	for r in rows:
		if r.docstatus == 2:
			action = "cancelled"
		elif r.creation > r.first_published_on:
			action = "submitted"
		else:
			action = "updated"
		previous = r.amended_from and frappe.db.get_value("Exam Result", r.amended_from, "marks")
		record_change_after_publish(
			r.exam,
			r.subject,
			r.student,
			{
				"id": f"{r.name}|{r.docstatus}",
				"result": r.name,
				"action": action,
				"marks": flt(r.marks),
				"previous_marks": None if previous is None else flt(previous),
				"by": r.modified_by,
				"on": str(r.modified),
			},
		)


def record_change_after_publish(exam, subject, student, change):
	"""Add a change to the open alert for this mark, or open a new alert. A change already recorded
	(by the form hook or an earlier night) is skipped; a reviewed alert is never reopened, a new one
	is made instead."""
	alerts = frappe.get_all(
		"Marks Alert",
		filters={"alert_type": CHANGED_AFTER_PUBLISH, "exam": exam, "subject": subject, "student": student},
		fields=["name", "status", "evidence"],
		order_by="creation asc",
	)
	for alert in alerts:
		if any(c["id"] == change["id"] for c in json.loads(alert.evidence or "{}").get("changes", [])):
			return

	open_alert = next((a for a in alerts if a.status == "Open"), None)
	changes = json.loads(open_alert.evidence).get("changes", []) if open_alert else []
	changes.append(change)
	save_alert(
		frappe.db.get_value("Marks Alert", open_alert.name, "alert_key")
		if open_alert
		else f"{CHANGED_AFTER_PUBLISH}|{change['id']}",
		alert_type=CHANGED_AFTER_PUBLISH,
		severity="High",
		exam=frappe.get_doc("Exam", exam),
		subject=subject,
		student=student,
		exam_result=change["result"],
		related_user=change["by"],
		evidence={"changes": changes},
		message=change_message(exam, subject, student, changes),
	)


def note_unpublished(exam, published_on):
	"""Unpublishing hides results from parents; it is recorded as an alert of its own."""
	user = frappe.session.user
	unpublished_on = now_datetime()
	save_alert(
		f"{UNPUBLISHED}|{exam.name}|{unpublished_on}",
		alert_type=UNPUBLISHED,
		severity="Medium",
		exam=exam,
		related_user=user,
		evidence={
			"unpublished_by": user,
			"unpublished_on": unpublished_on,
			"published_on": published_on,
			"first_published_on": exam.first_published_on,
		},
		message=(
			f"Results of {exam.exam_name} ({exam.get('class')}) were unpublished by {get_fullname(user)}. "
			"Parents no longer see them, and any mark changed from now on is flagged as a change after "
			"publishing. Please confirm this was intended."
		),
	)


def change_message(exam, subject, student, changes):
	student_name = frappe.db.get_value("Student", student, "full_name") or student
	exam_name = frappe.db.get_value("Exam", exam, "exam_name") or exam
	first, last = changes[0], changes[-1]
	before = first["marks"] if first["action"] == "cancelled" else first.get("previous_marks")
	after = None if last["action"] == "cancelled" else last["marks"]

	if before is not None and after is not None:
		what = f"was changed from {before:g} to {after:g}"
	elif before is not None:
		what = f"({before:g}) was cancelled"
	elif after is not None:
		what = f"({after:g}) was entered or updated"
	else:  # entered after publishing, then cancelled
		what = f"({first['marks']:g}) was entered and then cancelled"
	return (
		f"The {subject} mark of {student_name} in {exam_name} {what} after the results were published. "
		"Please confirm the change was intended."
	)


# ---------- saving alerts ----------


def save_alert(key, alert_type, severity, exam, evidence, message, **values):
	"""Create the alert for this key or refresh the open one. Alerts a person has reviewed are left alone;
	an auto-resolved alert whose pattern is back opens again."""
	evidence = json.dumps(evidence, indent=1, sort_keys=True, default=str)
	name = frappe.db.get_value("Marks Alert", {"alert_key": key}, "name")
	doc = frappe.get_doc("Marks Alert", name) if name else frappe.new_doc("Marks Alert")
	if doc.status in ("Reviewed-OK", "Corrected"):
		return doc

	values.update(
		{
			"alert_key": key,
			"alert_type": alert_type,
			"severity": severity,
			"exam": exam.name,
			"class": exam.get("class"),
			"term": exam.term,
			"evidence": evidence,
			"message": message,
			"status": "Open",
		}
	)
	if doc.status == "Auto-resolved":
		values.update({"reviewed_on": None, "review_note": None})
	if name and all(doc.get(f) == v for f, v in values.items()):
		return doc

	doc.update(values)
	doc.flags.from_checks = True
	doc.save(ignore_permissions=True)
	return doc


def auto_resolve(exam, found_keys):
	"""Open statistical alerts of this exam whose pattern the latest check no longer finds.
	Integrity alerts are never closed automatically."""
	for name in frappe.get_all(
		"Marks Alert",
		filters={
			"exam": exam,
			"status": "Open",
			"alert_type": ["in", STATISTICAL_TYPES],
			"alert_key": ["not in", list(found_keys) or [""]],
		},
		pluck="name",
	):
		doc = frappe.get_doc("Marks Alert", name)
		doc.status = "Auto-resolved"
		doc.reviewed_on = now_datetime()
		doc.review_note = "The latest check no longer finds this pattern in the marks."
		doc.flags.from_checks = True
		doc.save(ignore_permissions=True)


def statistical_message(alert_type, subject, e):
	if alert_type == ZEROS:
		return (
			f"{e['zeros']} of {e['students']} students have 0 in {subject}. "
			"If some students missed the exam, please confirm that 0 is the intended mark."
		)
	if alert_type == IDENTICAL:
		return (
			f"{e['count']} of {e['students']} students have exactly {e['mark']:g} in {subject}. "
			"This can happen; please confirm the marks are complete and correct."
		)
	if alert_type == ROUND:
		return (
			f"{e['multiples_of_5']} of {e['marks_checked']} {subject} marks are multiples of 5. "
			"Please confirm the marks are exact."
		)
	if alert_type == LOW_SPREAD:
		return (
			f"{subject} marks are very close together (standard deviation {e['std_percentage_points']:g} "
			"percentage points). Please confirm the marks are complete and correct."
		)
	if alert_type == CLASS_AVERAGE:
		direction = "above" if e["class_average"] > e["history_median"] else "below"
		return (
			f"The {subject} class average ({e['class_average']:g}%) is well {direction} the usual average "
			f"for this Form ({e['history_median']:g}% over {e['history_exams']} "
			f"{e.get('compared_with') or 'earlier exams'}). "
			"This may reflect the exam itself; please take a look."
		)
	if alert_type == ZERO_DROP:
		name = frappe.db.get_value("Student", e["student"], "full_name") or e["student"]
		previous = frappe.db.get_value("Exam", e["previous_exam"], "exam_name") or e["previous_exam"]
		return (
			f"{name} had {e['previous_percentage']:g}% in {subject} in {previous} and has 0 now. "
			"If the student missed the exam, please confirm that 0 is the intended mark."
		)
	if alert_type == SWAPPED:
		names = dict(frappe.get_all("Student", filters={"name": ["in", e["students"]]}, fields=["name", "full_name"], as_list=True))
		shown = []
		for p in e["pairs"][:5]:
			up, down = names.get(p["up"], p["up"]), names.get(p["down"], p["down"])
			shown.append(
				f"{up} ({p['up_marks'][0]:g}% → {p['up_marks'][1]:g}%) and {down} "
				f"({p['down_marks'][0]:g}% → {p['down_marks'][1]:g}%)"
			)
		more = f" and {len(e['pairs']) - 5} more" if len(e["pairs"]) > 5 else ""
		return (
			f"{subject} marks may have been typed against each other's names: {'; '.join(shown)}{more}, while the "
			f"class moved by {e['class_median_change']:+g}. The other way round, each pair would be closer to "
			"before. Please check these students' scripts."
		)
	if alert_type == STUDENT_CHANGE:
		name = frappe.db.get_value("Student", e["student"], "full_name") or e["student"]
		return (
			f"{name}'s {subject} result moved from {e['previous_percentage']:g}% to "
			f"{e['current_percentage']:g}% ({e['change']:+g} points), while the class moved by "
			f"{e['class_median_change']:+g} points. This may be genuine; please confirm the mark was "
			"entered correctly."
		)
	return ""


# ---------- entry points ----------


def get_open_alerts(exam):
	alerts = frappe.get_all(
		"Marks Alert",
		filters={"exam": exam, "status": "Open"},
		fields=["name", "alert_type", "severity", "subject", "student_name", "message"],
	)
	order = {"High": 0, "Medium": 1, "Low": 2}
	return sorted(alerts, key=lambda a: (order.get(a.severity, 3), a.subject or "", a.name))


@frappe.whitelist()
def check_exam(exam):
	"""Run before publishing: refresh this exam's alerts and return the open ones as a warning."""
	frappe.only_for(PUBLISHER_ROLES)
	run_exam_checks(exam)
	return get_open_alerts(exam)


def checks_before_publish(exam):
	"""Refresh the exam's alerts and count the open ones. A failing check must never stop publishing."""
	try:
		run_exam_checks(exam)
	except Exception:
		frappe.log_error(title=f"Marks alerts before publishing {exam}")
	return frappe.db.count("Marks Alert", {"exam": exam, "status": "Open"})


def run_nightly_checks():
	"""Daily: changes after publishing, then the exams of the current and previous term."""
	from smart_school.tasks import get_current_term, get_previous_term

	settings = get_settings()
	find_changes_after_publish()

	term = get_current_term()
	if not term:
		return
	terms = [t for t in (term.name, get_previous_term(term)) if t]
	for exam in frappe.get_all("Exam", filters={"term": ["in", terms]}, pluck="name"):
		try:
			run_exam_checks(exam, settings)
		except Exception:
			frappe.log_error(title=f"Marks alerts for {exam}")
