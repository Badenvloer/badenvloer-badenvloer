# Copyright 2018 ACSONE SA/NV
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

{
    "name": "2ba Importer",
    "summary": """
        Addon for importing 2ba products""",
    "version": "16.0.1.0.0",
    "license": "LGPL-3",
    "author": "WeSolved BV",
    "sequence": -5,
    "maintainers": ["WeSolved BV"],
    "website": "https://wesolved.com",
    "depends": ["stock"],
    "application": True,
    "data": [
        'data/ir_config_parameter.xml'
        'security/ir.model.access.csv',
        'wizard/ba_importer.xml',
    ],
    "demo": [],
    "external_dependencies": {
        "python": []
    },
    "installable": True,
}
