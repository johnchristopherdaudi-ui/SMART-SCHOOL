// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("SMS Outbox", {
	refresh(frm) {
		const manager = frappe.user.has_role("Headmaster") || frappe.user.has_role("System Manager");
		if (manager && ["Failed", "Skipped"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Try Again"), () => {
				frappe.call({
					method: "smart_school.sms.retry",
					args: { names: [frm.doc.name] },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			});
		}
	},
});
