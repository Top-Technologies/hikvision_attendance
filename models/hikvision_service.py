from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
from requests.auth import HTTPDigestAuth
import logging
from dateutil import parser
import pytz
from datetime import timedelta

_logger = logging.getLogger(__name__)


class HikvisionUser(models.Model):
    _name = "hikvision.user"
    _description = "Hikvision Employee"

    employee_id = fields.Char(string="Employee ID", required=True, copy=False)
    employee_no = fields.Char(string="Employee No", compute='_compute_employee_no')  # Alias for compatibility
    name = fields.Char(string="Name")

    def _compute_employee_no(self):
        for rec in self:
            rec.employee_no = rec.employee_id
    odoo_employee_id = fields.Many2one('hr.employee', string="Odoo Employee")
    company_id = fields.Many2one('res.company', string='Company', related='odoo_employee_id.company_id', store=True)
    begin_time = fields.Datetime(string="Begin Time")
    end_time = fields.Datetime(string="End Time")


class HikvisionService(models.TransientModel):
    _name = "hikvision.service"
    _description = "Hikvision Device Service"

    sync_mode = fields.Selection([
        ('auto', 'From Configuration'),
        ('manual', 'Manual Input')
    ], string="Sync Mode", default='auto', required=True)

    device_id = fields.Many2one('hikvision.device', string="Device")

    manual_ip = fields.Char(string="Device IP")
    manual_port = fields.Integer(string="Port", default=80)
    manual_username = fields.Char(string="Username")
    manual_password = fields.Char(string="Password")

    def _get_auth(self, username, password):
        """Get HTTPDigestAuth for stateless requests"""
        return HTTPDigestAuth(username, password)

    def _get_headers(self):
        """Get standard headers for requests"""
        return {
            'User-Agent': 'HikvisionBridge/1.0',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Connection': 'close'  # Important for Hikvision devices
        }

    def fetch_all_users(self):
        """Fetch users from Hikvision device using robust Auth."""
        self.ensure_one()

        # --- BRIDGE MODE LOGIC START ---
        if self.sync_mode == 'auto' and self.device_id and self.device_id.connection_mode == 'bridge':
            _logger.info(f"Fetching users via bridge for device {self.device_id.name}")

            if not self.device_id.bridge_url or not self.device_id.bridge_token or not self.device_id.bridge_device_id:
                raise UserError("Bridge configuration incomplete on the device record.")

            import time
            import json

            try:
                # 1. Submit sync_users command to bridge
                response = requests.post(
                    f"{self.device_id.bridge_url}/api/v1/commands",
                    headers={
                        'Authorization': f'Bearer {self.device_id.bridge_token}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        'device_id': self.device_id.bridge_device_id,
                        'operation': 'sync_users',
                        'parameters': {'max_results': 1000}
                    },
                    timeout=120
                )
                if response.status_code != 201:
                    raise UserError(f"Bridge error: {response.text}")

                command_id = response.json()['command_id']

                # 2. Poll for result
                max_wait = 300
                start_time = time.time()
                while time.time() - start_time < max_wait:
                    res_response = requests.get(
                        f"{self.device_id.bridge_url}/api/v1/commands/{command_id}",
                        headers={'Authorization': f'Bearer {self.device_id.bridge_token}'},
                        timeout=120
                    )
                    res_data = res_response.json()
                    if res_data['status'] == 'completed':
                        result = json.loads(res_data['result'])
                        if not result.get('success'):
                            raise UserError(f"Bridge sync failed: {result.get('error')}")

                        # Process users from bridge result
                        user_list = result.get('users', [])
                        User = self.env["hikvision.user"]
                        total_count = 0
                        for u in user_list:
                            emp_id = u.get("employeeNo")
                            if not emp_id: continue

                            vals = {"name": u.get("name", "Unknown")}
                            valid_dict = u.get("Valid", {})
                            begin_str = valid_dict.get("beginTime")
                            end_str = valid_dict.get("endTime")

                            offset = self.device_id.time_offset or 0.0
                            for field, val_str in [("begin_time", begin_str), ("end_time", end_str)]:
                                if val_str:
                                    try:
                                        dt = parser.parse(val_str)
                                        if dt.tzinfo: dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                                        if offset: dt += timedelta(hours=offset)
                                        vals[field] = dt
                                    except: pass

                            user = User.search([("employee_id", "=", emp_id)], limit=1)
                            if user: user.write(vals)
                            else:
                                vals["employee_id"] = emp_id
                                User.create(vals)
                            total_count += 1

                        return {
                            "type": "ir.actions.client",
                            "tag": "display_notification",
                            "params": {
                                "title": "Success",
                                "message": f"{total_count} users synced via bridge.",
                                "type": "success",
                            }
                        }
                    elif res_data['status'] == 'failed':
                        raise UserError(f"Bridge sync failed: {res_data.get('error')}")
                    time.sleep(2)
                raise UserError("Bridge sync timeout after 5 minutes")
            except Exception as e:
                raise UserError(f"Bridge communication error during sync: {e}")
        # --- BRIDGE MODE LOGIC END ---

        # Original Direct Connection Logic
        if self.sync_mode == 'auto':
            if not self.device_id:
                raise UserError("Please select a device.")
            ip = self.device_id.ip_address
            port = self.device_id.port
            username = self.device_id.username
            password = self.device_id.password
        else:
            if not self.manual_ip or not self.manual_username or not self.manual_password:
                raise UserError("Please fill in all manual connection details.")
            ip = self.manual_ip
            port = self.manual_port
            username = self.manual_username
            password = self.manual_password

        # Use direct device connection (not proxy)
        base_url = f"http://{ip}:{port}"
        url = f"{base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"

        User = self.env["hikvision.user"]
        total_count = 0
        search_position = 0
        has_more = True

        # Create auth
        auth = self._get_auth(username, password)
        headers = self._get_headers()

        try:
            while has_more:
                payload = {
                    "UserInfoSearchCond": {
                        "searchID": "1",
                        "searchResultPosition": search_position,
                        "maxResults": 30
                    }
                }

                _logger.info(f"Syncing users batch starting at position {search_position}...")

                response = requests.post(
                    url,
                    json=payload,
                    auth=auth,
                    headers=headers,
                    timeout=30
                )

                response.raise_for_status()
                data = response.json()

                user_info_search = data.get("UserInfoSearch", {})
                user_list = user_info_search.get("UserInfo", [])

                if isinstance(user_list, dict):
                    user_list = [user_list]

                batch_count = len(user_list)
                _logger.info(f"Hikvision Sync Batch: Found {batch_count} users.")

                if batch_count == 0:
                     has_more = False
                     break

                for u in user_list:
                    emp_id = u.get("employeeNo")
                    name = u.get("name", "Unknown")
                    if not emp_id:
                        continue

                    valid_dict = u.get("Valid", {})
                    begin_str = valid_dict.get("beginTime")
                    end_str = valid_dict.get("endTime")

                    vals = {"name": name}

                    offset = self.device_id.time_offset if self.sync_mode == 'auto' and self.device_id else 0.0

                    if begin_str:
                        try:
                            dt = parser.parse(begin_str)
                            if dt.tzinfo:
                                dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                            if offset:
                                dt += timedelta(hours=offset)
                            vals["begin_time"] = dt
                        except Exception:
                            pass

                    if end_str:
                        try:
                            dt = parser.parse(end_str)
                            if dt.tzinfo:
                                dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                            if offset:
                                dt += timedelta(hours=offset)
                            vals["end_time"] = dt
                        except Exception:
                            pass

                    user = User.search([("employee_id", "=", emp_id)], limit=1)
                    if user:
                        user.write(vals)
                    else:
                        vals["employee_id"] = emp_id
                        User.create(vals)
                    total_count += 1

                response_status = user_info_search.get("responseStatusStrg", "OK")
                num_of_matches = user_info_search.get("numOfMatches", 0)

                search_position += batch_count

                if response_status != 'MORE':
                    has_more = False

                if total_count > 2000:
                    _logger.warning("Sync limit reached (2000 users). Stopping.")
                    break

        except Exception as e:
            raise UserError(f"Failed to communicate with device: {e}")

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Success",
                "message": f"{total_count} users synced from device.",
                "type": "success",
            }
        }

    def action_sync_and_open_users(self):
        """Sync users from device and open the user list"""
        self.fetch_all_users()

        return {
            "type": "ir.actions.act_window",
            "name": "Device Users",
            "res_model": "hikvision.user",
            "view_mode": "list,form",
        }

    @api.model
    def action_cron_fetch_all(self):
        """Scheduled action to fetch logs from all connected devices."""
        from datetime import datetime, timedelta

        devices = self.env['hikvision.device'].search([('status', '!=', 'error')])

        today = fields.Date.today()
        three_days_ago = today - timedelta(days=3)

        for device in devices:
            try:
                _logger.info(f"Cron: Fetching logs for device {device.name} (Last 3 days)")
                device.action_fetch_logs_by_date(three_days_ago, today)
            except Exception as e:
                _logger.error(f"Cron: Failed to fetch logs for {device.name}: {e}")
