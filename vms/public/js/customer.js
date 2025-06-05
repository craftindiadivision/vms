frappe.ui.form.on('Customer', {
    territory(frm) {
        frm.set_query('custom_route', () => {
            return {
                filters: {
                    territory: frm.doc.territory
                }
            };
        });
    }
});
