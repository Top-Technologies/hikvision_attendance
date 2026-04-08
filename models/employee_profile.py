from odoo import models, fields, api
from datetime import datetime, timedelta


class HikvisionEmployeeProfile(models.Model):
    _name = 'hikvision.employee.profile'
    _description = 'Employee Attendance Profile'
    _auto = False  # This is a SQL view (virtual model)
    _order = 'employee_name'

    employee_id = fields.Many2one('hr.employee', string="Employee", readonly=True)
    employee_name = fields.Char(string="Name", readonly=True)
    department_id = fields.Many2one('hr.department', string="Department", readonly=True)
    job_id = fields.Many2one('hr.job', string="Job Position", readonly=True)
    company_id = fields.Many2one('res.company', string="Company", readonly=True)
    
    # Work hours - Current Period
    today_hours = fields.Float(string="Today", readonly=True)
    week_hours = fields.Float(string="This Week", readonly=True)
    month_hours = fields.Float(string="This Month", readonly=True)
    
    # Work hours - Historical
    last_week_hours = fields.Float(string="Last Week", readonly=True)
    last_month_hours = fields.Float(string="Last Month", readonly=True)
    
    # Attendance counts - Current Month
    present_days = fields.Integer(string="Present Days", readonly=True)
    absent_days = fields.Integer(string="Absent Days", readonly=True)
    incomplete_days = fields.Integer(string="Incomplete Days", readonly=True)
    late_days = fields.Integer(string="Late Days", readonly=True)
    early_leave_days = fields.Integer(string="Early Leave Days", readonly=True)
    
    # Historical counts (All time)
    total_absent_history = fields.Integer(string="Total Absences", readonly=True)
    total_late_history = fields.Integer(string="Total Late", readonly=True)
    total_early_leave_history = fields.Integer(string="Total Early Leave", readonly=True)
    
    # Averages
    avg_daily_hours = fields.Float(string="Avg Daily Hours", readonly=True)
    
    def init(self):
        """Create SQL view for employee attendance profile"""
        self.env.cr.execute("""
            DROP VIEW IF EXISTS hikvision_employee_profile;
            CREATE OR REPLACE VIEW hikvision_employee_profile AS (
                SELECT
                    e.id as id,
                    e.id as employee_id,
                    e.name as employee_name,
                    e.department_id as department_id,
                    e.job_id as job_id,
                    e.company_id as company_id,
                    
                    -- Today's hours
                    COALESCE((
                        SELECT SUM(a.total_hours)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date = CURRENT_DATE
                    ), 0) as today_hours,
                    
                    -- This week's hours
                    COALESCE((
                        SELECT SUM(a.total_hours)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('week', CURRENT_DATE)
                        AND a.date <= CURRENT_DATE
                    ), 0) as week_hours,
                    
                    -- This month's hours
                    COALESCE((
                        SELECT SUM(a.total_hours)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('month', CURRENT_DATE)
                        AND a.date <= CURRENT_DATE
                    ), 0) as month_hours,
                    
                    -- Last week's hours
                    COALESCE((
                        SELECT SUM(a.total_hours)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('week', CURRENT_DATE) - INTERVAL '7 days'
                        AND a.date < date_trunc('week', CURRENT_DATE)
                    ), 0) as last_week_hours,
                    
                    -- Last month's hours
                    COALESCE((
                        SELECT SUM(a.total_hours)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month'
                        AND a.date < date_trunc('month', CURRENT_DATE)
                    ), 0) as last_month_hours,
                    
                    -- Present days this month
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('month', CURRENT_DATE)
                        AND a.attendance_status = 'present'
                    ), 0) as present_days,
                    
                    -- Absent days this month
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('month', CURRENT_DATE)
                        AND a.attendance_status = 'absent'
                    ), 0) as absent_days,
                    
                    -- Incomplete days this month
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('month', CURRENT_DATE)
                        AND a.attendance_status = 'incomplete'
                    ), 0) as incomplete_days,
                    
                    -- Late days this month
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('month', CURRENT_DATE)
                        AND a.is_late = true
                    ), 0) as late_days,
                    
                    -- Early leave days this month
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= date_trunc('month', CURRENT_DATE)
                        AND a.is_early_leave = true
                    ), 0) as early_leave_days,
                    
                    -- Total absent history (all time)
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.attendance_status = 'absent'
                    ), 0) as total_absent_history,
                    
                    -- Total late history (all time)
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.is_late = true
                    ), 0) as total_late_history,
                    
                    -- Total early leave history (all time)
                    COALESCE((
                        SELECT COUNT(*)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.is_early_leave = true
                    ), 0) as total_early_leave_history,
                    
                    -- Average daily hours (last 30 days)
                    COALESCE((
                        SELECT AVG(a.total_hours)
                        FROM hikvision_attendance a
                        WHERE a.employee_id = e.id
                        AND a.date >= CURRENT_DATE - INTERVAL '30 days'
                        AND a.total_hours > 0
                    ), 0) as avg_daily_hours
                    
                FROM hr_employee e
                WHERE e.active = true
            )
        """)

    def action_view_attendance(self):
        """View attendance records for this employee"""
        self.ensure_one()
        return {
            'name': f'Attendance - {self.employee_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.employee_id.id)],
            'context': {'default_employee_id': self.employee_id.id},
        }

    def action_view_late_history(self):
        """View late arrival history for this employee"""
        self.ensure_one()
        return {
            'name': f'Late Arrivals - {self.employee_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.employee_id.id), ('is_late', '=', True)],
        }

    def action_view_absent_history(self):
        """View absent history for this employee"""
        self.ensure_one()
        return {
            'name': f'Absences - {self.employee_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.employee_id.id), ('attendance_status', '=', 'absent')],
        }

    def action_view_early_leave_history(self):
        """View early leave history for this employee"""
        self.ensure_one()
        return {
            'name': f'Early Leaves - {self.employee_name}',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.employee_id.id), ('is_early_leave', '=', True)],
        }
