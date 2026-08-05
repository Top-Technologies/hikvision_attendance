# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class HikvisionSyncLog(models.Model):
    _name = 'hikvision.sync.log'
    _description = 'Attendance Device Synchronization Log'
    _order = 'sync_date desc'

    device_id = fields.Many2one(
        'hikvision.device', string='Device',
        required=True, index=True, ondelete='cascade'
    )
    device_location = fields.Char(
        string='Location',
        related='device_id.location',
        store=True
    )
    sync_date = fields.Date(string='Sync Date', required=True, default=fields.Date.today, index=True)
    sync_datetime = fields.Datetime(string='Sync Time', default=fields.Datetime.now)
    triggered_by = fields.Many2one('res.users', string='Triggered By', default=lambda self: self.env.user)

    # Date range fetched
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    # Results
    records_fetched = fields.Integer(string='Records Fetched', default=0)
    records_created = fields.Integer(string='New Records Created', default=0)
    records_updated = fields.Integer(string='Records Updated', default=0)
    skipped_count = fields.Integer(string='Skipped (No Match)', default=0)

    # Status
    status = fields.Selection([
        ('success', 'Success'),
        ('partial', 'Partial'),
        ('failed', 'Failed'),
    ], string='Status', required=True, default='success')
    error_message = fields.Text(string='Error / Notes')
    duration_seconds = fields.Float(string='Duration (seconds)', digits=(6, 1))

    # Method used
    sync_mode = fields.Selection([
        ('direct', 'Direct'),
        ('bridge', 'Bridge'),
        ('chunked', 'Chunked'),
        ('cron', 'Scheduled Cron'),
    ], string='Sync Mode', default='direct')

    # ========================================================================
    # PHASE 4: AUTOMATED CRON METHODS
    # ========================================================================

    @api.model
    def action_cron_cleanup_old_logs(self):
        """
        Cron method: Delete sync logs older than 6 months
        Runs monthly on 15th at 3 AM
        """
        try:
            # Calculate cutoff date (6 months ago)
            cutoff_date = date.today() - timedelta(days=180)  # ~6 months
            
            _logger.info(f"[CRON] Cleaning up sync logs older than {cutoff_date}")
            
            # Find old logs
            old_logs = self.search([
                ('sync_date', '<', cutoff_date),
            ])
            
            if not old_logs:
                _logger.info("[CRON] No old sync logs to cleanup")
                return True
            
            count = len(old_logs)
            old_logs.unlink()
            
            _logger.info(f"[CRON] Successfully deleted {count} old sync logs")
            return True
            
        except Exception as e:
            _logger.error(f"[CRON] Error cleaning up sync logs: {str(e)}")
            return False
