# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class HikvisionPayrollSummary(models.Model):
    _name = 'hikvision.payroll.summary'
    _description = 'Payroll Attendance Summary'
    _order = 'month desc, employee_id'
    _rec_name = 'display_name'

    # Identity
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        compute='_compute_department_id', store=True
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        related='employee_id.company_id', store=True
    )
    month = fields.Date(string='Month', required=True, index=True)
    month_display = fields.Char(string='Period', compute='_compute_month_display', store=True)
    display_name = fields.Char(compute='_compute_display_name_field', store=False)

    # Regular Attendance
    working_days = fields.Integer(string='Working Days')
    present_days = fields.Integer(string='Present Days')
    absent_days = fields.Integer(string='Absent Days', compute='_compute_absent_days', store=True)
    regular_hours = fields.Float(string='Regular Working Hours', digits=(6, 2))

    # Overtime Breakdown (Hours)
    weekday_ot_hours = fields.Float(string='Weekday OT Hours', digits=(6, 2))
    saturday_ot_hours = fields.Float(string='Saturday OT Hours', digits=(6, 2))
    sunday_ot_hours = fields.Float(string='Sunday OT Hours', digits=(6, 2))
    holiday_ot_hours = fields.Float(string='Holiday OT Hours', digits=(6, 2))
    total_ot_hours = fields.Float(string='Total OT Hours', digits=(6, 2))
    total_ot_payable_hours = fields.Float(string='Payable OT Hours', digits=(6, 2),
                                           help='Weighted by policy rates')

    # Deductions (Minutes → for payroll integration)
    late_deduction_minutes = fields.Integer(string='Late Deduction (min)')
    early_deduction_minutes = fields.Integer(string='Early Leave Deduction (min)')
    total_deduction_minutes = fields.Integer(
        string='Total Deduction (min)',
        compute='_compute_total_deduction', store=True
    )

    _sql_constraints = [
        ('emp_month_uniq', 'unique(employee_id, month)',
         'Payroll summary already exists for this employee and month.')
    ]

    @api.depends('employee_id', 'employee_id.department_id')
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.employee_id.department_id if rec.employee_id else False

    @api.depends('month')
    def _compute_month_display(self):
        for rec in self:
            rec.month_display = rec.month.strftime('%B %Y') if rec.month else ''

    @api.depends('present_days', 'working_days')
    def _compute_absent_days(self):
        for rec in self:
            rec.absent_days = max(0, rec.working_days - rec.present_days)

    @api.depends('late_deduction_minutes', 'early_deduction_minutes')
    def _compute_total_deduction(self):
        for rec in self:
            rec.total_deduction_minutes = rec.late_deduction_minutes + rec.early_deduction_minutes

    @api.depends('employee_id', 'month')
    def _compute_display_name_field(self):
        for rec in self:
            emp = rec.employee_id.name if rec.employee_id else 'Unknown'
            month = rec.month.strftime('%B %Y') if rec.month else ''
            rec.display_name = f'{emp} — {month}'

    @api.model
    def action_generate(self, month, employee_ids=None, department_ids=None):
        """
        Generate payroll attendance summaries for the given month.
        """
        if not month:
            return

        month_start = month.replace(day=1) if hasattr(month, 'replace') else date.fromisoformat(str(month))
        month_start = month_start.replace(day=1)
        next_month = month_start + relativedelta(months=1)
        month_end = next_month - timedelta(days=1)

        Employee = self.env['hr.employee']
        emp_domain = [('active', '=', True)]
        if employee_ids:
            emp_domain.append(('id', 'in', employee_ids))
        if department_ids:
            emp_domain.append(('department_id', 'in', department_ids))
        employees = Employee.search(emp_domain)

        if not employees:
            return

        # Calculate working days (Mon–Sat)
        working_days_count = 0
        d = month_start
        while d <= month_end:
            if d.weekday() < 6:
                working_days_count += 1
            d += timedelta(days=1)

        # Delete existing
        self.search([
            ('month', '=', month_start),
            ('employee_id', 'in', employees.ids),
        ]).unlink()

        Attendance = self.env['hikvision.attendance']
        vals_list = []

        for emp in employees:
            records = Attendance.search([
                ('employee_id', '=', emp.id),
                ('date', '>=', month_start),
                ('date', '<=', month_end),
            ])

            present_recs = records.filtered(lambda r: r.attendance_status == 'present')

            # OT breakdown by day type
            weekday_ot = saturday_ot = sunday_ot = holiday_ot = 0.0

            for rec in records:
                if not rec.date or rec.overtime_hours <= 0:
                    continue
                weekday = rec.date.weekday()
                # Check holiday
                is_holiday = False
                if emp.resource_calendar_id:
                    for leave in emp.resource_calendar_id.global_leave_ids:
                        if leave.date_from.date() <= rec.date <= leave.date_to.date():
                            is_holiday = True
                            break

                if is_holiday:
                    holiday_ot += rec.overtime_hours
                elif weekday == 6:
                    sunday_ot += rec.overtime_hours
                elif weekday == 5:
                    saturday_ot += rec.overtime_hours
                else:
                    weekday_ot += rec.overtime_hours

            total_ot = sum(records.mapped('overtime_hours'))
            total_ot_payable = sum(records.mapped('ot_payable_hours'))
            regular_hrs = sum(r.working_minutes for r in present_recs) / 60.0

            vals_list.append({
                'employee_id': emp.id,
                'month': month_start,
                'working_days': working_days_count,
                'present_days': len(present_recs),
                'regular_hours': round(regular_hrs, 2),
                'weekday_ot_hours': round(weekday_ot, 2),
                'saturday_ot_hours': round(saturday_ot, 2),
                'sunday_ot_hours': round(sunday_ot, 2),
                'holiday_ot_hours': round(holiday_ot, 2),
                'total_ot_hours': round(total_ot, 2),
                'total_ot_payable_hours': round(total_ot_payable, 2),
                'late_deduction_minutes': int(sum(records.mapped('late_minutes'))),
                'early_deduction_minutes': int(sum(records.mapped('early_leave_minutes'))),
            })

        if vals_list:
            self.create(vals_list)
            _logger.info(
                'Payroll Summary: Generated %d records for %s',
                len(vals_list), month_start.strftime('%B %Y')
            )

    # ========================================================================
    # PHASE 4: AUTOMATED CRON METHODS
    # ========================================================================

    @api.model
    def action_cron_generate_payroll(self):
        """
        Cron method: Generate payroll summary for previous month
        Runs on 1st of each month at 3 AM (after monthly summary generation)
        """
        try:
            # Get first day of previous month
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_month = first_of_this_month - timedelta(days=1)
            month_start = last_month.replace(day=1)
            
            _logger.info(f"[CRON] Generating payroll summary for {month_start.strftime('%B %Y')}")
            
            # Generate payroll summary for previous month
            self.action_generate(month=month_start)
            
            _logger.info(f"[CRON] Successfully generated payroll summary")
            return True
            
        except Exception as e:
            _logger.error(f"[CRON] Error generating payroll summary: {str(e)}")
            return False
