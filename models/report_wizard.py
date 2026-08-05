# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


# ---------------------------------------------------------------------------
# 1. Daily Attendance Register
# ---------------------------------------------------------------------------
class HikvisionDailyRegisterWizard(models.TransientModel):
    _name = 'hikvision.daily.register.wizard'
    _description = 'Daily Attendance Register'

    report_date = fields.Date(string='Date', default=fields.Date.today, required=True)
    department_ids = fields.Many2many('hr.department', 'daily_reg_dept_rel', string='Departments',
                                      help='Leave empty for all departments')
    employee_ids = fields.Many2many('hr.employee', 'daily_reg_emp_rel', string='Employees',
                                    help='Leave empty for all employees')

    def action_run(self):
        self.ensure_one()
        domain = [('date', '=', self.report_date)]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        return {
            'name': _('Daily Attendance Register — %s') % self.report_date,
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {
                'search_default_group_by_department': 1,
                'group_by': ['department_id'],
            },
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 2. Monthly Attendance Summary
# ---------------------------------------------------------------------------
class HikvisionMonthlySummaryWizard(models.TransientModel):
    _name = 'hikvision.monthly.summary.wizard'
    _description = 'Monthly Attendance Summary'

    month = fields.Date(
        string='Month',
        default=lambda self: date.today().replace(day=1),
        required=True,
        help='Select any day in the target month'
    )
    department_ids = fields.Many2many('hr.department', 'monthly_sum_dept_rel', string='Departments')
    employee_ids = fields.Many2many('hr.employee', 'monthly_sum_emp_rel', string='Employees')

    def action_run(self):
        self.ensure_one()
        month_start = self.month.replace(day=1)
        self.env['hikvision.monthly.summary'].action_generate(
            month=month_start,
            employee_ids=self.employee_ids.ids,
            department_ids=self.department_ids.ids,
        )
        domain = [('month', '=', month_start)]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        return {
            'name': _('Monthly Attendance Summary — %s') % month_start.strftime('%B %Y'),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.monthly.summary',
            'view_mode': 'list,pivot,graph',
            'domain': domain,
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 3. Employee Timesheet Report
# ---------------------------------------------------------------------------
class HikvisionTimesheetWizard(models.TransientModel):
    _name = 'hikvision.timesheet.wizard'
    _description = 'Employee Timesheet Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    employee_ids = fields.Many2many('hr.employee', 'timesheet_emp_rel', string='Employees')
    department_ids = fields.Many2many('hr.department', 'timesheet_dept_rel', string='Departments')

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        return {
            'name': _('Employee Timesheet — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,pivot,graph',
            'domain': domain,
            'context': {
                'pivot_measures': ['total_hours', 'working_minutes', 'overtime_hours'],
                'pivot_row_groupby': ['employee_id'],
                'pivot_column_groupby': ['date:week'],
                'graph_mode': 'bar',
                'graph_measure': 'total_hours',
                'group_by': ['employee_id'],
            },
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 4. Overtime Report
# ---------------------------------------------------------------------------
class HikvisionOvertimeReportWizard(models.TransientModel):
    _name = 'hikvision.overtime.report.wizard'
    _description = 'Overtime Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    employee_ids = fields.Many2many('hr.employee', 'ot_report_emp_rel', string='Employees')
    department_ids = fields.Many2many('hr.department', 'ot_report_dept_rel', string='Departments')
    approval_state = fields.Selection([
        ('all', 'All'),
        ('approved', 'Approved Only'),
        ('to_approve', 'Pending Approval'),
        ('draft', 'Draft'),
    ], string='Approval Status', default='all')

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('overtime_hours', '>', 0),
        ]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.approval_state != 'all':
            domain.append(('approval_state', '=', self.approval_state))
        return {
            'name': _('Overtime Report — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,pivot,graph',
            'domain': domain,
            'context': {
                'pivot_measures': ['overtime_hours', 'ot_payable_hours'],
                'pivot_row_groupby': ['employee_id'],
                'group_by': ['employee_id', 'approval_state'],
            },
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 5. Late Arrival & Early Departure Report
# ---------------------------------------------------------------------------
class HikvisionLateEarlyWizard(models.TransientModel):
    _name = 'hikvision.late.early.wizard'
    _description = 'Late Arrival & Early Departure Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    employee_ids = fields.Many2many('hr.employee', 'late_early_emp_rel', string='Employees')
    department_ids = fields.Many2many('hr.department', 'late_early_dept_rel', string='Departments')
    report_type = fields.Selection([
        ('both', 'Late & Early Leave'),
        ('late', 'Late Arrivals Only'),
        ('early', 'Early Departures Only'),
    ], string='Report Type', default='both', required=True)

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))

        if self.report_type == 'late':
            domain.append(('is_late', '=', True))
            title = _('Late Arrivals — %s to %s') % (self.date_from, self.date_to)
        elif self.report_type == 'early':
            domain.append(('is_early_leave', '=', True))
            title = _('Early Departures — %s to %s') % (self.date_from, self.date_to)
        else:
            domain.append('|')
            domain.append(('is_late', '=', True))
            domain.append(('is_early_leave', '=', True))
            title = _('Late & Early Departure — %s to %s') % (self.date_from, self.date_to)

        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,pivot,graph',
            'domain': domain,
            'context': {
                'pivot_measures': ['late_minutes', 'early_leave_minutes'],
                'pivot_row_groupby': ['employee_id'],
                'group_by': ['employee_id'],
            },
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 6. Absence Report
# ---------------------------------------------------------------------------
class HikvisionAbsenceReportWizard(models.TransientModel):
    _name = 'hikvision.absence.report.wizard'
    _description = 'Absence Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    employee_ids = fields.Many2many('hr.employee', 'absence_rpt_emp_rel', string='Employees')
    department_ids = fields.Many2many('hr.department', 'absence_rpt_dept_rel', string='Departments')

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        # Generate absence line records
        self.env['hikvision.absence.line'].action_generate(
            date_from=self.date_from,
            date_to=self.date_to,
            employee_ids=self.employee_ids.ids,
            department_ids=self.department_ids.ids,
        )
        domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        return {
            'name': _('Absence Report — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.absence.line',
            'view_mode': 'list,pivot,graph',
            'domain': domain,
            'context': {'group_by': ['employee_id']},
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 7. Missing Punch Report
# ---------------------------------------------------------------------------
class HikvisionMissingPunchWizard(models.TransientModel):
    _name = 'hikvision.missing.punch.wizard'
    _description = 'Missing Punch Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    employee_ids = fields.Many2many('hr.employee', 'missing_punch_emp_rel', string='Employees')
    department_ids = fields.Many2many('hr.department', 'missing_punch_dept_rel', string='Departments')

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('attendance_status', '=', 'incomplete'),
        ]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        return {
            'name': _('Missing Punch Report — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'group_by': ['department_id', 'employee_id']},
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 8. Shift Compliance Report
# ---------------------------------------------------------------------------
class HikvisionShiftComplianceWizard(models.TransientModel):
    _name = 'hikvision.shift.compliance.wizard'
    _description = 'Shift Compliance Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    employee_ids = fields.Many2many('hr.employee', 'shift_comp_emp_rel', string='Employees')
    department_ids = fields.Many2many('hr.department', 'shift_comp_dept_rel', string='Departments')
    policy_ids = fields.Many2many('hikvision.work.policy', string='Policies')

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            ('attendance_status', '=', 'present'),
        ]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.policy_ids:
            domain.append(('employee_id.attendance_policy_id', 'in', self.policy_ids.ids))
        return {
            'name': _('Shift Compliance — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,pivot',
            'domain': domain,
            'context': {
                'pivot_measures': ['working_minutes', 'total_hours'],
                'pivot_row_groupby': ['employee_id'],
                'pivot_column_groupby': ['date:week'],
                'group_by': ['employee_id', 'date:week'],
            },
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 9. Attendance Exception Report
# ---------------------------------------------------------------------------
class HikvisionExceptionReportWizard(models.TransientModel):
    _name = 'hikvision.exception.report.wizard'
    _description = 'Attendance Exception Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    employee_ids = fields.Many2many('hr.employee', 'exception_rpt_emp_rel', string='Employees')
    department_ids = fields.Many2many('hr.department', 'exception_rpt_dept_rel', string='Departments')
    include_late = fields.Boolean(string='Include Late Arrivals', default=True)
    include_early = fields.Boolean(string='Include Early Departures', default=True)
    include_missing_punch = fields.Boolean(string='Include Missing Punches', default=True)
    include_absent = fields.Boolean(string='Include Absences', default=False)

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        if not any([self.include_late, self.include_early, self.include_missing_punch, self.include_absent]):
            raise UserError(_('Please select at least one exception type.'))

        base_domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if self.employee_ids:
            base_domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            base_domain.append(('department_id', 'in', self.department_ids.ids))

        # Build OR conditions for exception types
        exception_clauses = []
        if self.include_late:
            exception_clauses.append(('is_late', '=', True))
        if self.include_early:
            exception_clauses.append(('is_early_leave', '=', True))
        if self.include_missing_punch:
            exception_clauses.append(('attendance_status', '=', 'incomplete'))
        if self.include_absent:
            exception_clauses.append(('attendance_status', '=', 'absent'))

        if len(exception_clauses) == 1:
            domain = base_domain + exception_clauses
        else:
            # Build OR chain
            or_domain = []
            for i, clause in enumerate(exception_clauses):
                if i > 0:
                    or_domain.insert(len(or_domain) - i, '|')
                or_domain.append(clause)
            domain = base_domain + or_domain

        return {
            'name': _('Attendance Exceptions — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,pivot',
            'domain': domain,
            'context': {'group_by': ['department_id', 'employee_id']},
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 10. Attendance Device Synchronization Report
# ---------------------------------------------------------------------------
class HikvisionSyncReportWizard(models.TransientModel):
    _name = 'hikvision.sync.report.wizard'
    _description = 'Attendance Device Synchronization Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    device_ids = fields.Many2many('hikvision.device', string='Devices',
                                  help='Leave empty for all devices')
    status_filter = fields.Selection([
        ('all', 'All'),
        ('success', 'Success Only'),
        ('partial', 'Partial'),
        ('failed', 'Failed Only'),
    ], string='Status', default='all')

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        domain = [
            ('sync_date', '>=', self.date_from),
            ('sync_date', '<=', self.date_to),
        ]
        if self.device_ids:
            domain.append(('device_id', 'in', self.device_ids.ids))
        if self.status_filter != 'all':
            domain.append(('status', '=', self.status_filter))
        return {
            'name': _('Device Sync Report — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.sync.log',
            'view_mode': 'list,graph',
            'domain': domain,
            'context': {'group_by': ['device_id', 'status']},
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 11. Attendance by Branch / Location Report
# ---------------------------------------------------------------------------
class HikvisionBranchReportWizard(models.TransientModel):
    _name = 'hikvision.branch.report.wizard'
    _description = 'Attendance by Branch/Location Report'

    date_from = fields.Date(
        string='From',
        default=lambda self: date.today().replace(day=1),
        required=True
    )
    date_to = fields.Date(string='To', default=fields.Date.today, required=True)
    device_ids = fields.Many2many('hikvision.device', 'branch_rpt_dev_rel', string='Devices / Locations',
                                  help='Filter by specific devices (branch locations). Leave empty for all.')
    department_ids = fields.Many2many('hr.department', 'branch_rpt_dept_rel', string='Departments')

    def action_run(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('From date must be before To date.'))
        # Filter event logs by device, then get employee attendance
        employee_ids = []
        if self.device_ids:
            event_logs = self.env['hikvision.event.log'].search([
                ('device_id', 'in', self.device_ids.ids),
                ('timestamp', '>=', fields.Datetime.from_string(str(self.date_from) + ' 00:00:00')),
                ('timestamp', '<=', fields.Datetime.from_string(str(self.date_to) + ' 23:59:59')),
            ])
            employee_ids = list(set(event_logs.mapped('employee_id').ids))

        domain = [('date', '>=', self.date_from), ('date', '<=', self.date_to)]
        if employee_ids:
            domain.append(('employee_id', 'in', employee_ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))

        return {
            'name': _('Attendance by Location — %s to %s') % (self.date_from, self.date_to),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance',
            'view_mode': 'list,pivot,graph',
            'domain': domain,
            'context': {
                'pivot_row_groupby': ['department_id'],
                'group_by': ['department_id', 'employee_id'],
            },
            'target': 'current',
        }


# ---------------------------------------------------------------------------
# 12. Payroll Attendance Summary Wizard
# ---------------------------------------------------------------------------
class HikvisionPayrollSummaryWizard(models.TransientModel):
    _name = 'hikvision.payroll.summary.wizard'
    _description = 'Payroll Attendance Summary'

    month = fields.Date(
        string='Month',
        default=lambda self: date.today().replace(day=1),
        required=True,
        help='Select any day in the target month'
    )
    department_ids = fields.Many2many('hr.department', 'payroll_sum_dept_rel', string='Departments')
    employee_ids = fields.Many2many('hr.employee', 'payroll_sum_emp_rel', string='Employees')

    def action_run(self):
        self.ensure_one()
        month_start = self.month.replace(day=1)
        self.env['hikvision.payroll.summary'].action_generate(
            month=month_start,
            employee_ids=self.employee_ids.ids,
            department_ids=self.department_ids.ids,
        )
        domain = [('month', '=', month_start)]
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        return {
            'name': _('Payroll Attendance Summary — %s') % month_start.strftime('%B %Y'),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.payroll.summary',
            'view_mode': 'list,pivot',
            'domain': domain,
            'target': 'current',
        }
