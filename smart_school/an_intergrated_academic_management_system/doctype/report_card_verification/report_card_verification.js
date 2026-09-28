// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

frappe.ui.form.on("Report Card Verification", {
	refresh(frm) {
		const can_revoke = frappe.user.has_role("Headmaster") || frappe.user.has_role("System Manager");
		if (frm.doc.revoked || !can_revoke) return;
		frm.add_custom_button(__("Revoke"), () => {
			frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
				({ reason }) =>
					frappe
						.call("smart_school.verification.revoke", { name: frm.doc.name, reason })
						.then(() => frm.reload_doc()),
				__("Revoke this report card? Its QR code will show it as not valid."),
				__("Revoke")
			);
		}).addClass("btn-danger");
	},
});
