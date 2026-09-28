// The admission form is for parents: everything they see is in Swahili, like the parent portal. What Frappe itself
// shows in English on this page is put in Swahili here, and the form is checked in Swahili before it is sent (the
// server checks the same things again: StudentAdmission.validate_application).
const web_form = frappe.web_form;

// Page parts that come from Frappe (the website's navbar and footer too, on this page only)
$(".discard-btn").hide(); // a new application has nothing to discard
$(".indicator-pill").text("Haijatumwa");
$(".new-btn").text("Tuma maombi mengine"); // on the success page: another child
$("a.btn-login-area, .btn-login-area > a").text("Ingia");
$(".navbar-brand span").filter((_, el) => $(el).text().trim() === "Home").text("Mwanzo");
$(".footer-powered").each((_, el) => {
	el.innerHTML = el.innerHTML.replace("Built on", "Imejengwa kwa");
});

// The calendar in Swahili, with no date after today
$.fn.datepicker.language.sw = {
	days: ["Jumapili", "Jumatatu", "Jumanne", "Jumatano", "Alhamisi", "Ijumaa", "Jumamosi"],
	daysShort: ["Jpi", "Jtt", "Jnn", "Jtn", "Alh", "Iju", "Jmo"],
	daysMin: ["J2", "J3", "J4", "J5", "Al", "Ij", "J1"],
	months: [
		"Januari",
		"Februari",
		"Machi",
		"Aprili",
		"Mei",
		"Juni",
		"Julai",
		"Agosti",
		"Septemba",
		"Oktoba",
		"Novemba",
		"Desemba",
	],
	monthsShort: ["Jan", "Feb", "Mac", "Apr", "Mei", "Jun", "Jul", "Ago", "Sep", "Okt", "Nov", "Des"],
	today: "Leo",
	clear: "Futa",
	dateFormat: "dd-mm-yyyy",
	timeFormat: "hh:ii",
	firstDay: 1,
};
const birth_date = web_form.fields_dict.date_of_birth;
if (birth_date && birth_date.datepicker) {
	birth_date.today_text = "Leo";
	birth_date.datepicker.update({ language: "sw", maxDate: new Date() });
}

const REQUIRED = {
	full_name: "Jina kamili la mwanafunzi",
	date_of_birth: "Tarehe ya kuzaliwa",
	parent_name: "Jina kamili la mzazi au mlezi",
	phone_number: "Namba ya simu ya mkononi",
};
const MAX_LENGTH = { full_name: "Jina la mwanafunzi", parent_name: "Jina la mzazi au mlezi", email: "Barua pepe" };

// Like smart_school.portal_utils.normalize_tz_mobile: 0754 123 456, 754123456 and +255 754 123 456 are the same
function tanzanian_mobile(phone) {
	let digits = String(phone || "").replace(/\D/g, "");
	if (digits.length === 10 && digits.startsWith("0")) {
		digits = "255" + digits.slice(1);
	} else if (digits.length === 9) {
		digits = "255" + digits;
	}
	return /^255[67]\d{8}$/.test(digits) ? digits : null;
}

function problems(values) {
	const found = [];
	for (const [fieldname, label] of Object.entries(REQUIRED)) {
		if (!String(values[fieldname] || "").trim()) {
			found.push(`Jaza: ${label}.`);
		}
	}
	for (const [fieldname, label] of Object.entries(MAX_LENGTH)) {
		if (String(values[fieldname] || "").length > 140) {
			found.push(`${label} ni refu mno: herufi 140 ndizo nyingi zaidi.`);
		}
	}
	if (values.phone_number && !tanzanian_mobile(values.phone_number)) {
		found.push("Namba ya simu si sahihi. Andika namba ya simu ya mkononi ya Tanzania, mfano 0754 123 456.");
	}
	if (values.date_of_birth && frappe.datetime.get_diff(frappe.datetime.get_today(), values.date_of_birth) < 0) {
		found.push("Tarehe ya kuzaliwa haiwezi kuwa ya baadaye.");
	}
	if (values.email && !frappe.utils.validate_type(values.email, "email")) {
		found.push("Barua pepe si sahihi, mfano jina@mfano.com.");
	}
	return found;
}

// Checked here first, so Frappe's own (English) messages about missing values never show
const send = web_form.save.bind(web_form);
web_form.save = () => {
	const found = problems(web_form.get_values(true) || {});
	if (found.length) {
		frappe.msgprint({
			title: "Tafadhali rekebisha",
			message: `<ul>${found.map((p) => `<li>${frappe.utils.escape_html(p)}</li>`).join("")}</ul>`,
			indicator: "orange",
		});
		return false;
	}
	return send();
};
