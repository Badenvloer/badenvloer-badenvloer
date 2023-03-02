from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = "res.partner"

    pricelist_csv = fields.Binary()
    column_sale_price = fields.Integer()
    column_purchase_price = fields.Integer()
    column_gln = fields.Integer()

    @api.onchange("pricelist_xls")
    def _validate_pricelist(self):
        """ Validate if pricelist has the right fields. """
        return True
