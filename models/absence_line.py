# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, timedelta
import logging

_logger = logging.getLogger(__name__)


class HikvisionAbsenceLine(models.Model):
    _name = 'hikvision.absence.line'
    _description = 'Employee Absence Record'
    _order = 'date desc, employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        compute='_compute_department_id', store=True
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        related='employee_id.company_id', store=True
    )
    date = fields.Date(string='Date', required=True, index=True)
    day_of_week = fields.Char(string='Day', compute='_compute_day_of_week', store=True)
    absence_type = fields.Selection([
        ('absent', 'Absent — No Record'),
        ('incomplete', 'Incomplete — Missing Punch'),
        ('leave', 'On Leave'),
    ], string='Type', default='absent', required=True)
    reason = fields.Text(string='Reason / Note')
    generated_at = fields.Datetime(string='Generated On', default=fields.Datetime.now, readonly=True)

    @api.depends('employee_id', 'employee_id.department_id')
    def _compute_department_id(self):
        for rec in self:
            rec.department_id = rec.employee_id.department_id if rec.employee_id else False

    @api.depends('date')
    def _compute_day_of_week(self):
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        for rec in self:
            rec.day_of_week = days[rec.date.weekday()] if rec.date else ''

    @api.model
    def action_generate(self, date_from, date_to, employee_ids=None, department_ids=None):
        """
        Generate absence line records for the given date range.
        Existing records for the same employee/date are cleared and recreated.
        """
        Employee = self.env['hr.employee']
        emp_domain = [('active', '=', True)]
        if employee_ids:
            emp_domain.append(('id', 'in', employee_ids))
        if department_ids:
            emp_domain.append(('department_id', 'in', department_ids))
        employees = Employee.search(emp_domain)

        if not employees:
            return

        # Clear existing lines for this period + employees
        existing = self.search([
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('employee_id', 'in', employees.ids),
        ])
        existing.unlink()

        # Fetch all attendance records for the range
        Attendance = self.env['hikvision.attendance']
        all_att = Attendance.search([
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('employee_id', 'in', employees.ids),
        ])
        # Build a set of (emp_id, date) for fast lookup
        att_set = set((r.employee_id.id, r.date) for r in all_att)
        incomplete_set = set((r.employee_id.id, r.date) for r in all_att if r.attendance_status == 'incomplete')

        vals_list = []
        d = date_from
        while d <= date_to:
            # Skip Sundays (weekday() == 6)
            if d.weekday() == 6:
                d += timedelta(days=1)
                continue

            for emp in employees:
                key = (emp.id, d)
                if key in incomplete_set:
                    vals_list.append({
                        'employee_id': emp.id,
                        'date': d,
                        'absence_type': 'incomplete',
                    })
                elif key not in att_set:
                    vals_list.append({
                        'employee_id': emp.id,
                        'date': d,
                        'absence_type': 'absent',
                    })
            d += timedelta(days=1)

        if vals_list:
            self.create(vals_list)
            _logger.info(
                'Absence Report: Generated %d absence records (%s to %s)',
                len(vals_list), date_from, date_to
            )
