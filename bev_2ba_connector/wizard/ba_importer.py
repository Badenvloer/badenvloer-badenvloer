from odoo import models, fields
from odoo.exceptions import AccessError, UserError
import logging
import requests
from datetime import datetime, timedelta, date
from base64 import b64encode, b64decode
import csv
import io

_logger = logging.getLogger(__name__)


class BaImporterWizard(models.TransientModel):
    """
    Wizard for importing products from the 2ba api
    """
    _name = 'ba.importer.wizard'
    _description = '2ba importer wizard'

    baseUrl = "https://api.2ba.nl/1"
    authUrl = "https://authorize.2ba.nl/OAuth/Token"
    skus = fields.Text()
    pricelist_partner_id = fields.Many2one("res.partner", domain="[('pricelist_csv', '!=', False)]")

    def execute_import(self):
        """
        Imports products according to a list of products GTIN
        First we check if the product doesn't exist already. if so we give an error.
        When no duplicate products are found we start importing the products
        """

        for wizard in self:
            skus = wizard.skus.splitlines()

            # Execute call
            for sku in skus:
                if len(str(sku)) == 13:
                    sku = "0" + str(sku)
                prod = self.env['product.template'].sudo().search([
                    ("barcode", "=", sku)
                ])
                if prod:
                    if self._context.get("update_content"):
                        product = self.get_product_by_gtin(sku)
                        if 'IsError' in product.keys():
                            raise UserError("[%s]: %s" % (sku, product.get("ErrorMessage")))
                            continue
                        template = {
                            "name": product.get("Description"),
                            "description": product.get("Description"),
                            "description_sale": product.get("LongDescription"),
                            "weight": product.get("WeightQuantity"),
                            "weight_uom_name": product.get("WeightMeasureUnitDescription"),
                            "barcode": product.get("GTIN"),
                            "detailed_type": "product",
                            "ba_ref": product.get("Id"),
                            "default_code": product.get("Productcode"),
                        }
                        prod.write(template)
                    if self.pricelist_partner_id:
                        pricing = self.get_prices(sku)
                        _logger.info(pricing)
                        if pricing.get("sale_price"):
                            prod.write({
                                "list_price": pricing.get("sale_price", 0),
                            })
                        if pricing.get("purchase_price"):
                            prod.write({
                                "standard_price": pricing.get("purchase_price", 0),
                            })
                    continue
                if datetime.now() > datetime.fromtimestamp(
                        float(self.env.ref('bev_2ba_connector.ba_importer_authorization_expire').sudo().value)):
                    self.refresh_access()

                product = self.get_product_by_gtin(sku)
                if 'IsError' in product.keys():
                    raise UserError("[%s]: %s" % (sku, product.get("ErrorMessage")))
                    continue

                thumbnail = self.get_product_thumbnail(product.get('ManufacturerGLN'), product.get('Productcode'))

                attributes = self._get_product_attributes(sku)
                attr_list = []
                # loop features
                for attr in attributes.get("Features"):
                    res = self.env['product.attribute'].sudo().search([
                        ("ba_ref", "=", attr.get("FeatureID"))
                    ], limit=1)
                    if not res:
                        res = self.env['product.attribute'].sudo().search([
                            ("name", "=", attr.get("Description"))
                        ], limit=1)
                        if not res:
                            res = self.env["product.attribute"].sudo().create({
                                "name": attr.get("Description"),
                                "ba_ref": attr.get("FeatureID"),
                                "create_variant": "no_variant"
                            })

                    # Create attribute res
                    val = ""
                    if attr.get("LogicalValue") != None:
                        val = "Ja" if attr.get("LogicalValue") else "Nee"
                    if attr.get("NumericValue") != None:
                        val = str(attr.get("NumericValue"))
                    if attr.get("RangeLowerValue") != None:
                        val = str(attr.get("RangeLowerValue")) + " - " + str(attr.get("RangeUpperValue"))
                    if attr.get("ValueDescription") != None:
                        val = str(attr.get("ValueDescription"))

                    value = self.env['product.attribute.value'].sudo().search([
                        ("attribute_id", "=", res.id),
                        ("name", "=", val)
                    ])
                    if not value:
                        value = self.env["product.attribute.value"].sudo().create({
                            "attribute_id": res.id,
                            "name": val,
                        })
                    attr_list.append(
                        (0, 0, {
                            'attribute_id': res.id,
                            'value_ids': [(6, 0, [value.id])]
                        })
                    )
                name = product.get("Description")
                if product.get('Model' ,""):
                    name += " " + product.get('Model' ,"")
                if product.get('Version', ""):
                    name += " " + product.get('Version', "")

                pricing = {}
                if self.pricelist_partner_id:
                    pricing = self.get_prices(product.get("GTIN"))

                template = {
                    "name": product.get("Description"),
                    "description": product.get("Description"),
                    "description_sale": product.get("LongDescription"),
                    "weight": product.get("WeightQuantity"),
                    "weight_uom_name": product.get("WeightMeasureUnitDescription"),
                    "barcode": product.get("GTIN"),
                    "detailed_type": "product",
                    "ba_ref": product.get("Id"),
                    'attribute_line_ids': attr_list,
                    "default_code": product.get("Productcode"),
                    "list_price": pricing.get("sale_price", 0),
                    "standard_price": pricing.get("purchase_price", 0),
                }
                if thumbnail:
                    template['image_1920'] = thumbnail
                # add new product
                self.env["product.template"].sudo().create(template)

    @staticmethod
    def test_api(endpoint):
        """
        Does a get request to an endpoint of choice and returns the json response
        """
        r = requests.get(url=endpoint)
        data = r.json()
        return data

    def request_access(self):
        """
        Gets the authorization from the 2ba auth server using the supplied username and password.
        """
        r = requests.post(
            url=self.authUrl,
            data={
                "grant_type": "password",
                "username": self.env.ref('bev_2ba_connector.ba_importer_username').sudo().value,
                "password": self.env.ref('bev_2ba_connector.ba_importer_password').sudo().value,
                "client_id": self.env.ref('bev_2ba_connector.ba_importer_client_id').sudo().value,
                "client_secret": self.env.ref('bev_2ba_connector.ba_importer_client_secret').sudo().value,
            }
        )
        res = r.json()

        if res.get("error"):
            raise AccessError(res.get("error"))

        self.env.ref('bev_2ba_connector.ba_importer_authorization_code').sudo().value = res['access_token']
        self.env.ref('bev_2ba_connector.ba_importer_refresh_token').sudo().value = res['refresh_token']
        expire = datetime.timestamp(datetime.now() + timedelta(seconds=res['expires_in'] - 100))
        self.env.ref('bev_2ba_connector.ba_importer_authorization_expire').sudo().value = expire

    def refresh_access(self):
        """
        Gets the authorization from the 2ba auth server using the refresh token.
        has a fallback to the password method. when the refresh token is invalid.
        """
        r = requests.post(
            url=self.authUrl,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.env.ref('bev_2ba_connector.ba_importer_refresh_token').sudo().value,
                "client_id": self.env.ref('bev_2ba_connector.ba_importer_client_id').sudo().value,
                "client_secret": self.env.ref('bev_2ba_connector.ba_importer_client_secret').sudo().value,
            }
        )
        res = r.json()

        if res.get("error"):
            if res.get("error") == 'invalid_grant':
                return self.request_access()

            raise AccessError(res.get("error"))

        self.env.ref('bev_2ba_connector.ba_importer_authorization_code').sudo().value = res.get("access_token")
        self.env.ref('bev_2ba_connector.ba_importer_refresh_token').sudo().value = res.get("refresh_token")
        expire = datetime.timestamp(datetime.now() + timedelta(seconds=res.get("expires_in") - 100))
        self.env.ref('bev_2ba_connector.ba_importer_authorization_expire').sudo().value = expire

    def get_product_by_gtin(self, gtin):
        """
        Retrives the product from 2ba api and returns a json formatted product
        """
        r = requests.get(url=self.baseUrl + "/json/Product/DetailsForProduct", params={
            "gtin": gtin
        },
                         headers={
                             "Authorization": "Bearer " + self.env.ref(
                                 'bev_2ba_connector.ba_importer_authorization_code').sudo().value
                         })

        return r.json()

    def get_product_thumbnail(self, gln, productcode):
        """
        Retrives the product thumbnail from 2ba api and returns a base64 encoded image

        """

        r = requests.get(url=self.baseUrl + "/json/Thumbnail/product", params={
            "gln": gln,
            "productcode": productcode
        },
                         headers={
                             "Authorization": "Bearer " + self.env.ref(
                                 'bev_2ba_connector.ba_importer_authorization_code').sudo().value
                         })
        if r.status_code != 200:
            return False
        return b64encode(r.content).decode("utf-8")

    def get_prices(self, gln):
        """
        Retrives the product thumbnail from 2ba api and returns a base64 encoded image

        """

        # Get supplier
        if not self.pricelist_partner_id.pricelist_csv:
            raise UserError("Partner has no pricelist")
        if not self.pricelist_partner_id.column_gln:
            raise UserError("Partner has no Column for GLN")
        csv_data = b64decode(self.pricelist_partner_id.pricelist_csv)
        data_file = io.StringIO(csv_data.decode("utf-8"))
        data_file.seek(0)
        csv_reader = csv.reader(data_file, delimiter=',')
        for row in csv_reader:
            column_gln = str(row[self.pricelist_partner_id.column_gln])
            if len(column_gln) == 13:
                column_gln = "0" + column_gln
            if str(gln) == column_gln:
                obj = {}
                if self.pricelist_partner_id.column_sale_price:
                    obj['sale_price'] = row[self.pricelist_partner_id.column_sale_price - 1]
                if self.pricelist_partner_id.column_purchase_price:
                    obj['purchase_price'] = row[self.pricelist_partner_id.column_purchase_price - 1]
                return obj
        return {}

    def _get_product_attributes(self, gtin):
        r = requests.get(url=self.baseUrl + "/json/Product/DetailsByGtinA", params={
            "gtin": gtin,
            "includeFeatures": "true"
        },
                         headers={
                             "Authorization": "Bearer " + self.env.ref(
                                 'bev_2ba_connector.ba_importer_authorization_code').sudo().value
                         })

        return r.json()
