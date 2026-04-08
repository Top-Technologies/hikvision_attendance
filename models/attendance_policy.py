from odoo import models, fields, api
from odoo.addons.base.models.res_partner import _tz_get
from odoo.exceptions import ValidationError

class HikvisionWorkPolicy(models.Model):
    _name = 'hikvision.work.policy'
    _description = 'Work & Attendance Policy'

    name = fields.Char(string="Policy Name", required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    # Work Schedule
    work_start = fields.Float(string="Work Start Time", default=8.5, help="e.g. 8.5 for 08:30")
    work_end = fields.Float(string="Work End Time", default=17.5, help="e.g. 17.5 for 17:30")
    work_end_saturday = fields.Float(string="Saturday End Time", default=13.0, help="e.g. 13.0 for 13:00")
    tz = fields.Selection(_tz_get, string="Timezone", default='Africa/Addis_Ababa', required=True, help="Reference timezone for attendance calculations. Overrides employee timezone.")
    lunch_duration = fields.Float(string="Lunch Duration (min)", default=60.0, help="Deducted from total minutes to get working minutes")
    
    # Overtime Rules
    ot_apply = fields.Boolean(string="Apply Overtime", default=False)
    ot_start_time = fields.Float(string="Overtime Start Time", default=17.516, help="Time after which OT counts (e.g. 17:31 = 17.516)")
    ot_end_limit = fields.Float(string="Overtime End Limit", default=6.0, help="OT counts until this time on the next day (e.g. 6.0 for 06:00 AM)")
    
    # Advanced Overtime Rates
    rate_weekday = fields.Float(string="Weekday Rate", default=1.0)
    rate_saturday = fields.Float(string="Saturday Rate", default=1.0)
    rate_saturday_afternoon = fields.Float(string="Sat Afternoon Rate", default=1.5)
    saturday_afternoon_start = fields.Float(string="Sat Afternoon Start", default=13.0, help="Time after which Saturday Afternoon rate applies")
    rate_sunday = fields.Float(string="Sunday Rate", default=2.0)
    rate_holiday = fields.Float(string="Holiday Rate", default=2.0)
    
    # Night Shift
    rate_night = fields.Float(string="Night Rate", default=1.5)
    night_start = fields.Float(string="Night Start", default=22.0)
    night_end = fields.Float(string="Night End", default=6.0)
    
    # Tolerances
    late_tolerance = fields.Integer(string="Late Tolerance (minutes)", default=15, help="Minutes after start time before marked Late")
    early_leave_tolerance = fields.Integer(string="Early Leave Tolerance (minutes)", default=30, help="Minutes before end time considered Early Leave")
    
    ignore_late_early = fields.Boolean(string="Ignore Late/Early Flags", default=False, help="For Flexible shifts where fixed start/end times don't apply")
    
    employee_ids = fields.One2many('hr.employee', 'attendance_policy_id', string="Employees")

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Policy name must be unique!')
    ]
