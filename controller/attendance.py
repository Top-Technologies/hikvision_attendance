from odoo import http, fields
from odoo.http import request


class HikvisionAttendanceController(http.Controller):

    @http.route('/hikvision/toggle_attendance', auth='user', type='jsonrpc', methods=['POST'])
    def toggle_attendance(self):
        """Toggle attendance (check-in / check-out) for the currently logged-in employee."""
        employee = request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )
        if not employee:
            return {'error': 'No employee linked to the current user.'}

        self._toggle_attendance(employee)
        return {'success': True}

    def _toggle_attendance(self, employee):
        """Internal: toggle check-in/check-out for the given employee."""
        Attendance = request.env['hr.attendance'].sudo()
        HikAttendance = request.env['hikvision.attendance'].sudo()

        now = fields.Datetime.now()
        today = fields.Date.today()

        # Check HR attendance
        last_attendance = Attendance.search(
            [('employee_id', '=', employee.id)],
            order='check_in desc',
            limit=1,
        )

        # Check Hikvision attendance summary record for today
        day_record = HikAttendance.search([
            ('employee_id', '=', employee.id),
            ('date', '=', today),
        ], limit=1)

        # === CHECK OUT ===
        if last_attendance and not last_attendance.check_out:
            last_attendance.check_out = now

            if day_record:
                day_record.last_check_out = now
                day_record.status = 'out'

        # === CHECK IN ===
        else:
            Attendance.create({
                'employee_id': employee.id,
                'check_in': now,
            })

            if not day_record:
                HikAttendance.create({
                    'employee_id': employee.id,
                    'date': today,
                    'first_check_in': now,
                    'status': 'in',
                })
            else:
                day_record.last_check_out = False
                day_record.status = 'in'
