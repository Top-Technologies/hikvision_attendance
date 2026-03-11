from odoo import models, fields, api
from datetime import date, timedelta

class HikvisionAttendanceDashboard(models.Model):
    _name = 'hikvision.attendance.dashboard'
    _description = 'Attendance Dashboard'

    name = fields.Char(string="Name", default="Attendance Dashboard")
    
    # --- Top KPIs ---
    total_employees = fields.Integer(compute='_compute_stats', string="Total Employees")
    attendance_rate = fields.Float(compute='_compute_stats', string="Attendance Rate %")
    late_rate = fields.Float(compute='_compute_stats', string="Late Rate %")
    
    # --- Weekly Comparison (Bar Charts) ---
    attendance_this_week = fields.Float(compute='_compute_stats', string="Attendance This Week")
    attendance_last_week = fields.Float(compute='_compute_stats', string="Attendance Last Week")
    late_this_week = fields.Integer(compute='_compute_stats', string="Late This Week")
    late_last_week = fields.Integer(compute='_compute_stats', string="Late Last Week")
    
    # --- Department Insights ---
    top_dept_present = fields.Char(compute='_compute_stats', string="Most Present Dept")
    top_dept_late = fields.Char(compute='_compute_stats', string="Most Late Dept")
    
    # --- Raw Counts (Hidden/Helper) ---
    active_employees = fields.Integer(compute='_compute_stats')
    present_today = fields.Integer(compute='_compute_stats')
    late_today = fields.Integer(compute='_compute_stats')
    absent_today = fields.Integer(compute='_compute_stats')
    on_time_today = fields.Integer(compute='_compute_stats')
    leave_early_today = fields.Integer(compute='_compute_stats')
    overtime_today = fields.Integer(compute='_compute_stats')

    def _compute_stats(self):
        today = date.today()
        # Date ranges for weekly comparison
        start_this_week = today - timedelta(days=today.weekday())
        start_last_week = start_this_week - timedelta(days=7)
        end_last_week = start_this_week - timedelta(days=1)
        
        Employee = self.env['hr.employee']
        Attendance = self.env['hikvision.attendance']
        Department = self.env['hr.department']
        
        # 1. Base Counts
        total_count = Employee.search_count([])
        active_count = Employee.search_count([('active', '=', True)])
        if active_count == 0: active_count = 1 # Avoid div by zero
        
        daily_records = Attendance.search([('date', '=', today)])
        present_count = len(set(daily_records.mapped('employee_id').ids))
        late_count = Attendance.search_count([('date', '=', today), ('is_late', '=', True)])
        
        # 2. Rates
        att_rate = (present_count / active_count) * 100
        l_rate = (late_count / present_count * 100) if present_count > 0 else 0.0
        
        # 3. Weekly Comparisons
        # This Week
        this_week_recs = Attendance.search([('date', '>=', start_this_week), ('date', '<=', today)])
        # Approx avg presence per day this week? Or total count? Image shows "Attendance %".
        # Let's simple avg of daily mapped employee counts vs active
        # Easier: Count records / (Active * Days so far)
        days_so_far = (today - start_this_week).days + 1
        possible_attendance = active_count * days_so_far
        if possible_attendance > 0:
            att_this_week_pct = (len(this_week_recs) / possible_attendance) * 100
        else:
            att_this_week_pct = 0.0
            
        late_this_week_count = Attendance.search_count([('date', '>=', start_this_week), ('date', '<=', today), ('is_late', '=', True)])

        # Last Week
        last_week_recs = Attendance.search([('date', '>=', start_last_week), ('date', '<=', end_last_week)])
        possible_att_last = active_count * 7 # Assuming 7 days or 5? 
        # Making simple assumption:
        if possible_att_last > 0:
            att_last_week_pct = (len(last_week_recs) / possible_att_last) * 100
        else:
            att_last_week_pct = 0.0
            
        late_last_week_count = Attendance.search_count([('date', '>=', start_last_week), ('date', '<=', end_last_week), ('is_late', '=', True)])

        # 4. Leading Departments (Simple heuristics)
        # Most Present: Dept with highest count in daily_records
        # Group by dept manually
        dept_counts = {}
        top_present_name = "N/A"
        if daily_records:
            for r in daily_records:
                dname = r.employee_id.department_id.name or "Unknown"
                dept_counts[dname] = dept_counts.get(dname, 0) + 1
            if dept_counts:
                top_present_name = max(dept_counts, key=dept_counts.get)
        
        # Most Late:
        late_recs = daily_records.filtered(lambda x: x.is_late)
        late_dept_counts = {}
        top_late_name = "N/A"
        if late_recs:
             for r in late_recs:
                dname = r.employee_id.department_id.name or "Unknown"
                late_dept_counts[dname] = late_dept_counts.get(dname, 0) + 1
             if late_dept_counts:
                 top_late_name = max(late_dept_counts, key=late_dept_counts.get)

        for record in self:
            record.total_employees = active_count # Chart says "Current Enrollment" which usually means Active
            record.active_employees = active_count
            record.present_today = present_count
            record.absent_today = max(0, active_count - present_count)
            record.late_today = late_count
            record.on_time_today = max(0, present_count - late_count)
            record.leave_early_today = Attendance.search_count([('date', '=', today), ('is_early_leave', '=', True)])
            record.overtime_today = Attendance.search_count([('date', '=', today), ('overtime_hours', '>', 0)])
            
            record.attendance_rate = att_rate
            record.late_rate = l_rate
            
            record.attendance_this_week = att_this_week_pct
            record.attendance_last_week = att_last_week_pct
            record.late_this_week = late_this_week_count
            record.late_last_week = late_last_week_count
            
            record.top_dept_present = top_present_name
            record.top_dept_late = top_late_name

    # --- Actions ---
    def action_view_present(self):
        return {
            'name': 'Employees Present Today',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('date', '=', date.today())],
        }

    def action_view_absent(self):
        today = date.today()
        present_ids = self.env['hikvision.attendance'].search([('date', '=', today)]).mapped('employee_id').ids
        return {
            'name': 'Employees Not Logged In Today',
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'view_mode': 'list,form',
            'domain': [('id', 'not in', present_ids), ('active', '=', True)],
        }

    def action_view_late(self):
        return {
            'name': 'Late Today',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('date', '=', date.today()), ('is_late', '=', True)],
        }

    def action_view_early_leave(self):
        return {
            'name': 'Employees Left Early',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('date', '=', date.today()), ('is_early_leave', '=', True)],
        }

    def action_view_overtime(self):
        return {
            'name': 'Employees Performing Overtime',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('date', '=', date.today()), ('overtime_hours', '>', 0)],
        }
    
    def action_view_on_time(self):
        return {
            'name': 'Employees On Time Today',
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': [('date', '=', date.today()), ('is_late', '=', False)],
        }
