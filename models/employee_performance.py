# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)


class HikvisionEmployeePerformance(models.Model):
    _name = 'hikvision.employee.performance'
    _description = 'Employee Attendance Performance Scoring'
    _order = 'month desc, performance_score desc'
    _rec_name = 'display_name'

    # Identity
    employee_id = fields.Many2one('hr.employee', string='Employee', required=True, index=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                   related='employee_id.department_id', store=True)
    month = fields.Date(string='Month', required=True, index=True)
    month_display = fields.Char(string='Period', compute='_compute_month_display', store=True)
    
    # Performance Scores (0-100)
    performance_score = fields.Float(string='Overall Performance Score', digits=(5, 2),
                                     compute='_compute_performance_score', store=True)
    attendance_score = fields.Float(string='Attendance Score', digits=(5, 2))
    punctuality_score = fields.Float(string='Punctuality Score', digits=(5, 2))
    consistency_score = fields.Float(string='Consistency Score', digits=(5, 2))
    overtime_score = fields.Float(string='Overtime Score', digits=(5, 2))
    
    # Performance Grade
    performance_grade = fields.Selection([
        ('A+', 'A+ Exceptional'),
        ('A', 'A Excellent'),
        ('B', 'B Good'),
        ('C', 'C Average'),
        ('D', 'D Below Average'),
        ('F', 'F Poor'),
    ], string='Performance Grade', compute='_compute_performance_grade', store=True)
    
    # Metrics (from monthly summary)
    attendance_rate = fields.Float(string='Attendance Rate %', digits=(5, 2))
    punctuality_rate = fields.Float(string='Punctuality Rate %', digits=(5, 2))
    working_days = fields.Integer(string='Working Days')
    present_days = fields.Integer(string='Present Days')
    late_days = fields.Integer(string='Late Days')
    early_leave_days = fields.Integer(string='Early Leave Days')
    overtime_hours = fields.Float(string='Overtime Hours', digits=(6, 2))
    
    # Behavioral Indicators
    consecutive_on_time_days = fields.Integer(string='Consecutive On-Time Days',
                                             help='Current streak of on-time arrivals')
    perfect_attendance_month = fields.Boolean(string='Perfect Attendance',
                                             compute='_compute_perfect_attendance', store=True)
    
    # Improvement Tracking
    score_trend = fields.Selection([
        ('improving', 'Improving'),
        ('stable', 'Stable'),
        ('declining', 'Declining'),
    ], string='Score Trend', compute='_compute_score_trend', store=True)
    
    score_change = fields.Float(string='Score Change', digits=(5, 2),
                                help='Change vs previous month')
    
    # Recommendations
    improvement_areas = fields.Text(string='Areas for Improvement',
                                   compute='_compute_recommendations', store=True)
    strengths = fields.Text(string='Strengths',
                           compute='_compute_recommendations', store=True)
    
    # Display
    display_name = fields.Char(compute='_compute_display_name_field', store=False)
    
    _sql_constraints = [
        ('emp_month_uniq', 'unique(employee_id, month)',
         'Performance record already exists for this employee and month.')
    ]

    @api.depends('month')
    def _compute_month_display(self):
        for rec in self:
            rec.month_display = rec.month.strftime('%B %Y') if rec.month else ''

    @api.depends('employee_id', 'month')
    def _compute_display_name_field(self):
        for rec in self:
            emp = rec.employee_id.name if rec.employee_id else 'Unknown'
            month = rec.month.strftime('%B %Y') if rec.month else ''
            rec.display_name = f'{emp} — {month}'

    @api.depends('attendance_rate', 'present_days', 'working_days', 'late_days', 'early_leave_days')
    def _compute_perfect_attendance(self):
        for rec in self:
            rec.perfect_attendance_month = (
                rec.present_days == rec.working_days and
                rec.late_days == 0 and
                rec.early_leave_days == 0
            )

    @api.depends('attendance_score', 'punctuality_score', 'consistency_score', 'overtime_score')
    def _compute_performance_score(self):
        """Calculate weighted overall performance score"""
        for rec in self:
            # Weighted calculation
            rec.performance_score = (
                rec.attendance_score * 0.35 +  # 35% weight
                rec.punctuality_score * 0.35 +  # 35% weight
                rec.consistency_score * 0.20 +  # 20% weight
                rec.overtime_score * 0.10  # 10% weight
            )

    @api.depends('performance_score')
    def _compute_performance_grade(self):
        for rec in self:
            score = rec.performance_score
            if score >= 95:
                rec.performance_grade = 'A+'
            elif score >= 85:
                rec.performance_grade = 'A'
            elif score >= 75:
                rec.performance_grade = 'B'
            elif score >= 65:
                rec.performance_grade = 'C'
            elif score >= 50:
                rec.performance_grade = 'D'
            else:
                rec.performance_grade = 'F'

    @api.depends('performance_score')
    def _compute_score_trend(self):
        """Compare with previous month to determine trend"""
        for rec in self:
            prev_month = rec.month - relativedelta(months=1)
            prev_record = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('month', '=', prev_month),
            ], limit=1)
            
            if prev_record:
                diff = rec.performance_score - prev_record.performance_score
                rec.score_change = round(diff, 2)
                
                if diff > 3:
                    rec.score_trend = 'improving'
                elif diff < -3:
                    rec.score_trend = 'declining'
                else:
                    rec.score_trend = 'stable'
            else:
                rec.score_trend = 'stable'
                rec.score_change = 0

    @api.depends('attendance_score', 'punctuality_score', 'consistency_score', 'perfect_attendance_month')
    def _compute_recommendations(self):
        """Generate personalized recommendations"""
        for rec in self:
            strengths = []
            improvements = []
            
            # Identify strengths
            if rec.perfect_attendance_month:
                strengths.append("Perfect attendance this month!")
            if rec.attendance_score >= 95:
                strengths.append("Excellent attendance rate")
            if rec.punctuality_score >= 95:
                strengths.append("Consistently on-time")
            if rec.consecutive_on_time_days >= 20:
                strengths.append(f"{rec.consecutive_on_time_days} days on-time streak")
            if rec.consistency_score >= 90:
                strengths.append("Very consistent work schedule")
            
            # Identify improvement areas
            if rec.attendance_score < 85:
                improvements.append("Focus on improving attendance rate")
            if rec.punctuality_score < 85:
                improvements.append("Work on arriving on time")
            if rec.late_days > 5:
                improvements.append(f"Reduce late arrivals (currently {rec.late_days} days)")
            if rec.consistency_score < 70:
                improvements.append("Maintain more consistent attendance patterns")
            if rec.early_leave_days > 3:
                improvements.append("Avoid early departures when possible")
            
            rec.strengths = '\n'.join(f"• {s}" for s in strengths) if strengths else "Keep up the good work!"
            rec.improvement_areas = '\n'.join(f"• {i}" for i in improvements) if improvements else "Excellent performance across all areas!"

    @api.model
    def action_generate_performance(self, month=None, employee_ids=None, department_ids=None):
        """
        Generate performance scores for given month and employees
        """
        if not month:
            today = date.today()
            month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        
        # Get employees
        Employee = self.env['hr.employee']
        emp_domain = [('active', '=', True)]
        if employee_ids:
            emp_domain.append(('id', 'in', employee_ids))
        if department_ids:
            emp_domain.append(('department_id', 'in', department_ids))
        employees = Employee.search(emp_domain)
        
        if not employees:
            return
        
        # Delete existing
        self.search([
            ('month', '=', month),
            ('employee_id', 'in', employees.ids),
        ]).unlink()
        
        Summary = self.env['hikvision.monthly.summary']
        Attendance = self.env['hikvision.attendance']
        
        # Calculate period
        next_month = month + relativedelta(months=1)
        month_end = next_month - timedelta(days=1)
        
        vals_list = []
        
        for emp in employees:
            # Get monthly summary
            summary = Summary.search([
                ('employee_id', '=', emp.id),
                ('month', '=', month),
            ], limit=1)
            
            if not summary:
                continue
            
            # Calculate attendance score (based on attendance rate)
            attendance_score = min(100, summary.attendance_rate)
            
            # Calculate punctuality score (based on punctuality rate)
            punctuality_score = min(100, summary.punctuality_rate)
            
            # Calculate consistency score (low variance in check-in times)
            records = Attendance.search([
                ('employee_id', '=', emp.id),
                ('date', '>=', month),
                ('date', '<=', month_end),
                ('first_check_in', '!=', False),
            ])
            
            if records:
                check_in_times = []
                for rec in records:
                    if rec.first_check_in:
                        # Convert to minutes since midnight
                        check_in_times.append(rec.first_check_in.hour * 60 + rec.first_check_in.minute)
                
                if len(check_in_times) > 1:
                    import statistics
                    variance = statistics.variance(check_in_times)
                    # Lower variance = higher consistency
                    # Assume variance of 0 = 100 score, variance of 900 (30 min std dev) = 70 score
                    consistency_score = max(50, min(100, 100 - (variance / 30)))
                else:
                    consistency_score = 100
            else:
                consistency_score = 0
            
            # Calculate overtime score (reasonable OT = good, excessive = bad)
            # Ideal OT: 10-20 hours per month
            ot_hours = summary.overtime_hours
            if 10 <= ot_hours <= 20:
                overtime_score = 100
            elif ot_hours < 10:
                overtime_score = 70 + (ot_hours * 3)  # 70-100
            else:  # > 20
                overtime_score = max(50, 100 - ((ot_hours - 20) * 2))  # diminishing returns
            
            # Calculate consecutive on-time days
            consecutive_days = 0
            recent_records = Attendance.search([
                ('employee_id', '=', emp.id),
                ('date', '<=', month_end),
            ], order='date desc', limit=30)
            
            for rec in reversed(recent_records):
                if not rec.is_late:
                    consecutive_days += 1
                else:
                    break
            
            vals_list.append({
                'employee_id': emp.id,
                'month': month,
                'attendance_score': round(attendance_score, 2),
                'punctuality_score': round(punctuality_score, 2),
                'consistency_score': round(consistency_score, 2),
                'overtime_score': round(overtime_score, 2),
                'attendance_rate': summary.attendance_rate,
                'punctuality_rate': summary.punctuality_rate,
                'working_days': summary.working_days,
                'present_days': summary.present_days,
                'late_days': summary.late_days,
                'early_leave_days': summary.early_leave_days,
                'overtime_hours': summary.overtime_hours,
                'consecutive_on_time_days': consecutive_days,
            })
        
        if vals_list:
            self.create(vals_list)
            _logger.info(f'Generated {len(vals_list)} performance records for {month.strftime("%B %Y")}')
        
        return True

    # ========================================================================
    # CRON METHOD
    # ========================================================================

    @api.model
    def action_cron_generate_performance(self):
        """
        Cron method: Generate performance scores for previous month
        Runs on 3rd of month at 6 AM (after summaries and analytics)
        """
        try:
            # Get first day of previous month
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_month = first_of_this_month - timedelta(days=1)
            month_start = last_month.replace(day=1)
            
            _logger.info(f"[CRON] Generating performance scores for {month_start.strftime('%B %Y')}")
            
            # Generate performance scores
            self.action_generate_performance(month=month_start)
            
            _logger.info(f"[CRON] Successfully generated performance scores")
            return True
            
        except Exception as e:
            _logger.error(f"[CRON] Error generating performance scores: {str(e)}")
            return False
