// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("Announcement", {
	refresh(frm) {
		const manager = frappe.user.has_role("Headmaster") || frappe.user.has_role("System Manager");
		if (frm.is_new() || frm.doc.sms_sent_on || !manager) {
			return;
		}
		frm.add_custom_button(__("Also Send by SMS"), () => confirm_sms(frm));
	},
});

// The title and a portal link go by SMS, not the whole announcement
function confirm_sms(frm) {
	frappe.call({
		method: "smart_school.sms.preview_announcement",
		args: { announcement: frm.doc.name },
		freeze: true,
		callback: (r) => {
			const p = r.message;
			if (p.mode === "Off") {
				frappe.msgprint(__("SMS are turned off (Smart School Settings > SMS Mode)."));
				return;
			}
			if (!p.template_enabled) {
				frappe.msgprint(__("The Announcement SMS template is switched off."));
				return;
			}
			const money = (v) => format_number(v, null, 0);
			const lines = [
				p.mode === "Test" ? `<b>${__("Test mode")}</b>: ${__("messages are written to the SMS Outbox, not sent.")}` : "",
				__("{0} guardians: {1} SMS, about TZS {2}.", [p.messages, p.sms, money(p.cost)]),
				__("Not agreed to SMS: {0} · wrong or missing number: {1}.", [p.skipped, p.failed]),
				__("Left today: {0} of {1} SMS; this month: {2} of {3}.", [p.remaining_today, p.daily_limit, p.remaining_month, p.monthly_limit]),
			].filter(Boolean);
			if (!p.fits_month) {
				frappe.msgprint(lines.concat(__("Not enough SMS left this month.")).map((l) => `<p>${l}</p>`).join(""));
				return;
			}
			frappe.confirm(lines.map((l) => `<p>${l}</p>`).join("") + `<p>${__("Send?")}</p>`, () => {
				frappe.call({
					method: "smart_school.sms.send_announcement",
					args: { announcement: frm.doc.name },
					freeze: true,
					callback: (res) => {
						frappe.show_alert({ message: __("{0} SMS messages written", [res.message]), indicator: "green" });
						frm.reload_doc();
					},
				});
			});
		},
	});
}
