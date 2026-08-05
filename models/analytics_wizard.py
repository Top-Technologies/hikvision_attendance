# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


class HikvisionAnalyticsWizard(models.TransientModel):
    _name = 'hikvision.analytics.wizard'
    _description = 'Analytics Generation Wizard'

    period_type = fields.Selection([
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ], string='Period Type', required=True, default='monthly')
    
    period_start = fields.Date(string='Period Start', required=True,
                               default=lambda self: date.today().replace(day=1))
    
    department_ids = fields.Many2many('hr.department', string='Departments',
                                     help='Leave empty for all departments')
    
    def action_generate_analytics(self):
        """Generate analytics and open results"""
        self.ensure_one()
        
        # Generate analytics
        Analytics = self.env['hikvision.attendance.analytics']
        Analytics.action_generate_analytics(
            period_type=self.period_type,
            period_start=self.period_start,
            department_ids=self.department_ids.ids if self.department_ids else None
        )
        
        # Calculate period end
        if self.period_type == 'weekly':
            period_end = self.period_start + timedelta(days=6)
        elif self.period_type == 'monthly':
            next_month = self.period_start + relativedelta(months=1)
            period_end = next_month - timedelta(days=1)
        elif self.period_type == 'quarterly':
            next_quarter = self.period_start + relativedelta(months=3)
            period_end = next_quarter - timedelta(days=1)
        else:  # yearly
            next_year = self.period_start + relativedelta(years=1)
            period_end = next_year - timedelta(days=1)
        
        # Build domain
        domain = [
            ('period_type', '=', self.period_type),
            ('period_start', '=', self.period_start),
        ]
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        
        # Return action to view results
        return {
            'name': _('Attendance Analytics'),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.attendance.analytics',
            'view_mode': 'list,pivot,graph,form',
            'domain': domain,
            'context': {
                'group_by': ['department_id'],
                'pivot_measures': ['avg_attendance_rate', 'avg_punctuality_rate', 'overall_score'],
                'graph_type': 'bar',
            },
            'target': 'current',
        }


class HikvisionPerformanceWizard(models.TransientModel):
    _name = 'hikvision.performance.wizard'
    _description = 'Performance Score Generation Wizard'

    month = fields.Date(string='Month', required=True,
                       default=lambda self: (date.today().replace(day=1) - timedelta(days=1)).replace(day=1),
                       help='First day of the month')
    
    department_ids = fields.Many2many('hr.department', string='Departments',
                                     help='Leave empty for all departments')
    
    employee_ids = fields.Many2many('hr.employee', string='Employees',
                                   help='Leave empty for all employees')
    
    def action_generate_performance(self):
        """Generate performance scores and open results"""
        self.ensure_one()
        
        # Generate performance scores
        Performance = self.env['hikvision.employee.performance']
        Performance.action_generate_performance(
            month=self.month,
            employee_ids=self.employee_ids.ids if self.employee_ids else None,
            department_ids=self.department_ids.ids if self.department_ids else None
        )
        
        # Build domain
        domain = [('month', '=', self.month)]
        if self.department_ids:
            domain.append(('department_id', 'in', self.department_ids.ids))
        if self.employee_ids:
            domain.append(('employee_id', 'in', self.employee_ids.ids))
        
        # Return action to view results
        return {
            'name': _('Employee Performance Scores'),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.employee.performance',
            'view_mode': 'list,pivot,graph,form',
            'domain': domain,
            'context': {
                'group_by': ['performance_grade', 'department_id'],
                'pivot_measures': ['performance_score', 'attendance_score', 'punctuality_score'],
                'graph_type': 'bar',
            },
            'target': 'current',
        }


class HikvisionTrendAnalysisWizard(models.TransientModel):
    _name = 'hikvision.trend.analysis.wizard'
    _description = 'Trend Analysis Wizard'

    date_from = fields.Date(string='From Date', required=True,
                           default=lambda self: date.today() - relativedelta(months=6))
    date_to = fields.Date(string='To Date', required=True,
                         default=lambda self: date.today())
    
    analysis_type = fields.Selection([
        ('attendance', 'Attendance Trends'),
        ('punctuality', 'Punctuality Trends'),
        ('exceptions', 'Exception Trends'),
        ('overtime', 'Overtime Trends'),
        ('performance', 'Performance Trends'),
    ], string='Analysis Type', required=True, default='attendance')
    
    department_ids = fields.Many2many('hr.department', string='Departments')
    
    def action_run_analysis(self):
        """Run trend analysis and show results"""
        self.ensure_one()
        
        if self.analysis_type == 'performance':
            # Performance trend analysis
            domain = [
                ('month', '>=', self.date_from),
                ('month', '<=', self.date_to),
            ]
            if self.department_ids:
                domain.append(('department_id', 'in', self.department_ids.ids))
            
            return {
                'name': _('Performance Trend Analysis'),
                'type': 'ir.actions.act_window',
                'res_model': 'hikvision.employee.performance',
                'view_mode': 'graph,pivot,list',
                'domain': domain,
                'context': {
                    'graph_type': 'line',
                    'graph_measure': 'performance_score',
                    'graph_groupbys': ['month:month', 'department_id'],
                    'pivot_measures': ['performance_score', 'attendance_score', 'punctuality_score'],
                    'pivot_row_groupby': ['employee_id'],
                    'pivot_column_groupby': ['month:month'],
                },
                'target': 'current',
            }
        else:
            # Analytics trend analysis
            domain = [
                ('period_start', '>=', self.date_from),
                ('period_start', '<=', self.date_to),
                ('period_type', '=', 'monthly'),
            ]
            if self.department_ids:
                domain.append(('department_id', 'in', self.department_ids.ids))
            
            # Determine measures based on analysis type
            if self.analysis_type == 'attendance':
                measures = ['avg_attendance_rate', 'attendance_score']
                title = 'Attendance Trend Analysis'
            elif self.analysis_type == 'punctuality':
                measures = ['avg_punctuality_rate', 'punctuality_score']
                title = 'Punctuality Trend Analysis'
            elif self.analysis_type == 'exceptions':
                measures = ['total_late_incidents', 'total_absences', 'total_missing_punches']
                title = 'Exception Trend Analysis'
            else:  # overtime
                measures = ['total_ot_hours', 'avg_ot_per_employee']
                title = 'Overtime Trend Analysis'
            
            return {
                'name': _(title),
                'type': 'ir.actions.act_window',
                'res_model': 'hikvision.attendance.analytics',
                'view_mode': 'graph,pivot,list',
                'domain': domain,
                'context': {
                    'graph_type': 'line',
                    'graph_measure': measures[0],
                    'graph_groupbys': ['period_start:month', 'department_id'],
                    'pivot_measures': measures,
                    'pivot_row_groupby': ['department_id'],
                    'pivot_column_groupby': ['period_start:month'],
                },
                'target': 'current',
            }
