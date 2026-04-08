from odoo import models, fields, api
from datetime import datetime, timedelta
import pytz

class HikvisionAttendance(models.Model):
    _name = 'hikvision.attendance'
    _inherit = ['mail.thread']
    _description = 'Hikvision Daily Attendance Summary'
    _order = 'date desc'

    employee_id = fields.Many2one('hr.employee', string="Employee", required=True)
    company_id = fields.Many2one('res.company', string='Company', related='employee_id.company_id', store=True)
    department_id = fields.Many2one('hr.department', related='employee_id.department_id', store=True, string="Department")
    date = fields.Date(string="Date", required=True)
    first_check_in = fields.Datetime(string="First Check-in")
    last_check_out = fields.Datetime(string="Last Check-out")
    status = fields.Selection([
        ('in', 'Checked In'),
        ('out', 'Checked Out'),
    ], string="Punch Status")
    
    # Attendance status
    attendance_status = fields.Selection([
        ('present', 'Present'),
        ('incomplete', 'Incomplete'),
        ('absent', 'Absent'),
    ], string="Attendance", compute="_compute_attendance_status", store=True)
    
    # Computed fields
    total_hours = fields.Float(string="Total Hours", compute="_compute_total_hours", store=True)
    working_minutes = fields.Integer(string="Working Minutes", compute="_compute_working_minutes", store=True, help="Total minutes minus 60 minutes lunch break (480 min = 8 hours)")
    is_late = fields.Boolean(string="Late", compute="_compute_late_early", store=True)
    is_early_leave = fields.Boolean(string="Early Leave", compute="_compute_late_early", store=True)
    late_minutes = fields.Integer(string="Late (min)", compute="_compute_late_early", store=True)
    early_leave_minutes = fields.Integer(string="Early (min)", compute="_compute_late_early", store=True)
    
    # Overtime & Approval
    overtime_hours = fields.Float(string="Overtime Hours", compute="_compute_overtime", store=True)
    ot_payable_hours = fields.Float(string="Payable OT Hours", compute="_compute_overtime", store=True, help="Weighted OT hours based on policy rates")
    
    # Approval Stats (Non-stored or stored for search? Stored is better for perf)
    ot_weekly_total = fields.Float(string="Weekly OT Total", compute="_compute_approval_stats")

    ot_monthly_total = fields.Float(string="Monthly OT Total", compute="_compute_approval_stats")
    
    # Manual Overtime Request
    manual_overtime = fields.Float(string="Manual Overtime Claim", help="Manually specified overtime hours if different from auto-calculation")
    request_reason = fields.Text(string="Reason for Request", help="Reason for manual overtime claim")
    
    approval_state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'Pending'),
        ('second_approval', 'Second Approval'),
        ('approved', 'Approved'),
        ('refused', 'Refused')
    ], string="Approval Status", default='draft', tracking=True)
    
    approver_ids = fields.Many2many('res.users', string="Approvers", help="List of users who can approve this request")

    @api.depends('first_check_in', 'last_check_out')
    def _compute_attendance_status(self):
        for rec in self:
            if rec.first_check_in and rec.last_check_out:
                rec.attendance_status = 'present'
            elif rec.first_check_in and not rec.last_check_out:
                rec.attendance_status = 'incomplete'
            else:
                rec.attendance_status = 'absent'

    @api.depends('first_check_in', 'last_check_out')
    def _compute_total_hours(self):
        for rec in self:
            if rec.first_check_in and rec.last_check_out:
                delta = rec.last_check_out - rec.first_check_in
                rec.total_hours = delta.total_seconds() / 3600
            else:
                rec.total_hours = 0.0

    @api.depends('total_hours', 'employee_id.attendance_policy_id')
    def _compute_working_minutes(self):
        """Calculate working minutes using policy lunch duration and cap at 8 hours (480 min) for standard shifts"""
        for rec in self:
            if rec.total_hours > 0:
                policy = rec.employee_id.attendance_policy_id
                lunch_min = policy.lunch_duration if policy else 60.0
                
                # Convert hours to minutes and deduct lunch
                total_minutes = rec.total_hours * 60
                working_mins = max(0, int(total_minutes - lunch_min))
                
                # End cap based on policy hours (e.g. 5:30 - 8:30 = 9 hrs - 1 hr lunch = 8 hrs)
                # This keeps regular work distinct from overtime.
                max_regular_min = 480 # Default 8 hours
                if policy:
                   max_regular_min = int((policy.work_end - policy.work_start) * 60 - lunch_min)
                
                rec.working_minutes = min(max(0, max_regular_min), working_mins)
            else:
                rec.working_minutes = 0

    @api.depends('first_check_in', 'last_check_out', 'employee_id.attendance_policy_id', 'date')
    def _compute_late_early(self):
        for rec in self:
            rec.is_late = False
            rec.is_early_leave = False
            rec.late_minutes = 0
            rec.early_leave_minutes = 0
            
            if not rec.employee_id or not rec.date:
                continue
            
            policy = rec.employee_id.attendance_policy_id
            if not policy or policy.ignore_late_early:
                continue
                
            # robust timezone fallback: Policy > Employee > User > Company > UTC
            tz_name = (policy and policy.tz) or rec.employee_id.tz or self.env.user.tz or self.env.company.partner_id.tz or 'UTC'
            try:
                local_tz = pytz.timezone(tz_name)
            except:
                local_tz = pytz.UTC
            
            # Check Late Arrival
            if rec.first_check_in:
                # Convert UTC check-in to local time
                check_in_local = rec.first_check_in.replace(tzinfo=pytz.UTC).astimezone(local_tz)
                check_in_hour = check_in_local.hour + check_in_local.minute / 60.0
                
                # Work start time + tolerance (e.g., 8.5 + 15/60 = 8.75 = 8:45)
                late_limit = policy.work_start + (policy.late_tolerance / 60.0)
                
                if check_in_hour > late_limit:
                    rec.is_late = True
                    # Calculate late minutes from work_start (total time late)
                    # e.g., check-in at 8:46 (8.766), work_start at 8:30 (8.5)
                    # late_minutes = (8.766 - 8.5) * 60 = 16 minutes
                    rec.late_minutes = int((check_in_hour - policy.work_start) * 60)

            # Check Early Leave
            if rec.last_check_out:
                # Convert UTC check-out to local time
                check_out_local = rec.last_check_out.replace(tzinfo=pytz.UTC).astimezone(local_tz)
                check_out_hour = check_out_local.hour + check_out_local.minute / 60.0
                
                # Work end time - tolerance (e.g., 17.5 - 15/60 = 17.25 = 17:15)
                early_limit = policy.work_end - (policy.early_leave_tolerance / 60.0)
                
                if check_out_hour < early_limit:
                    rec.is_early_leave = True
                    # Calculate early leave minutes from check-out to work_end
                    # e.g., check-out at 17:18 (17.3), work_end at 17:30 (17.5)
                    # early_leave_minutes = (17.5 - 17.3) * 60 = 12 minutes
                    rec.early_leave_minutes = int((policy.work_end - check_out_hour) * 60)

    @api.depends('last_check_out', 'employee_id.attendance_policy_id', 'manual_overtime')
    def _compute_overtime(self):
        for rec in self:
            # If manual overtime is set, use it!
            if rec.manual_overtime > 0:
                rec.overtime_hours = rec.manual_overtime
                # Recalculate payable based on manual hours? Or just assume 1:1 for manual?
                # Let's assume standard rate logic applies to this duration unless we want manual payable too.
                # For now, let's treat manual overtime as raw hours that need rate application.
                # We need to calculate payable based on these hours. We'll use a simplified rate calculation 
                # effectively assuming the OT happened 'after work'. 
                # Or simpler: just match payable to manual for now or re-run the rate logic using a hypothetical start time?
                # Let's re-run rate logic using the manual duration starting from cutoff.
                
                # We need common variables from below:
                rec.ot_payable_hours = 0.0 # Will be calc below
                
                # If we don't have policy/check_out, we can't easily guess 'when' the OT happened for rates (day/night).
                # Fallback: Payable = Manual * 1.0 if no policy context?
                continue
            else:
                rec.overtime_hours = 0.0
                rec.ot_payable_hours = 0.0
            
            # Common Policy Setup (Needed for both Auto and Manual rate calc)
            policy = rec.employee_id.attendance_policy_id
            if not policy or not policy.ot_apply:
                 # Even if manual, if policy says NO OT, maybe we shouldn't allow? 
                 # But manual is an override. Let's allow manual even if 'ot_apply' is false? 
                 # Actually, usually manual request implies we want it.
                 pass

            # ... Rest of logic needs adjusting to wrap Auto calculation ...
            
            # AUTO CALCULATION (Only if manual is 0)
            if rec.manual_overtime <= 0:
                if not policy or not policy.ot_apply or not rec.last_check_out:
                    rec.overtime_hours = 0.0
                    rec.ot_payable_hours = 0.0
                    continue

                # Timezone fallback: Policy > Employee > User > UTC
                tz_name = (policy and policy.tz) or rec.employee_id.tz or self.env.user.tz or 'UTC'
                try:
                    local_tz = pytz.timezone(tz_name)
                except:
                    local_tz = pytz.UTC
                    
                dt_local = rec.last_check_out.replace(tzinfo=pytz.UTC).astimezone(local_tz)
                check_out_hour = dt_local.hour + dt_local.minute / 60.0
            
            # Simple OT Calculation (Hours after work end?)
            # Usually OT is strictly (Check Out - Work End) or (Check Out - OT Start)
            # User previously had logic: if check_out > ot_start_time, OT = check_out - work_end
            
            # Calculate raw OT hours first
            raw_ot_hours = 0.0
            
            # Use policy logic for start
            ot_start = policy.ot_start_time # e.g. 17.51
            cutoff_hour = policy.work_end # e.g. 17.5
            
            # Saturday Awareness: OT starts earlier on Saturdays
            if rec.date.weekday() == 5: # Saturday
                cutoff_hour = policy.work_end_saturday
                # OT start time follows cutoff closely unless specifically offset
                # For simplicity, if we are on Saturday, OT starts after Saturday End
                ot_start = cutoff_hour + (1 / 60.0) # 1 minute past end
            
            # Handle day crossing
            is_next_day = False
            check_out_date = dt_local.date()
            if check_out_date > rec.date:
                is_next_day = True
                check_out_hour += 24.0 # Adjust for calculation
            
            if check_out_hour > ot_start:
                 raw_ot_hours = check_out_hour - cutoff_hour
                 # Cap at limit
                 limit = policy.ot_end_limit
                 if limit < 12.0: limit += 24.0 # Limit is usually next morning
                 if check_out_hour > limit:
                     raw_ot_hours = limit - cutoff_hour
            
            rec.overtime_hours = max(0.0, raw_ot_hours)

            # --- Calculate Payable Hours based on Rates ---
            if rec.overtime_hours > 0:
                payable = 0.0
                
                # Determine Day Type
                weekday = rec.date.weekday() # 0=Mon, 6=Sun
                is_holiday = False
                
                # Check Public Holidays
                if rec.employee_id.resource_calendar_id:
                     # Check global leaves
                     start_dt = datetime.combine(rec.date, datetime.min.time())
                     end_dt = datetime.combine(rec.date, datetime.max.time())
                     # Simply checking if any global leave intersects today
                     leaves = rec.employee_id.resource_calendar_id.global_leave_ids
                     for leave in leaves:
                         if leave.date_from.date() <= rec.date <= leave.date_to.date():
                             is_holiday = True
                             break
                
                # Base Rate determination
                rate = policy.rate_weekday
                if is_holiday:
                    rate = policy.rate_holiday
                elif weekday == 6: # Sunday
                    rate = policy.rate_sunday
                elif weekday == 5: # Saturday
                    rate = policy.rate_saturday
                
                # Special Time-based Logic (applied iteratively?)
                # We have a duration (raw_ot_hours) starting from `cutoff_hour`
                # We need to integrate this duration over time to apply rates
                
                # Simplification: Iterate hour by hour or handling intervals
                # Start: cutoff_hour (e.g. 17.5)
                # End: Start + raw_ot_hours
                
                current = cutoff_hour
                end = cutoff_hour + rec.overtime_hours
                
                # We step through 30min chunks? Or exact calculation?
                # Exact:
                
                # Intervals of interest:
                # 1. Saturday Afternoon (if Saturday) > saturday_afternoon_start
                # 2. Night > night_start (e.g. 22.0)
                # 3. Night < night_end (e.g. 6.0 next day -> 30.0)
                
                # Note: `current` might be > 24.0 (next day)
                
                # Sort transition points
                points = [current, end]
                
                # Night Start (e.g. 22)
                if policy.night_start > current and policy.night_start < end:
                    points.append(policy.night_start)
                
                # Sat Afternoon Start (e.g. 13) - Only if Saturday
                if weekday == 5 and not is_holiday:
                    if policy.saturday_afternoon_start > current and policy.saturday_afternoon_start < end:
                        points.append(policy.saturday_afternoon_start)

                points = sorted(list(set(points)))
                
                for i in range(len(points) - 1):
                    p_start = points[i]
                    p_end = points[i+1]
                    duration = p_end - p_start
                    
                    interval_rate = rate # Default for day
                    
                    # Apply specific overrides
                    
                    # 1. Saturday Afternoon override
                    if weekday == 5 and not is_holiday and p_start >= policy.saturday_afternoon_start:
                        interval_rate = max(interval_rate, policy.rate_saturday_afternoon)
                    
                    # 2. Night Rate override (High priority)
                    # Check if p_start is in night window (defined in policy, e.g. 22 to 6)
                    night_s = policy.night_start
                    night_e = policy.night_end
                    
                    # Handle window that crosses midnight (e.g. 22:00 -> 06:00)
                    is_night = False
                    if night_s > night_e: # Crosses midnight
                        if p_start >= night_s or p_start < night_e:
                            is_night = True
                        elif p_start >= (night_s + 24) or p_start < (night_e + 24):
                            # Handle next day transition case (p_start can be > 24)
                            is_night = True
                    else: # Within same day window
                        if night_s <= p_start < night_e:
                            is_night = True
                        elif night_s <= (p_start - 24) < night_e:
                            is_night = True

                    if is_night:
                        interval_rate = max(interval_rate, policy.rate_night)
                    
                    payable += duration * interval_rate
                
                rec.ot_payable_hours = payable

            # Trigger approval if OT exists (Auto or Manual)
            if rec.overtime_hours > 0 and rec.approval_state == 'draft':
                 # Don't auto-submit manual ones? Or yes? 
                 # Usually manual request follows a button click 'Request'.
                 # So we might not want to auto-move to 'to_approve' just by computing?
                 # Existing logic auto-moved. Let's keep it consistent BUT:
                 # If it's manual, we want them to click "Claim" button first?
                 # Actually, compute methods shouldn't change state ideally (creates side effects).
                 # But sticking to existing pattern for now.
                 pass

    def action_manual_request(self):
        self.ensure_one()
        if self.manual_overtime > 0:
            self.overtime_hours = self.manual_overtime # Trigger compute/store
            self.approval_state = 'to_approve'

    def _compute_approval_stats(self):
        for rec in self:
            # Weekly Total
            start_week = rec.date - timedelta(days=rec.date.weekday())
            end_week = start_week + timedelta(days=6)
            
            weekly_recs = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '>=', start_week),
                ('date', '<=', end_week),
                ('id', '!=', rec.id) # Exclude current potentially? Or include? User wants "how many... does person have". Include current + others.
            ])
            # Just sum all in database (approved + to_approve?)
            # User wants to know "person have", usually implies 'Approved' or 'Worked'.
            # Let's sum all overtime_hours
            total_w = sum(weekly_recs.mapped('overtime_hours'))
            rec.ot_weekly_total = total_w + rec.overtime_hours

            # Monthly Total
            start_month = rec.date.replace(day=1)
            # End month logic skipped, just >= start_month and < next month
            # Simple: matching same month
            monthly_recs = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('date', '>=', start_month),
                ('date', '<', (start_month + timedelta(days=32)).replace(day=1)),
                ('id', '!=', rec.id)
            ])
            total_m = sum(monthly_recs.mapped('overtime_hours'))
            rec.ot_monthly_total = total_m + rec.overtime_hours

    def action_submit_ot(self):
        self.ensure_one()
        self.approval_state = 'to_approve'
        
    def action_first_approve(self):
        self.ensure_one()
        self.approval_state = 'second_approval'

    def action_second_approve(self):
        self.ensure_one()
        self.approval_state = 'approved'
        
    def action_refuse_ot(self):
        self.ensure_one()
        self.approval_state = 'refused'
        self.overtime_hours = 0.0
        self.ot_payable_hours = 0.0
