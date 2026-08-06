from odoo import models, fields, api, Command, _
from datetime import datetime, timedelta
import pytz

class HikvisionAttendance(models.Model):
    _name = 'hikvision.attendance'
    _inherit = ['mail.thread']
    _description = 'Hikvision Daily Attendance Summary'
    _order = 'date desc'

    employee_id = fields.Many2one('hr.employee', string="Employee", required=True)
    company_id = fields.Many2one('res.company', string='Company', related='employee_id.company_id', store=True)
    department_id = fields.Many2one('hr.department', string="Department", compute='_compute_department_id', store=True)
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
        ('weekend', 'Weekend'),
        ('holiday', 'Holiday'),
    ], string="Attendance", compute="_compute_attendance_status", store=True)
    
    # Computed fields
    total_hours = fields.Float(string="Total Hours", compute="_compute_total_hours", store=True)
    working_minutes = fields.Integer(string="Working Minutes", compute="_compute_working_minutes", store=True, help="Total minutes minus 60 minutes lunch break (480 min = 8 hours)")
    is_late = fields.Boolean(string="Late", compute="_compute_is_late", store=True)
    is_early_leave = fields.Boolean(string="Early Leave", compute="_compute_early_leave", store=True)
    late_minutes = fields.Integer(string="Late (min)", compute="_compute_late_minutes", inverse="_inverse_late_minutes", store=True, readonly=False)
    late_hours = fields.Float(string="Late Hours", compute="_compute_late_hours", store=True)
    early_leave_minutes = fields.Integer(string="Early (min)", compute="_compute_early_leave", store=True)
    absent_hours = fields.Float(string="Absent Hours", compute="_compute_absent_hours", store=True)
    
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

    @api.depends('first_check_in', 'last_check_out', 'employee_id.resource_calendar_id', 'date')
    def _compute_attendance_status(self):
        for rec in self:
            if rec.first_check_in and rec.last_check_out:
                rec.attendance_status = 'present'
            elif rec.first_check_in and not rec.last_check_out:
                rec.attendance_status = 'incomplete'
            else:
                # Check if weekend or holiday
                is_sunday = (rec.date.weekday() == 6) if rec.date else False
                is_holiday = False
                if rec.date and rec.employee_id.resource_calendar_id:
                    leaves = rec.employee_id.resource_calendar_id.global_leave_ids
                    for leave in leaves:
                        if leave.date_from.date() <= rec.date <= leave.date_to.date():
                            is_holiday = True
                            break
                if is_holiday:
                    rec.attendance_status = 'holiday'
                elif is_sunday:
                    rec.attendance_status = 'weekend'
                else:
                    rec.attendance_status = 'absent'

    @api.depends('employee_id', 'employee_id.department_id')
    def _compute_department_id(self):
        """Compute department from employee (handles Odoo 19 hr_version structure)."""
        for rec in self:
            rec.department_id = rec.employee_id.department_id if rec.employee_id else False

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
                
                rec.working_minutes = min(max_regular_min, working_mins)
            else:
                rec.working_minutes = 0

    @api.depends('first_check_in', 'employee_id.attendance_policy_id', 'date')
    def _compute_late_minutes(self):
        for rec in self:
            rec.late_minutes = 0
            if not rec.employee_id or not rec.date or not rec.first_check_in:
                continue
            policy = rec.employee_id.attendance_policy_id
            if not policy or policy.ignore_late_early:
                continue
                
            tz_name = (policy and policy.tz) or rec.employee_id.tz or self.env.user.tz or self.env.company.partner_id.tz or 'UTC'
            try:
                local_tz = pytz.timezone(tz_name)
            except:
                local_tz = pytz.UTC
            
            check_in_local = rec.first_check_in.replace(tzinfo=pytz.UTC).astimezone(local_tz)
            check_in_hour = check_in_local.hour + check_in_local.minute / 60.0
            
            late_limit = policy.work_start + (policy.late_tolerance / 60.0)
            if check_in_hour > late_limit:
                rec.late_minutes = int((check_in_hour - policy.work_start) * 60)

    def _inverse_late_minutes(self):
        pass

    @api.depends('late_minutes')
    def _compute_is_late(self):
        for rec in self:
            rec.is_late = rec.late_minutes > 0

    @api.depends('late_minutes')
    def _compute_late_hours(self):
        for rec in self:
            rec.late_hours = rec.late_minutes / 60.0

    @api.depends('last_check_out', 'employee_id.attendance_policy_id', 'date')
    def _compute_early_leave(self):
        for rec in self:
            rec.is_early_leave = False
            rec.early_leave_minutes = 0
            if not rec.employee_id or not rec.date or not rec.last_check_out:
                continue
            policy = rec.employee_id.attendance_policy_id
            if not policy or policy.ignore_late_early:
                continue
                
            tz_name = (policy and policy.tz) or rec.employee_id.tz or self.env.user.tz or self.env.company.partner_id.tz or 'UTC'
            try:
                local_tz = pytz.timezone(tz_name)
            except:
                local_tz = pytz.UTC
            
            # Saturday check
            work_end = policy.work_end
            if rec.date and rec.date.weekday() == 5:
                work_end = policy.work_end_saturday
                
            check_out_local = rec.last_check_out.replace(tzinfo=pytz.UTC).astimezone(local_tz)
            check_out_hour = check_out_local.hour + check_out_local.minute / 60.0
            
            # Check-out crossing midnight (next day)
            if check_out_local.date() > rec.date:
                check_out_hour += 24.0
                
            early_limit = work_end - (policy.early_leave_tolerance / 60.0)
            if check_out_hour < early_limit:
                rec.is_early_leave = True
                rec.early_leave_minutes = int((work_end - check_out_hour) * 60)

    @api.depends('attendance_status', 'employee_id.attendance_policy_id', 'date')
    def _compute_absent_hours(self):
        for rec in self:
            if rec.attendance_status == 'absent':
                policy = rec.employee_id.attendance_policy_id
                lunch_hour = (policy.lunch_duration / 60.0) if policy else 1.0
                work_start = policy.work_start if policy else 8.5
                work_end = policy.work_end if policy else 17.5
                
                # Saturday
                if rec.date and rec.date.weekday() == 5:
                    work_end = policy.work_end_saturday if policy else 13.0
                    lunch_hour = 0.0
                
                rec.absent_hours = max(0.0, work_end - work_start - lunch_hour)
            else:
                rec.absent_hours = 0.0

    @api.depends('last_check_out', 'employee_id.attendance_policy_id', 'manual_overtime', 'date', 'approval_state')
    def _compute_overtime(self):
        for rec in self:
            if rec.approval_state == 'refused':
                rec.overtime_hours = 0.0
                rec.ot_payable_hours = 0.0
                continue

            policy = rec.employee_id.attendance_policy_id

            # --- Determine raw OT hours ---
            if rec.manual_overtime > 0:
                # Manual override: use the claimed hours directly
                raw_ot_hours = rec.manual_overtime
                # For rate calculation we use a synthetic checkout at cutoff + manual hours
                cutoff_hour = policy.work_end if policy else 17.5
                if rec.date and rec.date.weekday() == 5 and policy:
                    cutoff_hour = policy.work_end_saturday
                dt_local = None  # No real checkout time for manual claims
                ot_start = cutoff_hour
            else:
                # AUTO CALCULATION
                if not policy or not policy.ot_apply or not rec.last_check_out:
                    rec.overtime_hours = 0.0
                    rec.ot_payable_hours = 0.0
                    continue

                # Timezone fallback: Policy > Employee > User > UTC
                tz_name = (policy.tz if policy else None) or rec.employee_id.tz or self.env.user.tz or 'UTC'
                try:
                    local_tz = pytz.timezone(tz_name)
                except Exception:
                    local_tz = pytz.UTC

                dt_local = rec.last_check_out.replace(tzinfo=pytz.UTC).astimezone(local_tz)
                check_out_hour = dt_local.hour + dt_local.minute / 60.0

                cutoff_hour = policy.work_end  # e.g. 17.5
                ot_start = policy.ot_start_time  # e.g. 17.516

                # Saturday: OT starts right after Saturday end time
                if rec.date and rec.date.weekday() == 5:
                    cutoff_hour = policy.work_end_saturday
                    ot_start = cutoff_hour + (1 / 60.0)

                # Handle checkout crossing midnight (next day)
                if dt_local.date() > rec.date:
                    check_out_hour += 24.0

                raw_ot_hours = 0.0
                if check_out_hour > ot_start:
                    raw_ot_hours = check_out_hour - ot_start
                    # Cap at the configured end limit
                    limit = policy.ot_end_limit
                    if limit < 12.0:
                        limit += 24.0  # limit is usually next morning (e.g. 6 → 30)
                    if check_out_hour > limit:
                        raw_ot_hours = limit - ot_start

                raw_ot_hours = max(0.0, raw_ot_hours)

            rec.overtime_hours = raw_ot_hours

            if raw_ot_hours <= 0 or not policy:
                rec.ot_payable_hours = 0.0
                continue

            # --- Calculate Payable Hours based on Rates ---
            weekday = rec.date.weekday() if rec.date else 0  # 0=Mon, 6=Sun
            is_holiday = False

            # Check Public Holidays via the employee's resource calendar
            if rec.employee_id.resource_calendar_id:
                leaves = rec.employee_id.resource_calendar_id.global_leave_ids
                for leave in leaves:
                    if leave.date_from.date() <= rec.date <= leave.date_to.date():
                        is_holiday = True
                        break

            # Base rate for the day type
            rate = policy.rate_weekday
            if is_holiday:
                rate = policy.rate_holiday
            elif weekday == 6:  # Sunday
                rate = policy.rate_sunday
            elif weekday == 5:  # Saturday
                rate = policy.rate_saturday

            # Iterate over time intervals to apply time-based rate overrides
            current = ot_start
            end = ot_start + raw_ot_hours

            points = [current, end]

            # Night start transition
            if current < policy.night_start < end:
                points.append(policy.night_start)

            # Saturday afternoon transition
            if weekday == 5 and not is_holiday:
                if current < policy.saturday_afternoon_start < end:
                    points.append(policy.saturday_afternoon_start)

            points = sorted(set(points))

            payable = 0.0
            for i in range(len(points) - 1):
                p_start = points[i]
                p_end = points[i + 1]
                duration = p_end - p_start
                interval_rate = rate

                # Saturday afternoon override
                if weekday == 5 and not is_holiday and p_start >= policy.saturday_afternoon_start:
                    interval_rate = max(interval_rate, policy.rate_saturday_afternoon)

                # Night rate override — handles windows crossing midnight
                night_s = policy.night_start
                night_e = policy.night_end
                is_night = False
                if night_s > night_e:  # Crosses midnight (e.g. 22 → 06)
                    # p_start can be > 24 when OT crosses into next day
                    norm = p_start % 24
                    if norm >= night_s or norm < night_e:
                        is_night = True
                else:
                    norm = p_start % 24
                    if night_s <= norm < night_e:
                        is_night = True

                if is_night:
                    interval_rate = max(interval_rate, policy.rate_night)

                payable += duration * interval_rate

            rec.ot_payable_hours = payable

    def action_manual_request(self):
        self.ensure_one()
        if self.manual_overtime > 0:
            self.overtime_hours = self.manual_overtime # Trigger compute/store
            self.approval_state = 'to_approve'

    def _compute_approval_stats(self):
        """Compute weekly and monthly OT totals for each record efficiently."""
        if not self:
            return

        # 1. Collect unique employees and date range from current set
        emp_ids = self.mapped('employee_id.id')
        dates = [rec.date for rec in self if rec.date]
        if not dates or not emp_ids:
            for rec in self:
                rec.ot_weekly_total = 0.0
                rec.ot_monthly_total = 0.0
            return

        min_date = min(dates)
        max_date = max(dates)

        # Expand range to cover full weeks/months
        start_week = min_date - timedelta(days=min_date.weekday())
        end_month_temp = max_date.replace(day=1) + timedelta(days=32)
        end_month = end_month_temp.replace(day=1) + timedelta(days=-1)

        # 2. Bulk fetch all attendance records for these employees in the range
        all_recs = self.search([
            ('employee_id', 'in', emp_ids),
            ('date', '>=', start_week),
            ('date', '<=', end_month),
        ])

        # 3. Build lookup dictionaries: { emp_id: { week_key: total, month_key: total } }
        stats = {emp_id: {'weekly': {}, 'monthly': {}} for emp_id in emp_ids}
        for att_rec in all_recs:
            emp_id = att_rec.employee_id.id
            if emp_id not in stats:
                continue

            if not att_rec.date:
                continue

            # Week key
            week_start = att_rec.date - timedelta(days=att_rec.date.weekday())
            week_key = week_start.isoformat()
            stats[emp_id]['weekly'][week_key] = stats[emp_id]['weekly'].get(week_key, 0.0) + att_rec.overtime_hours

            # Month key
            month_key = att_rec.date.strftime('%Y-%m')
            stats[emp_id]['monthly'][month_key] = stats[emp_id]['monthly'].get(month_key, 0.0) + att_rec.overtime_hours

        # 4. Assign values to records in self
        for rec in self:
            if not rec.date:
                rec.ot_weekly_total = 0.0
                rec.ot_monthly_total = 0.0
                continue

            emp_stats = stats.get(rec.employee_id.id, {'weekly': {}, 'monthly': {}})

            week_start = rec.date - timedelta(days=rec.date.weekday())
            rec.ot_weekly_total = emp_stats['weekly'].get(week_start.isoformat(), 0.0)

            month_key = rec.date.strftime('%Y-%m')
            rec.ot_monthly_total = emp_stats['monthly'].get(month_key, 0.0)

    def action_submit_ot(self):
        self.ensure_one()
        self.approval_state = 'to_approve'
        
    def action_first_approve(self):
        self.ensure_one()
        manager_user = self.employee_id.parent_id.user_id
        is_manager = manager_user and self.env.user == manager_user
        is_hr = self.env.user.has_group('hikvision_attendance.group_hikvision_hr')
        is_admin = self.env.user.has_group('hikvision_attendance.group_hikvision_admin')
        
        if not (is_manager or is_hr or is_admin):
            raise UserError(_("Only the employee's manager or an HR Manager can approve this request."))
            
        self.approval_state = 'second_approval'
        self.approver_ids = [Command.link(self.env.user.id)]

    def action_second_approve(self):
        self.ensure_one()
        is_hr = self.env.user.has_group('hikvision_attendance.group_hikvision_hr')
        is_admin = self.env.user.has_group('hikvision_attendance.group_hikvision_admin')
        
        if not (is_hr or is_admin):
            raise UserError(_("Only an HR Manager or Administrator can perform the final approval."))
            
        self.approval_state = 'approved'
        self.approver_ids = [Command.link(self.env.user.id)]
        
    def action_refuse_ot(self):
        self.ensure_one()
        manager_user = self.employee_id.parent_id.user_id
        is_manager = manager_user and self.env.user == manager_user
        is_hr = self.env.user.has_group('hikvision_attendance.group_hikvision_hr')
        is_admin = self.env.user.has_group('hikvision_attendance.group_hikvision_admin')
        
        if not (is_manager or is_hr or is_admin):
            raise UserError(_("Only the employee's manager or an HR Manager can refuse this request."))
            
        self.approval_state = 'refused'
        self.overtime_hours = 0.0
        self.ot_payable_hours = 0.0
