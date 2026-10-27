// Show the API secret on the User form (Settings > API Access) every time, with copy buttons.
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

	frappe
		.call({ method: "litwatch.api.api_keys.get_api_secret", args: { user: frm.doc.name }, freeze: false })
		.then((r) => {
			const secret = r.message && r.message.api_secret;
			if (!secret) return;
			const token = `token ${frm.doc.api_key}:${secret}`;
			const $box = $(`
				<div class="litwatch-api-secret" style="margin-top: 8px">
					<div style="font-family: var(--font-family-monospace, monospace); padding: 6px 10px;
						background: var(--control-bg); border-radius: var(--border-radius); user-select: all">
						${frappe.utils.escape_html(secret)}
					</div>
					<div style="margin-top: 6px">
						<button class="btn btn-xs btn-default ls-copy-secret">${__("Copy secret")}</button>
						<button class="btn btn-xs btn-default ls-copy-token" style="margin-left: 6px">${__("Copy token")}</button>
					</div>
				</div>`);
			$box.find(".ls-copy-secret").on("click", () => frappe.utils.copy_to_clipboard(secret));
			$box.find(".ls-copy-token").on("click", () => frappe.utils.copy_to_clipboard(token));
			field.$wrapper.append($box);
		})
		.catch(() => {});
}
