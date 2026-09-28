// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("Smart School Settings", {
	sms_mode(frm) {
		if (frm.doc.sms_mode !== "Live") {
			return;
		}
		frappe.confirm(
			__("Live: messages will really be sent to parents and paid for. Continue?"),
			() => {},
			() => frm.set_value("sms_mode", "Test")
		);
	},
	sms_fee_reminder_before_term(frm) {
		confirm_reminders(frm, "sms_fee_reminder_before_term", "Fee Reminder");
	},
	sms_fee_reminder_overdue(frm) {
		confirm_reminders(frm, "sms_fee_reminder_overdue", "Fee Overdue");
	},
});

// Before a reminder switch is turned on: who would get one today, and what it would cost
function confirm_reminders(frm, fieldname, kind) {
	if (!frm.doc[fieldname] || frm._confirming) {
		return;
	}
	frappe.call({
		method: "smart_school.sms.preview_fee_reminders",
		args: { kind },
		freeze: true,
		callback: (r) => {
			const p = r.message;
			const esc = frappe.utils.escape_html;
			const lines = [];
			if (p.mode === "Off") {
				lines.push(__("SMS Mode is Off: nothing will be sent until it is Test or Live."));
			}
			if (p.messages || p.skipped || p.failed) {
				lines.push(
					__("Today: {0} guardians of {1} students ({2}).", [p.guardians, p.students, esc(p.terms.join(", "))]),
					__("{0} messages, {1} SMS, about TZS {2}.", [p.messages, p.sms, format_number(p.cost, null, 0)]),
					__("Not agreed to SMS: {0}. Wrong or missing number: {1}.", [p.skipped, p.failed])
				);
				if (p.fits_month === false) {
					lines.push(__("Only {0} SMS are left this month: the rest will wait.", [p.remaining_month]));
				}
			} else if (p.next_term) {
				lines.push(
					__("None today. {0}: reminders start on {1}.", [esc(p.next_term), frappe.datetime.str_to_user(p.next_date)])
				);
			} else {
				lines.push(__("No reminder is due today."));
			}
			frappe.confirm(
				lines.map((l) => `<p>${l}</p>`).join("") + `<p>${__("Turn the reminders on?")}</p>`,
				() => {},
				() => {
					frm._confirming = true;
					frm.set_value(fieldname, 0).then(() => (frm._confirming = false));
				}
			);
		},
	});
}
