# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class HikvisionAuditTrail(models.Model):
    _name = 'hikvision.audit.trail'
    _description = 'Attendance Record Audit Trail'
    _order = 'changed_at desc'

    # Reference to the attendance record (kept even if deleted)
    attendance_id = fields.Many2one(
        'hikvision.attendance', string='Attendance Record',
        ondelete='set null', index=True
    )
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    department_id = fields.Many2one(
        'hr.department', string='Department',
        related='employee_id.department_id', store=True
    )
    attendance_date = fields.Date(string='Attendance Date', index=True)

    # What changed
    action = fields.Selection([
        ('create', 'Record Created'),
        ('write', 'Record Updated'),
        ('unlink', 'Record Deleted'),
    ], string='Action', required=True)
    field_name = fields.Char(string='Field Changed')
    field_label = fields.Char(string='Field Label')
    old_value = fields.Char(string='Previous Value')
    new_value = fields.Char(string='New Value')
    change_summary = fields.Text(string='Change Summary')

    # Who & When
    changed_by = fields.Many2one('res.users', string='Changed By', default=lambda self: self.env.user)
    changed_at = fields.Datetime(string='Changed At', default=fields.Datetime.now, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company
    )
