# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import logging
import statistics

_logger = logging.getLogger(__name__)


class HikvisionAttendanceAnalytics(models.Model):
    _name = 'hikvision.attendance.analytics'
    _description = 'Advanced Attendance Analytics'
    _order = 'period_start desc'
    _rec_name = 'display_name'

    # Period
    period_type = fields.Selection([
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ], string='Period Type', required=True, default='monthly')
    
    period_start = fields.Date(string='Period Start', required=True, index=True)
    period_end = fields.Date(string='Period End', required=True)
    period_name = fields.Char(string='Period', compute='_compute_period_name', store=True)
    
    # Scope
    department_id = fields.Many2one('hr.department', string='Department', index=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    
    # Attendance Metrics
    total_employees = fields.Integer(string='Total Employees')
    avg_attendance_rate = fields.Float(string='Avg Attendance Rate %', digits=(5, 2))
    avg_punctuality_rate = fields.Float(string='Avg Punctuality Rate %', digits=(5, 2))
    
    # Trend Indicators
    attendance_trend = fields.Selection([
        ('improving', 'Improving'),
        ('stable', 'Stable'),
        ('declining', 'Declining'),
    ], string='Attendance Trend', compute='_compute_trends', store=True)
    
    punctuality_trend = fields.Selection([
        ('improving', 'Improving'),
        ('stable', 'Stable'),
        ('declining', 'Declining'),
    ], string='Punctuality Trend', compute='_compute_trends', store=True)
    
    # Exception Metrics
    total_late_incidents = fields.Integer(string='Total Late Incidents')
    total_early_departures = fields.Integer(string='Total Early Departures')
    total_missing_punches = fields.Integer(string='Total Missing Punches')
    total_absences = fields.Integer(string='Total Absences')
    
    # Exception Trends (vs previous period)
    late_trend_pct = fields.Float(string='Late Trend %', digits=(5, 2),
                                   help='Percentage change vs previous period')
    absence_trend_pct = fields.Float(string='Absence Trend %', digits=(5, 2))
    
    # Overtime Metrics
    total_ot_hours = fields.Float(string='Total OT Hours', digits=(6, 2))
    avg_ot_per_employee = fields.Float(string='Avg OT per Employee', digits=(6, 2))
    ot_trend_pct = fields.Float(string='OT Trend %', digits=(5, 2))
    
    # Performance Scores
    overall_score = fields.Float(string='Overall Score', digits=(3, 2),
                                  compute='_compute_performance_scores', store=True,
                                  help='Composite score 0-100')
    attendance_score = fields.Float(string='Attendance Score', digits=(3, 2))
    punctuality_score = fields.Float(string='Punctuality Score', digits=(3, 2))
    compliance_score = fields.Float(string='Compliance Score', digits=(3, 2))
    
    # Predictive Metrics
    predicted_absence_risk = fields.Selection([
        ('low', 'Low Risk'),
        ('medium', 'Medium Risk'),
        ('high', 'High Risk'),
    ], string='Predicted Absence Risk', compute='_compute_predictive_metrics', store=True)
    
    risk_score = fields.Float(string='Risk Score', digits=(3, 2),
                               help='0-100, higher means more risk')
    
    # Display
    display_name = fields.Char(compute='_compute_display_name_field', store=False)
    
    _sql_constraints = [
        ('period_dept_uniq', 'unique(period_start, department_id)',
         'Analytics already exists for this period and department.')
    ]

    @api.depends('period_start', 'period_end', 'period_type')
    def _compute_period_name(self):
        for rec in self:
            if rec.period_type == 'weekly':
                rec.period_name = f"Week {rec.period_start.isocalendar()[1]}, {rec.period_start.year}"
            elif rec.period_type == 'monthly':
                rec.period_name = rec.period_start.strftime('%B %Y')
            elif rec.period_type == 'quarterly':
                quarter = (rec.period_start.month - 1) // 3 + 1
                rec.period_name = f"Q{quarter} {rec.period_start.year}"
            elif rec.period_type == 'yearly':
                rec.period_name = str(rec.period_start.year)
            else:
                rec.period_name = ''

    @api.depends('period_name', 'department_id')
    def _compute_display_name_field(self):
        for rec in self:
            dept = rec.department_id.name if rec.department_id else 'All Departments'
            rec.display_name = f"{rec.period_name} - {dept}"

    @api.depends('avg_attendance_rate', 'avg_punctuality_rate')
    def _compute_trends(self):
        """Calculate trend by comparing with previous period"""
        for rec in self:
            # Find previous period analytics
            if rec.period_type == 'monthly':
                prev_start = rec.period_start - relativedelta(months=1)
            elif rec.period_type == 'weekly':
                prev_start = rec.period_start - timedelta(days=7)
            elif rec.period_type == 'quarterly':
                prev_start = rec.period_start - relativedelta(months=3)
            else:  # yearly
                prev_start = rec.period_start - relativedelta(years=1)
            
            prev = self.search([
                ('period_start', '=', prev_start),
                ('department_id', '=', rec.department_id.id),
                ('period_type', '=', rec.period_type),
            ], limit=1)
            
            # Attendance trend
            if prev:
                diff = rec.avg_attendance_rate - prev.avg_attendance_rate
                if diff > 2:
                    rec.attendance_trend = 'improving'
                elif diff < -2:
                    rec.attendance_trend = 'declining'
                else:
                    rec.attendance_trend = 'stable'
                
                # Punctuality trend
                diff_p = rec.avg_punctuality_rate - prev.avg_punctuality_rate
                if diff_p > 2:
                    rec.punctuality_trend = 'improving'
                elif diff_p < -2:
                    rec.punctuality_trend = 'declining'
                else:
                    rec.punctuality_trend = 'stable'
            else:
                rec.attendance_trend = 'stable'
                rec.punctuality_trend = 'stable'

    @api.depends('avg_attendance_rate', 'avg_punctuality_rate', 'total_missing_punches', 'total_employees')
    def _compute_performance_scores(self):
        """Calculate composite performance scores"""
        for rec in self:
            # Attendance score (0-100)
            rec.attendance_score = min(100, rec.avg_attendance_rate)
            
            # Punctuality score (0-100)
            rec.punctuality_score = min(100, rec.avg_punctuality_rate)
            
            # Compliance score based on missing punches
            if rec.total_employees > 0:
                missing_rate = (rec.total_missing_punches / (rec.total_employees * 20)) * 100  # assume 20 working days
                rec.compliance_score = max(0, 100 - missing_rate)
            else:
                rec.compliance_score = 0
            
            # Overall score (weighted average)
            rec.overall_score = (
                rec.attendance_score * 0.4 +
                rec.punctuality_score * 0.4 +
                rec.compliance_score * 0.2
            )

    @api.depends('total_absences', 'total_late_incidents', 'avg_attendance_rate')
    def _compute_predictive_metrics(self):
        """Calculate predictive risk metrics"""
        for rec in self:
            # Simple risk calculation based on trends and current metrics
            risk_points = 0
            
            # High absence count
            if rec.total_employees > 0:
                absence_rate = (rec.total_absences / rec.total_employees) * 100
                if absence_rate > 20:
                    risk_points += 30
                elif absence_rate > 10:
                    risk_points += 15
            
            # Declining trends
            if rec.attendance_trend == 'declining':
                risk_points += 25
            if rec.punctuality_trend == 'declining':
                risk_points += 15
            
            # High late incidents
            if rec.total_employees > 0:
                late_rate = (rec.total_late_incidents / rec.total_employees) * 100
                if late_rate > 30:
                    risk_points += 20
                elif late_rate > 15:
                    risk_points += 10
            
            # Low attendance rate
            if rec.avg_attendance_rate < 85:
                risk_points += 10
            
            rec.risk_score = min(100, risk_points)
            
            # Risk classification
            if rec.risk_score >= 60:
                rec.predicted_absence_risk = 'high'
            elif rec.risk_score >= 30:
                rec.predicted_absence_risk = 'medium'
            else:
                rec.predicted_absence_risk = 'low'

    @api.model
    def action_generate_analytics(self, period_type='monthly', period_start=None, department_ids=None):
        """
        Generate analytics for given period and departments
        """
        if not period_start:
            period_start = date.today().replace(day=1)
        
        # Calculate period end based on type
        if period_type == 'weekly':
            period_end = period_start + timedelta(days=6)
        elif period_type == 'monthly':
            next_month = period_start + relativedelta(months=1)
            period_end = next_month - timedelta(days=1)
        elif period_type == 'quarterly':
            next_quarter = period_start + relativedelta(months=3)
            period_end = next_quarter - timedelta(days=1)
        else:  # yearly
            next_year = period_start + relativedelta(years=1)
            period_end = next_year - timedelta(days=1)
        
        # Get departments
        Department = self.env['hr.department']
        if department_ids:
            departments = Department.browse(department_ids)
        else:
            departments = Department.search([])
        
        # Also generate for "all departments" (no department filter)
        departments = departments | Department
        
        # Delete existing analytics
        self.search([
            ('period_start', '=', period_start),
            ('period_type', '=', period_type),
            ('department_id', 'in', departments.ids),
        ]).unlink()
        
        Attendance = self.env['hikvision.attendance']
        Summary = self.env['hikvision.monthly.summary']
        
        vals_list = []
        
        for dept in departments:
            # Get attendance records
            domain = [
                ('date', '>=', period_start),
                ('date', '<=', period_end),
            ]
            if dept:
                domain.append(('department_id', '=', dept.id))
            
            records = Attendance.search(domain)
            
            # Get employees
            if dept:
                employees = self.env['hr.employee'].search([
                    ('department_id', '=', dept.id),
                    ('active', '=', True),
                ])
            else:
                employees = self.env['hr.employee'].search([('active', '=', True)])
            
            total_emp = len(employees)
            
            if total_emp == 0:
                continue
            
            # Calculate metrics
            late_count = len(records.filtered(lambda r: r.is_late))
            early_count = len(records.filtered(lambda r: r.is_early_leave))
            missing_count = len(records.filtered(lambda r: r.status == 'incomplete'))
            
            # Absences (working days - attendance days)
            working_days = 0
            d = period_start
            while d <= period_end:
                if d.weekday() < 6:  # Mon-Sat
                    working_days += 1
                d += timedelta(days=1)
            
            present_count = len(records.filtered(lambda r: r.attendance_status == 'present'))
            total_possible = total_emp * working_days
            absence_count = total_possible - len(records)
            
            # Average rates from monthly summaries
            summary_domain = [('month', '>=', period_start), ('month', '<=', period_end)]
            if dept:
                summary_domain.append(('department_id', '=', dept.id))
            
            summaries = Summary.search(summary_domain)
            if summaries:
                avg_att_rate = statistics.mean(summaries.mapped('attendance_rate'))
                avg_punc_rate = statistics.mean(summaries.mapped('punctuality_rate'))
            else:
                # Calculate from records
                if total_possible > 0:
                    avg_att_rate = (len(records) / total_possible) * 100
                else:
                    avg_att_rate = 0
                if present_count > 0:
                    avg_punc_rate = ((present_count - late_count) / present_count) * 100
                else:
                    avg_punc_rate = 0
            
            # OT metrics
            total_ot = sum(records.mapped('overtime_hours'))
            avg_ot = total_ot / total_emp if total_emp > 0 else 0
            
            # Calculate trends vs previous period
            if period_type == 'monthly':
                prev_start = period_start - relativedelta(months=1)
            elif period_type == 'weekly':
                prev_start = period_start - timedelta(days=7)
            elif period_type == 'quarterly':
                prev_start = period_start - relativedelta(months=3)
            else:
                prev_start = period_start - relativedelta(years=1)
            
            prev_analytics = self.search([
                ('period_start', '=', prev_start),
                ('department_id', '=', dept.id if dept else False),
                ('period_type', '=', period_type),
            ], limit=1)
            
            if prev_analytics:
                late_trend = ((late_count - prev_analytics.total_late_incidents) / 
                             prev_analytics.total_late_incidents * 100) if prev_analytics.total_late_incidents > 0 else 0
                absence_trend = ((absence_count - prev_analytics.total_absences) / 
                                prev_analytics.total_absences * 100) if prev_analytics.total_absences > 0 else 0
                ot_trend = ((total_ot - prev_analytics.total_ot_hours) / 
                           prev_analytics.total_ot_hours * 100) if prev_analytics.total_ot_hours > 0 else 0
            else:
                late_trend = absence_trend = ot_trend = 0
            
            vals_list.append({
                'period_type': period_type,
                'period_start': period_start,
                'period_end': period_end,
                'department_id': dept.id if dept else False,
                'total_employees': total_emp,
                'avg_attendance_rate': round(avg_att_rate, 2),
                'avg_punctuality_rate': round(avg_punc_rate, 2),
                'total_late_incidents': late_count,
                'total_early_departures': early_count,
                'total_missing_punches': missing_count,
                'total_absences': absence_count,
                'late_trend_pct': round(late_trend, 2),
                'absence_trend_pct': round(absence_trend, 2),
                'total_ot_hours': round(total_ot, 2),
                'avg_ot_per_employee': round(avg_ot, 2),
                'ot_trend_pct': round(ot_trend, 2),
            })
        
        if vals_list:
            self.create(vals_list)
            _logger.info(f'Generated {len(vals_list)} analytics records for {period_type} period')
        
        return True

    # ========================================================================
    # CRON METHOD
    # ========================================================================

    @api.model
    def action_cron_generate_monthly_analytics(self):
        """
        Cron method: Generate analytics for previous month
        Runs on 3rd of month at 5 AM (after summaries generated)
        """
        try:
            # Get first day of previous month
            today = date.today()
            first_of_this_month = today.replace(day=1)
            last_month = first_of_this_month - timedelta(days=1)
            month_start = last_month.replace(day=1)
            
            _logger.info(f"[CRON] Generating analytics for {month_start.strftime('%B %Y')}")
            
            # Generate monthly analytics
            self.action_generate_analytics(
                period_type='monthly',
                period_start=month_start
            )
            
            _logger.info(f"[CRON] Successfully generated analytics")
            return True
            
        except Exception as e:
            _logger.error(f"[CRON] Error generating analytics: {str(e)}")
            return False
