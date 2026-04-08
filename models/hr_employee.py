from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    attendance_policy_id = fields.Many2one(
        'hikvision.work.policy', 
        string="Attendance Policy",
        help="Defines work hours, tolerances, and overtime rules."
    )
