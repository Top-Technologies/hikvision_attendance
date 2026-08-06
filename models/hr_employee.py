from odoo import models, fields, api
import pytz

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    attendance_policy_id = fields.Many2one(
        'hikvision.work.policy', 
        string="Attendance Policy",
        help="Defines work hours, tolerances, and overtime rules."
    )
    
    # One2many to hikvision attendance records (renamed to avoid conflict with hr_attendance)
    hikvision_attendance_ids = fields.One2many(
        'hikvision.attendance', 
        'employee_id', 
        string='Hikvision Attendance Records'
    )
    
    # Absenteeism Statistics (Late minutes & Absent days)
    current_month_late_minutes = fields.Integer(
        string="Late Minutes (Current Month)",
        compute="_compute_absent_stats",
    )
    total_late_minutes = fields.Integer(
        string="Late Minutes (Total)",
        compute="_compute_absent_stats",
    )
    current_month_absent_hours = fields.Float(
        string="Absent Hours (Current Month)",
        compute="_compute_absent_stats",
    )
    total_absent_hours = fields.Float(
        string="Absent Hours (Total)",
        compute="_compute_absent_stats",
    )
    current_month_total_absent_hours = fields.Float(
        string="Total Absent Hours (Current Month)",
        compute="_compute_absent_stats",
    )
    total_total_absent_hours = fields.Float(
        string="Total Absent Hours (Total)",
        compute="_compute_absent_stats",
    )
    current_month_absent_days = fields.Integer(
        string="Absent Days (Current Month)",
        compute="_compute_absent_stats",
    )
    total_absent_days = fields.Integer(
        string="Absent Days (Total)",
        compute="_compute_absent_stats",
    )
    
    # Current Month OT Statistics
    current_month_ot_hours = fields.Float(
        string="Current Month OT Hours",
        compute='_compute_overtime_stats',
        help="Total overtime hours for current month"
    )
    
    current_month_ot_payable = fields.Float(
        string="Current Month Payable OT",
        compute='_compute_overtime_stats',
        help="Payable overtime hours for current month (weighted by rates)"
    )
    
    pending_ot_requests = fields.Integer(
        string="Pending OT Requests",
        compute='_compute_overtime_stats',
        help="Number of overtime requests pending approval"
    )
    
    # Historical Statistics
    total_ot_hours = fields.Float(
        string="Total OT Hours",
        compute='_compute_overtime_stats',
        help="Total overtime hours (all time)"
    )
    
    total_ot_payable = fields.Float(
        string="Total Payable OT",
        compute='_compute_overtime_stats',
        help="Total payable overtime hours (all time)"
    )
    
    avg_monthly_ot = fields.Float(
        string="Avg Monthly OT",
        compute='_compute_overtime_stats',
        help="Average monthly overtime hours"
    )
    
    # Breakdown by Day Type (Current Month)
    ot_weekday_hours = fields.Float(
        string="Weekday OT",
        compute='_compute_overtime_breakdown',
        help="Overtime on weekdays (Mon-Fri) this month"
    )
    
    ot_saturday_hours = fields.Float(
        string="Saturday OT",
        compute='_compute_overtime_breakdown',
        help="Overtime on Saturdays this month"
    )
    
    ot_sunday_hours = fields.Float(
        string="Sunday OT",
        compute='_compute_overtime_breakdown',
        help="Overtime on Sundays this month"
    )
    
    ot_holiday_hours = fields.Float(
        string="Holiday OT",
        compute='_compute_overtime_breakdown',
        help="Overtime on public holidays this month"
    )
    
    ot_night_hours = fields.Float(
        string="Night Shift OT",
        compute='_compute_overtime_breakdown',
        help="Overtime during night hours this month"
    )
    
    @api.depends('hikvision_attendance_ids.overtime_hours', 'hikvision_attendance_ids.ot_payable_hours', 
                 'hikvision_attendance_ids.approval_state', 'hikvision_attendance_ids.date')
    def _compute_overtime_stats(self):
        """Compute overtime statistics for each employee."""
        for employee in self:
            # Get date ranges
            today = fields.Date.today()
            start_of_month = today.replace(day=1)
            
            # Current month records
            current_month_recs = employee.hikvision_attendance_ids.filtered(
                lambda r: r.date and r.date >= start_of_month and r.overtime_hours > 0
            )
            
            # All OT records
            all_ot_recs = employee.hikvision_attendance_ids.filtered(lambda r: r.overtime_hours > 0)
            
            # Current month stats
            employee.current_month_ot_hours = sum(current_month_recs.mapped('overtime_hours'))
            employee.current_month_ot_payable = sum(current_month_recs.mapped('ot_payable_hours'))
            employee.pending_ot_requests = len(current_month_recs.filtered(
                lambda r: r.approval_state in ('to_approve', 'second_approval')
            ))
            
            # Historical stats
            employee.total_ot_hours = sum(all_ot_recs.mapped('overtime_hours'))
            employee.total_ot_payable = sum(all_ot_recs.mapped('ot_payable_hours'))
            
            # Calculate average monthly OT
            if all_ot_recs:
                dates = all_ot_recs.mapped('date')
                if dates:
                    min_date = min(dates)
                    # Calculate number of months
                    months = ((today.year - min_date.year) * 12 + 
                             (today.month - min_date.month) + 1)
                    employee.avg_monthly_ot = employee.total_ot_hours / months if months > 0 else 0
                else:
                    employee.avg_monthly_ot = 0
            else:
                employee.avg_monthly_ot = 0
    
    @api.depends('hikvision_attendance_ids.overtime_hours', 'hikvision_attendance_ids.date')
    def _compute_overtime_breakdown(self):
        """Compute overtime breakdown by day type for current month."""
        for employee in self:
            today = fields.Date.today()
            start_of_month = today.replace(day=1)
            
            # Get current month OT records
            current_month_recs = employee.hikvision_attendance_ids.filtered(
                lambda r: r.date and r.date >= start_of_month and r.overtime_hours > 0
            )
            
            weekday_ot = 0.0
            saturday_ot = 0.0
            sunday_ot = 0.0
            holiday_ot = 0.0
            night_ot = 0.0
            
            for rec in current_month_recs:
                if not rec.date:
                    continue
                    
                weekday = rec.date.weekday()  # 0=Monday, 6=Sunday
                
                # Check if it's a holiday
                is_holiday = False
                if employee.resource_calendar_id:
                    leaves = employee.resource_calendar_id.global_leave_ids
                    for leave in leaves:
                        if leave.date_from.date() <= rec.date <= leave.date_to.date():
                            is_holiday = True
                            break
                
                if is_holiday:
                    holiday_ot += rec.overtime_hours
                elif weekday == 6:  # Sunday
                    sunday_ot += rec.overtime_hours
                elif weekday == 5:  # Saturday
                    saturday_ot += rec.overtime_hours
                else:  # Monday-Friday
                    weekday_ot += rec.overtime_hours
                
                # Night hours estimation (if OT ended after 22:00 or before 06:00)
                # This is a simplified calculation - actual night hours would need more detail
                if rec.last_check_out:
                    import pytz
                    policy = employee.attendance_policy_id
                    tz_name = (policy.tz if policy else None) or employee.tz or 'UTC'
                    try:
                        local_tz = pytz.timezone(tz_name)
                    except:
                        local_tz = pytz.UTC
                    
                    checkout_local = rec.last_check_out.replace(tzinfo=pytz.UTC).astimezone(local_tz)
                    hour = checkout_local.hour
                    
                    # If checkout is between 22:00-06:00, assume some night hours
                    if hour >= 22 or hour < 6:
                        # Rough estimate: assume half of OT was during night
                        night_ot += rec.overtime_hours * 0.5
            
            employee.ot_weekday_hours = weekday_ot
            employee.ot_saturday_hours = saturday_ot
            employee.ot_sunday_hours = sunday_ot
            employee.ot_holiday_hours = holiday_ot
            employee.ot_night_hours = night_ot
    
    def action_view_overtime_records(self):
        """Open overtime records for this employee."""
        self.ensure_one()
        return {
            'name': f'Overtime Records - {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id), ('overtime_hours', '>', 0)],
            'context': {'default_employee_id': self.id},
        }

    @api.depends('hikvision_attendance_ids.late_minutes', 'hikvision_attendance_ids.absent_hours', 'hikvision_attendance_ids.attendance_status', 'hikvision_attendance_ids.date')
    def _compute_absent_stats(self):
        for employee in self:
            today = fields.Date.today()
            start_of_month = today.replace(day=1)
            
            # Current month records
            current_month_recs = employee.hikvision_attendance_ids.filtered(
                lambda r: r.date and r.date >= start_of_month
            )
            
            # All records
            all_recs = employee.hikvision_attendance_ids
            
            # 1. Late Minutes
            employee.current_month_late_minutes = sum(current_month_recs.mapped('late_minutes'))
            employee.total_late_minutes = sum(all_recs.mapped('late_minutes'))
            
            # 2. Absent Hours (from absent days only)
            employee.current_month_absent_hours = sum(current_month_recs.mapped('absent_hours'))
            employee.total_absent_hours = sum(all_recs.mapped('absent_hours'))
            
            # 3. Total Absent Hours = Absent Hours + (Late Minutes / 60.0)
            employee.current_month_total_absent_hours = employee.current_month_absent_hours + (employee.current_month_late_minutes / 60.0)
            employee.total_total_absent_hours = employee.total_absent_hours + (employee.total_late_minutes / 60.0)
            
            # 4. Absent Days
            employee.current_month_absent_days = len(current_month_recs.filtered(lambda r: r.attendance_status == 'absent'))
            employee.total_absent_days = len(all_recs.filtered(lambda r: r.attendance_status == 'absent'))

