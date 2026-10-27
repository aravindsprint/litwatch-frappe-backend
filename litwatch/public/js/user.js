// API secret on the User form (Settings > API Access): eye icon to show / hide, copy buttons.
// Frappe itself shows it only once, right after Generate Keys.
frappe.ui.form.on("User", {
	refresh(frm) {
		litwatch_show_api_secret(frm);
	},
	after_save(frm) {
		litwatch_show_api_secret(frm);
	},
});

function litwatch_show_api_secret(frm) {
	const field = frm.fields_dict.api_secret;
	if (!field) return;
	field.$wrapper.find(".litwatch-api-secret").remove();
	if (frm.is_new() || !frm.doc.api_key) return;
	if (frappe.session.user !== frm.doc.name && !frappe.user.has_role("System Manager")) return;
	litwatch_secret_toggle(
		field,
		"litwatch-api-secret",
		{ method: "litwatch.api.api_keys.get_api_secret", args: { user: frm.doc.name }, key: "api_secret" },
		[
			[__("Copy secret"), (s) => s],
			[__("Copy token"), (s) => `token ${frm.doc.api_key}:${s}`],
		]
	);
}

// Eye toggle under a Password field: masked by default; the eye fetches the saved value and shows /
// hides it. Copy buttons fetch it too, so the secret never sits in the page until asked for.
function litwatch_secret_toggle(field, cls, fetch_secret, copies) {
	field.$wrapper.find("." + cls).remove();
	const EYE = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
	const EYE_OFF = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><path d="M14.12 14.12a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>';
	let secret = null;
	const get = async () => {
		if (secret === null) {
			const r = await frappe.call({ method: fetch_secret.method, args: fetch_secret.args });
			secret = (r.message && r.message[fetch_secret.key]) || "";
			if (!secret) frappe.show_alert({ message: __("No secret saved"), indicator: "orange" });
		}
		return secret;
	};
	const $box = $(`
		<div class="${cls}" style="margin-top: 8px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
			<div class="ls-secret-text" style="flex: 1; min-width: 200px; font-family: var(--font-family-monospace, monospace);
				padding: 6px 10px; background: var(--control-bg); border-radius: var(--border-radius); word-break: break-all">••••••••••••••••</div>
			<button class="btn btn-xs btn-default ls-eye" title="${__("Show")}">${EYE}</button>
		</div>`);
	let shown = false;
	$box.find(".ls-eye").on("click", async () => {
		if (!shown) {
			const s = await get();
			if (!s) return;
			$box.find(".ls-secret-text").text(s).css("user-select", "all");
		} else {
			$box.find(".ls-secret-text").text("••••••••••••••••").css("user-select", "none");
		}
		shown = !shown;
		$box.find(".ls-eye").html(shown ? EYE_OFF : EYE).attr("title", shown ? __("Hide") : __("Show"));
	});
	(copies || []).forEach(([label, make]) => {
		const $b = $(`<button class="btn btn-xs btn-default">${label}</button>`);
		$b.on("click", async () => {
			const s = await get();
			if (s) frappe.utils.copy_to_clipboard(make(s));
		});
		$box.append($b);
	});
	field.$wrapper.append($box);
}
