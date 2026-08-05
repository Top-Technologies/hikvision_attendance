# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class HikvisionMonthlySummary(models.Model):
    _name = 'hikvision.monthly.summary'
    _description = 'Monthly Attendance Summary'
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
    month = fields.Date(string='Month', required=True, index=True,
                        help='First day of the month')
    month_display = fields.Char(string='Month', compute='_compute_month_display', store=True)

    # Attendance Counts
    working_days = fields.Integer(string='Working Days', default=0)
    present_days = fields.Integer(string='Present Days', default=0)
    absent_days = fields.Integer(string='Absent Days', default=0,
                                  compute='_compute_absent_days', store=True)
    late_days = fields.Integer(string='Late Days', default=0)
    early_leave_days = fields.Integer(string='Early Leave Days', default=0)
    incomplete_days = fields.Integer(string='Missing Punch Days', default=0)

    # Hours
    total_hours = fields.Float(string='Total Hours', digits=(6, 2))
    working_minutes = fields.Integer(string='Total Working Minutes')
    overtime_hours = fields.Float(string='Overtime Hours', digits=(6, 2))
    ot_payable_hours = fields.Float(string='Payable OT Hours', digits=(6, 2))

    # Deduction Minutes
    late_minutes_total = fields.Integer(string='Total Late Minutes')
    early_leave_minutes_total = fields.Integer(string='Total Early Leave Minutes')

    # Rates
    attendance_rate = fields.Float(string='Attendance Rate %', digits=(5, 2))
    punctuality_rate = fields.Float(string='Punctuality Rate %', digits=(5, 2))

    display_name = fields.Char(compute='_compute_display_name_field', store=False)

    _sql_constraints = [
        ('emp_month_uniq', 'unique(employee_id, month)',
         'Monthly summary already exists for this employee and month. Delete it first to regenerate.')
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

    @api.depends('employee_id', 'month')
    def _compute_display_name_field(self):
        for rec in self:
            emp = rec.employee_id.name if rec.employee_id else 'Unknown'
            month = rec.month.strftime('%B %Y') if rec.month else ''
            rec.display_name = f'{emp} — {month}'

    @api.model
    def action_generate(self, month, employee_ids=None, department_ids=None):
        """
        Generate (or refresh) monthly summary records for the given month.
        Existing records are deleted and recreated.
        """
        if not month:
            return

        # Date range
        month_start = month.replace(day=1) if hasattr(month, 'replace') else date.fromisoformat(str(month))
        month_start = month_start.replace(day=1)
        next_month = month_start + relativedelta(months=1)
        month_end = next_month - timedelta(days=1)

        # Determine employees
        Employee = self.env['hr.employee']
        domain = [('active', '=', True)]
        if employee_ids:
            domain.append(('id', 'in', employee_ids))
        if department_ids:
            domain.append(('department_id', 'in', department_ids))
        employees = Employee.search(domain)

        if not employees:
            _logger.warning('Monthly Summary: No employees found for given filters.')
            return

        # Calculate working days in month (Mon–Sat, excluding Sundays)
        working_days_count = 0
        d = month_start
        while d <= month_end:
            if d.weekday() < 6:  # 0–5 = Mon–Sat
                working_days_count += 1
            d += timedelta(days=1)

        # Delete existing summaries for this month/employee set
        existing = self.search([
            ('month', '=', month_start),
            ('employee_id', 'in', employees.ids),
        ])
        existing.unlink()

        Attendance = self.env['hikvision.attendance']
        vals_list = []

        for emp in employees:
            records = Attendance.search([
                ('employee_id', '=', emp.id),
                ('date', '>=', month_start),
                ('date', '<=', month_end),
            ])

            present_recs = records.filtered(lambda r: r.attendance_status == 'present')
            incomplete_recs = records.filtered(lambda r: r.attendance_status == 'incomplete')
            late_recs = records.filtered(lambda r: r.is_late)
            early_recs = records.filtered(lambda r: r.is_early_leave)

            present_count = len(present_recs)
            total_hrs = sum(records.mapped('total_hours'))
            work_mins = sum(records.mapped('working_minutes'))
            ot_hrs = sum(records.mapped('overtime_hours'))
            ot_payable = sum(records.mapped('ot_payable_hours'))
            late_mins = sum(records.mapped('late_minutes'))
            early_mins = sum(records.mapped('early_leave_minutes'))

            att_rate = (present_count / working_days_count * 100) if working_days_count else 0.0
            punc_rate = ((present_count - len(late_recs)) / present_count * 100) if present_count else 0.0

            vals_list.append({
                'employee_id': emp.id,
                'month': month_start,
                'working_days': working_days_count,
                'present_days': present_count,
                'late_days': len(late_recs),
                'early_leave_days': len(early_recs),
                'incomplete_days': len(incomplete_recs),
                'total_hours': total_hrs,
                'working_minutes': work_mins,
                'overtime_hours': ot_hrs,
                'ot_payable_hours': ot_payable,
                'late_minutes_total': int(late_mins),
                'early_leave_minutes_total': int(early_mins),
                'attendance_rate': round(att_rate, 2),
                'punctuality_rate': round(punc_rate, 2),
            })

        if vals_list:
            self.create(vals_list)
            _logger.info('Monthly Summary: Generated %d records for %s', len(vals_list), month_start.strftime('%B %Y'))

    # ========================================================================
    # PHASE 4: AUTOMATED CRON METHODS
    # ========================================================================

    @api.model
    def action_cron_generate_yesterday(self):
        """
        Cron method: Generate summary for yesterday's date
        Runs daily at 1 AM to keep summaries up-to-date
        """
        try:
            yesterday = date.today() - timedelta(days=1)
            month_start = yesterday.replace(day=1)
            
            _logger.info(f"[CRON] Generating daily summary for {yesterday}")
            
            # Generate summary for the month containing yesterday
            self.action_generate(month=month_start)
            
            _logger.info(f"[CRON] Successfully generated daily summary")
            return True
            
        except Exception as e:
            _logger.error(f"[CRON] Error generating daily summary: {str(e)}")
            return False

    @api.model
    def action_cron_generate_monthly(self):
        """
        Cron method: Generate summary for previous month
        Runs on 1st of each month at 2 AM
        """
        try:
            # Get first day of previous month
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_month = first_of_this_month - timedelta(days=1)
            month_start = last_month.replace(day=1)
            
            _logger.info(f"[CRON] Generating monthly summary for {month_start.strftime('%B %Y')}")
            
            # Generate summary for previous month
            self.action_generate(month=month_start)
            
            _logger.info(f"[CRON] Successfully generated monthly summary")
            return True
            
        except Exception as e:
            _logger.error(f"[CRON] Error generating monthly summary: {str(e)}")
            return False

    @api.model
    def action_cron_email_monthly_reports(self):
        """
        Cron method: Email monthly reports to managers
        Runs on 2nd of each month at 9 AM
        """
        try:
            # Get first day of previous month
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_month = first_of_this_month - timedelta(days=1)
            month_start = last_month.replace(day=1)
            
            _logger.info(f"[CRON] Emailing monthly reports for {month_start.strftime('%B %Y')}")
            
            # Get all summaries for last month
            summaries = self.search([('month', '=', month_start)])
            
            if not summaries:
                _logger.warning("[CRON] No monthly summaries found to email")
                return False
            
            # Group by department
            dept_summaries = {}
            for summary in summaries:
                dept = summary.department_id
                if dept not in dept_summaries:
                    dept_summaries[dept] = []
                dept_summaries[dept].append(summary)
            
            # Email each department manager
            mail_template = self.env.ref('hikvision_attendance.email_template_monthly_report', 
                                        raise_if_not_found=False)
            
            if not mail_template:
                _logger.warning("[CRON] Email template not found, skipping email")
                return False
            
            emails_sent = 0
            for dept, dept_summaries_list in dept_summaries.items():
                if dept and dept.manager_id and dept.manager_id.work_email:
                    try:
                        # Send email to department manager
                        mail_template.send_mail(
                            dept_summaries_list[0].id,
                            force_send=True,
                            email_values={
                                'email_to': dept.manager_id.work_email,
                                'subject': f'Monthly Attendance Report - {dept.name} - {month_start.strftime("%B %Y")}'
                            }
                        )
                        emails_sent += 1
                        _logger.info(f"[CRON] Sent report to {dept.name} manager")
                    except Exception as e:
                        _logger.error(f"[CRON] Failed to email {dept.name}: {str(e)}")
            
            _logger.info(f"[CRON] Successfully sent {emails_sent} monthly report emails")
            return True
            
        except Exception as e:
            _logger.error(f"[CRON] Error emailing monthly reports: {str(e)}")
            return False
