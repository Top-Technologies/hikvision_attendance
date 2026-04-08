from odoo import models, fields, api

class HikvisionPolicyAssignWizard(models.TransientModel):
    _name = 'hikvision.policy.assign.wizard'
    _description = 'Assign Attendance Policy'

    policy_id = fields.Many2one('hikvision.work.policy', string="Attendance Policy", required=True)
    employee_ids = fields.Many2many('hr.employee', string="Employees", default=lambda self: self.env.context.get('active_ids'))

    def action_assign(self):
        self.ensure_one()
        if self.employee_ids and self.policy_id:
            self.employee_ids.write({'attendance_policy_id': self.policy_id.id})
        return {'type': 'ir.actions.act_window_close'}
