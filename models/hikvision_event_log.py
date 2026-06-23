from odoo import models, fields, api
from datetime import timedelta

class HikvisionEventLog(models.Model):
    _name = 'hikvision.event.log'
    _description = 'Hikvision Event Log'
    _order = 'timestamp desc'

    device_id = fields.Many2one('hikvision.device', string="Device", required=True)
    timestamp = fields.Datetime(string="Timestamp", required=True)
    event_type = fields.Char(string="Event Type")
    employee_no = fields.Char(string="Employee No")
    employee_id = fields.Many2one('hr.employee', string="Employee")
    company_id = fields.Many2one('res.company', string='Company', related='employee_id.company_id', store=True)
    raw_data = fields.Text(string="Raw Data")
    
    # Computed fields for filtering
    event_date = fields.Date(string="Event Date", compute='_compute_event_date', store=True)
    
    @api.depends('timestamp')
    def _compute_event_date(self):
        for record in self:
            if record.timestamp:
                record.event_date = record.timestamp.date()
            else:
                record.event_date = False
