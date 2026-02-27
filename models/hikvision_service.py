from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
from requests.auth import HTTPDigestAuth
import logging

_logger = logging.getLogger(__name__)

DEVICE_IP = "192.168.30.138"
DEVICE_USER = "admin"
DEVICE_PASS = "Carpedium1"


class HikvisionUser(models.Model):
    _name = "hikvision.user"
    _description = "Hikvision Employee"

    employee_id = fields.Char(string="Employee ID", required=True, copy=False)
    employee_no = fields.Char(string="Employee No", related='employee_id', store=False)  # Alias for compatibility
    name = fields.Char(string="Name")
    odoo_employee_id = fields.Many2one('hr.employee', string="Odoo Employee")
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

    def _get_session(self, username, password):
        """Create a requests Session with correct auth and headers."""
        session = requests.Session()
        session.auth = HTTPDigestAuth(username, password)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*, application/json'
        })
        return session

    def fetch_all_users(self):
        """Fetch users from Hikvision device using robust Auth."""
        self.ensure_one()
        
        # Determine connection details based on mode
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

        base_url = f"http://{ip}:{port}"
        # Some devices require format=json, others might differ, but assuming valid based on previous code
        url = f"{base_url}/ISAPI/AccessControl/UserInfo/Search?format=json"
        
        User = self.env["hikvision.user"]
        total_count = 0
        search_position = 0
        has_more = True
        
        # Create session
        try:
             with self._get_session(username, password) as session:
                session.headers.update({"Content-Type": "application/json"})
                
                while has_more:
                    payload = {
                        "UserInfoSearchCond": {
                            "searchID": "1",
                            "searchResultPosition": search_position,
                            "maxResults": 30
                        }
                    }
                    
                    _logger.info(f"Syncing users batch starting at position {search_position}...")
                    
                    response = session.post(
                        url,
                        json=payload,
                        timeout=30
                    )
                    
                    # Check for 401 and try Basic Auth fallback if needed
                    if response.status_code == 401:
                        _logger.warning("Digest Auth failed (401). Retrying with Basic Auth...")
                        from requests.auth import HTTPBasicAuth
                        response = requests.post(
                            url,
                            auth=HTTPBasicAuth(username, password),
                            headers=session.headers,
                            json=payload,
                            timeout=30
                        )
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    user_info_search = data.get("UserInfoSearch", {})
                    user_list = user_info_search.get("UserInfo", [])
                    
                    # Handle single dict response
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
                        
                        # Extract Validity
                        valid_dict = u.get("Valid", {})
                        begin_str = valid_dict.get("beginTime")
                        end_str = valid_dict.get("endTime")
                        
                        vals = {
                            "name": name,
                        }
                        
                        # Parse datetime with timezone handling
                        from dateutil import parser
                        import pytz
                        
                        if begin_str:
                            try:
                                dt = parser.parse(begin_str)
                                if dt.tzinfo:
                                    dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                                vals["begin_time"] = dt
                            except Exception:
                                pass

                        if end_str:
                            try:
                                dt = parser.parse(end_str)
                                if dt.tzinfo:
                                    dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
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
                    
                    # Check for more
                    response_status = user_info_search.get("responseStatusStrg", "OK")
                    num_of_matches = user_info_search.get("numOfMatches", 0)
                    
                    matches_in_batch = int(num_of_matches) if num_of_matches else batch_count
                    search_position += matches_in_batch
                    
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
        # This calls fetch_all_users which will now use the wizard's configuration
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
                # Fetch last 3 days to catch up on weekend/missed data
                device.action_fetch_logs_by_date(three_days_ago, today)
            except Exception as e:
                _logger.error(f"Cron: Failed to fetch logs for {device.name}: {e}")
