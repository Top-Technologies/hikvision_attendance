from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta


class FetchLogsWizard(models.TransientModel):
    _name = 'hikvision.fetch.logs.wizard'
    _description = 'Fetch Logs Wizard'

    device_id = fields.Many2one('hikvision.device', string='Device', required=True)
    date_range = fields.Selection([
        ('today', 'Today'),
        ('yesterday', 'Yesterday'),
        ('last_7_days', 'Last 7 Days'),
        ('last_30_days', 'Last 30 Days'),
        ('last_90_days', 'Last 90 Days'),
        ('custom', 'Custom Range'),
    ], string='Date Range', default='last_7_days', required=True)
    
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    
    use_chunking = fields.Boolean(
        string='Use Chunked Fetching',
        default=True,
        help='Split large date ranges into smaller chunks to prevent 401 errors and ensure complete data retrieval. Recommended for date ranges larger than 7 days.'
    )
    chunk_days = fields.Integer(
        string='Days per Chunk',
        default=7,
        help='Number of days to fetch in each chunk. Smaller values are more reliable but slower.'
    )

    @api.onchange('date_range')
    def _onchange_date_range(self):
        """Set start and end dates based on selected range."""
        today = fields.Date.context_today(self)
        if self.date_range == 'today':
            self.start_date = today
            self.end_date = today
        elif self.date_range == 'yesterday':
            yesterday = today - timedelta(days=1)
            self.start_date = yesterday
            self.end_date = yesterday
        elif self.date_range == 'last_7_days':
            self.start_date = today - timedelta(days=7)
            self.end_date = today
        elif self.date_range == 'last_30_days':
            self.start_date = today - timedelta(days=30)
            self.end_date = today
        elif self.date_range == 'last_90_days':
            self.start_date = today - timedelta(days=90)
            self.end_date = today
        elif self.date_range == 'custom':
            # Keep existing dates or set defaults
            if not self.start_date:
                self.start_date = today - timedelta(days=7)
            if not self.end_date:
                self.end_date = today

    def action_fetch_logs(self):
        """Fetch logs for the selected date range."""
        self.ensure_one()
        
        if not self.start_date or not self.end_date:
            raise UserError(_("Please select both start and end dates."))
        
        if self.start_date > self.end_date:
            raise UserError(_("Start date cannot be after end date."))
        
        # Use chunked fetching if enabled
        if self.use_chunking:
            return self.device_id.action_fetch_logs_chunked(
                self.start_date, 
                self.end_date, 
                chunk_days=self.chunk_days
            )
        else:
            return self.device_id.action_fetch_logs_by_date(self.start_date, self.end_date)
