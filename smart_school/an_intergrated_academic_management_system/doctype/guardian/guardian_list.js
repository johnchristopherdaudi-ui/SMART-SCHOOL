// Copyright (c) 2026, john daudi and contributors
// For license information, please see license.txt

// Consent collected on paper, for many guardians at once (Headmaster / System Manager)
frappe.listview_settings["Guardian"] = {
	onload(listview) {
		if (!(frappe.user.has_role("Headmaster") || frappe.user.has_role("System Manager"))) {
			return;
		}
		const set_consent = (opt_in) => {
			const guardians = listview.get_checked_items(true);
			if (!guardians.length) {
				frappe.msgprint(__("Select the guardians first"));
				return;
			}
			const dialog = new frappe.ui.Dialog({
				title: opt_in ? __("Record SMS consent") : __("Withdraw SMS consent"),
				fields: [
					{
						fieldtype: "HTML",
						options: `<p>${__("{0} guardian(s) selected.", [guardians.length])} ${
							opt_in
								? __("Only for parents who agreed in writing; keep the forms.")
								: __("They will get no more SMS.")
						}</p>`,
					},
					{
						fieldname: "consent_date",
						fieldtype: "Date",
						label: opt_in ? __("Date on the consent form") : __("Date"),
						reqd: 1,
						default: frappe.datetime.get_today(),
					},
				],
				primary_action_label: __("Save"),
				primary_action(values) {
					frappe.call({
						method: "smart_school.sms.set_consent_for_guardians",
						args: { guardians, opt_in: opt_in ? 1 : 0, consent_date: values.consent_date },
						freeze: true,
						callback: (r) => {
							dialog.hide();
							frappe.show_alert({ message: __("{0} guardian(s) updated", [r.message]), indicator: "green" });
							listview.refresh();
						},
					});
				},
			});
			dialog.show();
		};
		listview.page.add_actions_menu_item(__("Record SMS Consent (Paper)"), () => set_consent(true));
		listview.page.add_actions_menu_item(__("Withdraw SMS Consent"), () => set_consent(false));
	},
};
