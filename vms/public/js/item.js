frappe.ui.form.on('Item', {
    custom_length: function(frm) {
        calculate_volume(frm);
    },
    custom_width: function(frm) {
        calculate_volume(frm);
    },
    custom_height: function(frm) {
        calculate_volume(frm);
    }
});

function calculate_volume(frm) {
    const length_cm = flt(frm.doc.custom_length);
    const width_cm = flt(frm.doc.custom_width);
    const height_cm = flt(frm.doc.custom_height);

    if (length_cm && width_cm && height_cm) {
        const volume_m3 = (length_cm * width_cm * height_cm) / 1000000;
        frm.set_value('custom_volume_per_unit', volume_m3);
    } else {
        frm.set_value('custom_volume_per_unit', 0);
    }
}
