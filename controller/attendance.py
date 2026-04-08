def _toggle_attendance(self, employee):
    Attendance = request.env['hr.attendance'].sudo()
    HikAttendance = request.env['hikvision.attendance'].sudo()

    now = fields.Datetime.now()
    today = fields.Date.today()

    # Check HR attendance
    last_attendance = Attendance.search(
        [('employee_id', '=', employee.id)],
        order="check_in desc",
        limit=1
    )

    # Check Hikvision attendance summary record for today
    day_record = HikAttendance.search([
        ('employee_id', '=', employee.id),
        ('date', '=', today)
    ], limit=1)

    # === CHECK OUT ===
    if last_attendance and not last_attendance.check_out:
        # Update hr.attendance
        last_attendance.check_out = now

        # Update hikvision.attendance summary
        if day_record:
            day_record.last_check_out = now
            day_record.status = 'out'

    # === CHECK IN ===
    else:
        # Create new hr.attendance
        Attendance.create({
            'employee_id': employee.id,
            'check_in': now,
        })

        # Create or update hikvision.attendance summary
        if not day_record:
            HikAttendance.create({
                'employee_id': employee.id,
                'date': today,
                'first_check_in': now,
                'status': 'in'
            })
        else:
            day_record.last_check_out = False
            day_record.status = 'in'
