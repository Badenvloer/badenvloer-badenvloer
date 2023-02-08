from odoo import api, fields, models, _


class ProductAttribute(models.Model):
    _inherit = "product.attribute"

    ba_ref = fields.Char()