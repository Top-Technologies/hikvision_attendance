from odoo import http
from datetime import date

class Dashboard(http.Controller):

    @http.route('/hikvision/dashboard', auth='public', website=True)
    def show_dashboard(self):
        today = date.today()
        logs = http.request.env['hikvision.attendance'].sudo().search([('date', '=', today)])
        return http.request.render("hikvision_attendance.dashboard_page", {
            "logs": logs,
            "today": today
        })
