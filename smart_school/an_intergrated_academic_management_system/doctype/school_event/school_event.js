// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("School Event", {
	refresh(frm) {
		frm.add_custom_button(__("Calendar"), () => frappe.set_route("List", "School Event", "Calendar"));
	},
	// Before the SMS reminder is switched on: how many guardians it reaches and what it costs
	sms_reminder(frm) {
		if (!frm.doc.sms_reminder || frm._confirming) return;
		frappe.call({
			method: "smart_school.sms.preview_event_reminder",
			args: {
				event: frm.is_new() ? null : frm.doc.name,
				audience: frm.doc.audience,
				classes: (frm.doc.classes || []).map((c) => c.class),
			},
			callback: (r) => {
				const p = r.message;
				const lines = [];
				if (p.mode === "Off") lines.push(__("SMS Mode is Off: nothing will be sent until it is Test or Live."));
				lines.push(
					__("{0} guardians: {1} SMS, about TZS {2}.", [p.messages, p.sms, format_number(p.cost, null, 0)]),
					__("Not agreed to SMS: {0}. Wrong or missing number: {1}.", [p.skipped, p.failed])
				);
				if (p.fits_month === false) lines.push(__("Only {0} SMS are left this month: the rest will wait.", [p.remaining_month]));
				frappe.confirm(
					lines.map((l) => `<p>${l}</p>`).join("") + `<p>${__("Send the reminder {0} day(s) before the event?", [frm.doc.sms_days_before || 0])}</p>`,
					() => {},
					() => {
						frm._confirming = true;
						frm.set_value("sms_reminder", 0).then(() => (frm._confirming = false));
					}
				);
			},
		});
	},
});
