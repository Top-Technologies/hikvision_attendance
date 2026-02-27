from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
from requests.auth import HTTPDigestAuth
import threading
import time
import logging
import json
import xml.etree.ElementTree as ET

_logger = logging.getLogger(__name__)

class HikvisionDevice(models.Model):
    _name = 'hikvision.device'
    _description = 'Hikvision Device'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Device Name', required=True, tracking=True)
    ip_address = fields.Char(string='IP Address', required=True, tracking=True)
    port = fields.Integer(string='Port', default=80, required=True, tracking=True)
    username = fields.Char(string='Username', required=True, tracking=True)
    password = fields.Char(string='Password', required=True)
    
    status = fields.Selection([
        ('disconnected', 'Disconnected'),
        ('connected', 'Connected'),
        ('error', 'Error')
    ], string='Status', default='disconnected', tracking=True)
    
    last_heartbeat = fields.Datetime(string='Last Heartbeat', readonly=True)
    is_streaming = fields.Boolean(string='Is Streaming', default=False, tracking=True)
    event_log_ids = fields.One2many('hikvision.event.log', 'device_id', string='Event Logs')

    def _get_api_url(self, endpoint):
        return f"http://{self.ip_address}:{self.port}/{endpoint}"

    def _get_session(self):
        """Create a requests Session with correct auth and headers."""
        session = requests.Session()
        session.auth = HTTPDigestAuth(self.username, self.password)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*'
        })
        return session

    def action_test_connection(self):
        self.ensure_one()
        url = self._get_api_url("ISAPI/System/deviceInfo")
        try:
            # Use session to handle cookies/headers properly during auth challenge
            with self._get_session() as session:
                response = session.get(url, timeout=10)
                
                if response.status_code == 401:
                    # Provide more detail if 401 persists
                    header = response.headers.get('WWW-Authenticate', 'N/A')
                    raise UserError(_("Authentication failed (401). Check username/password. Device asked for: %s") % header)
                
                response.raise_for_status()
                
                self.status = 'connected'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('Connection successful!'),
                        'type': 'success',
                    }
                }
        except Exception as e:
            self.status = 'error'
            raise UserError(_("Connection failed: %s") % str(e))

    def action_start_stream(self):
        self.ensure_one()
        if self.is_streaming:
            return
        
        # Start the thread
        thread = threading.Thread(target=self._stream_listener_thread, args=(self.id,), daemon=True)
        thread.start()
        self.is_streaming = True
        self.status = 'connected'

    def action_stop_stream(self):
        self.ensure_one()
        self.is_streaming = False
        self.status = 'disconnected'

    def action_reboot_device(self):
        """Reboot the Hikvision device."""
        self.ensure_one()
        url = self._get_api_url("ISAPI/System/reboot")
        try:
            with self._get_session() as session:
                response = session.put(
                    url,
                    timeout=10
                )
            if response.status_code in [200, 201]:
                self.is_streaming = False
                self.status = 'disconnected'
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Device Rebooting'),
                        'message': _('Device is rebooting. Please wait 1-2 minutes before reconnecting.'),
                        'type': 'success',
                    }
                }
            else:
                raise UserError(_("Reboot failed: %s") % response.text)
        except requests.exceptions.RequestException as e:
            raise UserError(_("Reboot failed: %s") % str(e))

    def action_fetch_logs(self):
        """Fetch attendance logs from the device and import into Odoo."""
        self.ensure_one()
        url = self._get_api_url("ISAPI/AccessControl/AcsEvent?format=json")
        
        # Search for events from the last 30 days
        import datetime
        end_time = datetime.datetime.now()
        start_time = end_time - datetime.timedelta(days=30)
        
        success = False
        events = []
        
        # Define strategies to try
        strategies = [
            {
                "name": "UTC Time, Major 0 (All)",
                "payload": {
                    "AcsEventCond": {
                        "searchID": "odoo-fetch-logs-1",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "major": 0, 
                        "minor": 0,
                        "startTime": start_time.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "endTime": end_time.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                }
            },
            {
                "name": "Local Time, No Major/Minor",
                "payload": {
                    "AcsEventCond": {
                        "searchID": "odoo-fetch-logs-2",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "startTime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "endTime": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                }
            },
            {
                "name": "Timezone Offset, Major 5 (Access)",
                "payload": {
                    "AcsEventCond": {
                        "searchID": "odoo-fetch-logs-3",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "major": 5,
                        "minor": 0,
                        "startTime": start_time.strftime("%Y-%m-%dT00:00:00+03:00"),
                        "endTime": end_time.strftime("%Y-%m-%dT23:59:59+03:00"),
                    }
                }
            }
        ]
        
        last_error = None
        
        # Use session for connection reuse and proper headers
        with self._get_session() as session:
            session.headers.update({"Content-Type": "application/json"})
            
            for strategy in strategies:
                _logger.info(f"Trying fetch strategy: {strategy['name']}")
                try:
                    response = session.post(
                        url,
                        json=strategy['payload'],
                        timeout=30
                    )
                
                    if response.status_code == 200:
                        data = response.json()
                        events = data.get('AcsEvent', {}).get('InfoList', [])
                        success = True
                        _logger.info(f"Strategy '{strategy['name']}' succeeded! Fetched {len(events)} events.")
                        break
                    else:
                        _logger.warning(f"Strategy '{strategy['name']}' failed with {response.status_code}: {response.text}")
                        if response.status_code == 401:
                             _logger.warning(f"Auth failed with Digest. Headers: {response.headers}")
                             # Try fallback to Basic Auth
                             try:
                                 from requests.auth import HTTPBasicAuth
                                 _logger.info("Retrying with Basic Auth...")
                                 basic_response = requests.post(
                                     url,
                                     json=strategy['payload'],
                                     auth=HTTPBasicAuth(self.username, self.password),
                                     timeout=30,
                                     headers=session.headers
                                 )
                                 if basic_response.status_code == 200:
                                     response = basic_response
                                     _logger.info("Basic Auth succeeded!")
                                     data = response.json()
                                     events = data.get('AcsEvent', {}).get('InfoList', [])
                                     success = True
                                     _logger.info(f"Strategy '{strategy['name']}' succeeded! Fetched {len(events)} events.")
                                     break
                                 else:
                                     _logger.warning(f"Basic Auth failed with {basic_response.status_code}: {basic_response.text}")
                             except Exception as e:
                                 _logger.error(f"Basic Auth retry failed: {e}")

                        last_error = f"{response.status_code} {response.text}"
                    
                except Exception as e:
                    _logger.warning(f"Strategy '{strategy['name']}' exception: {e}")
                    last_error = str(e)
        
        if not success:
             _logger.error("All fetch strategies failed.")
             # Try fallback as last resort
             try:
                 return self._fetch_logs_fallback(start_time, end_time)
             except Exception as fallback_e:
                 raise UserError(_("Failed to fetch logs. Device rejected all payload formats. Last error: %s") % last_error)

        # Process events if success
        if success:
            _logger.info(f"Processing {len(events)} events...")
            _logger.info(f"Fetched {len(events)} events from device")
            
            imported_count = 0
            for event in events:
                try:
                    employee_no = event.get('employeeNoString') or str(event.get('employeeNo', ''))
                    if not employee_no or employee_no == '0':
                        continue
                    
                    time_str = event.get('time', '')
                    if not time_str:
                        continue
                    
                    # Parse datetime
                    from dateutil import parser
                    import pytz
                    dt = parser.parse(time_str)
                    if dt.tzinfo:
                        dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                    
                    # Find employee
                    employee = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
                    if not employee:
                        hik_user = self.env['hikvision.user'].search([('employee_id', '=', employee_no)], limit=1)
                        if hik_user and hik_user.odoo_employee_id:
                            employee = hik_user.odoo_employee_id
                    
                    if not employee:
                        continue
                    
                    # Check if event already exists (by timestamp and employee)
                    existing = self.env['hikvision.event.log'].search([
                        ('device_id', '=', self.id),
                        ('employee_id', '=', employee.id),
                        ('timestamp', '=', dt)
                    ], limit=1)
                    
                    if existing:
                        continue
                    
                    # Create event log
                    self.env['hikvision.event.log'].create({
                        'device_id': self.id,
                        'timestamp': dt,
                        'event_type': 'AccessControllerEvent',
                        'employee_no': employee_no,
                        'employee_id': employee.id,
                        'raw_data': json.dumps(event),
                    })
                    
                    # Create attendance records
                    event_date = dt.date()
                    
                    # Update hikvision.attendance daily summary
                    HikAttendance = self.env['hikvision.attendance']
                    day_record = HikAttendance.search([
                        ('employee_id', '=', employee.id),
                        ('date', '=', event_date)
                    ], limit=1)
                    
                    if not day_record:
                        HikAttendance.create({
                            'employee_id': employee.id,
                            'date': event_date,
                            'first_check_in': dt,
                            'status': 'in'
                        })
                    else:
                        # Update last_check_out if this is later
                        if not day_record.last_check_out or dt > day_record.last_check_out:
                            day_record.write({
                                'last_check_out': dt,
                                'status': 'out'
                            })
                    
                    imported_count += 1
                    
                except Exception as e:
                    _logger.error(f"Error importing event: {e}")
                    continue
            
            # Ensure all employees have records for the fetched period (last 30 days)
            self._ensure_complete_attendance(start_time.date(), end_time.date())
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Logs Fetched'),
                    'message': _('%s events imported from device.') % imported_count,
                    'type': 'success',
                }
            }
            


    def action_open_fetch_logs_wizard(self):
        """Open the wizard to select date range for fetching logs."""
        self.ensure_one()
        return {
            'name': _('Fetch Logs'),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.fetch.logs.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_device_id': self.id,
            },
        }

    def action_fetch_logs_by_date(self, start_date, end_date):
        """Fetch attendance logs from the device for a specific date range."""
        self.ensure_one()
        url = self._get_api_url("ISAPI/AccessControl/AcsEvent?format=json")
        
        # Prepare datetime objects for strategies
        import datetime
        try:
            # Handles YYYY-MM-DD string or date objects
            if isinstance(start_date, str):
                start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            else:
                start_dt = datetime.datetime.combine(start_date, datetime.time.min)
                
            if isinstance(end_date, str):
                end_dt = datetime.datetime.strptime(end_date, "%Y-%m-%d")
            else:
                end_dt = datetime.datetime.combine(end_date, datetime.time.max)
        except Exception as e:
            raise UserError(f"Invalid date format: {e}")

        success = False
        events = []
        active_strategy = None
        
        strategies = [
            {
                "name": "UTC Time, Major 0",
                "payload": {
                    "AcsEventCond": {
                        "searchID": "odoo-fetch-logs-1",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "major": 0, 
                        "minor": 0,
                        "startTime": start_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "endTime": end_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                }
            },
            {
                "name": "Local Time, No Major/Minor",
                "payload": {
                    "AcsEventCond": {
                        "searchID": "odoo-fetch-logs-2",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "startTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                        "endTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                }
            },
               {
                "name": "Timezone Offset, Major 5",
                "payload": {
                    "AcsEventCond": {
                        "searchID": "odoo-fetch-logs-3",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "major": 5,
                        "minor": 0,
                        "startTime": start_dt.strftime("%Y-%m-%dT00:00:00+03:00"),
                        "endTime": end_dt.strftime("%Y-%m-%dT23:59:59+03:00"),
                    }
                }
            }
        ]
        
        last_error = None
        
        # Use a session to maintain connection and auth cookies (prevents lockout)
        with self._get_session() as session:
            session.headers.update({"Content-Type": "application/json"})
            
            # 1. First Pass: Find a working strategy
            for strategy in strategies:
                _logger.info(f"Trying fetch strategy: {strategy['name']}")
                try:
                    response = session.post(
                        url,
                        json=strategy['payload'],
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        batch = data.get('AcsEvent', {}).get('InfoList', [])
                        events.extend(batch)
                        success = True
                        active_strategy = strategy
                        _logger.info(f"Strategy '{strategy['name']}' succeeded! Fetched initial {len(batch)} events.")
                        break
                    else:
                        _logger.warning(f"Strategy '{strategy['name']}' failed with {response.status_code}: {response.text}")
                        last_error = f"{response.status_code} {response.text}"
                        
                        # If 401, we might be locked out or wrong password. Break to avoid spamming?
                        # But we have multiple strategies. Continue but sleep?
                        if response.status_code == 401:
                             time.sleep(1) 
                             
                except Exception as e:
                    _logger.warning(f"Strategy '{strategy['name']}' exception: {e}")
                    last_error = str(e)
            
            # 2. Pagination Loop (if initial fetch was successful)
            if success and active_strategy:
                # Assuming batch is result from previous call
                last_batch_size = len(events)
                current_position = active_strategy['payload']['AcsEventCond']['searchResultPosition']
                
                # Continue fetching as long as we got some data
                loop_count = 0
                while last_batch_size > 0 and loop_count < 100:
                    loop_count += 1
                    
                    # Polite delay to avoid device CPU spike or Rate Limiting
                    time.sleep(0.5) 
                    
                    current_position += last_batch_size
                    active_strategy['payload']['AcsEventCond']['searchResultPosition'] = current_position
                    
                    _logger.info(f"Pagination: Fetching next batch starting at {current_position}...")
                    
                    try:
                        response = session.post(
                            url,
                            json=active_strategy['payload'],
                            timeout=45
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            batch = data.get('AcsEvent', {}).get('InfoList', [])
                            batch_size = len(batch)
                            
                            if batch_size > 0:
                                events.extend(batch)
                                _logger.info(f"Fetched {batch_size} more events. Total: {len(events)}")
                            
                            last_batch_size = batch_size
                            
                            if batch_size == 0:
                                break
                                
                        else:
                            _logger.warning(f"Pagination request failed: {response.status_code}. Info: {response.text}")
                            break
                            
                    except Exception as e:
                        _logger.error(f"Pagination error: {e}")
                        break
        
        if not success:
            _logger.error("All fetch strategies failed.")
            try:
                 return self._fetch_logs_fallback(start_dt, end_dt)
            except:
                 raise UserError(_("Failed to fetch logs. Device rejected all payload formats. Last error: %s") % last_error)

        # Continue with processing if success
        if success:
            _logger.info(f"Processing total {len(events)} events...")
            
            imported_count = 0
            skipped_no_employee = []
            
            for event in events:
                try:
                    employee_no = event.get('employeeNoString') or str(event.get('employeeNo', ''))
                    if not employee_no or employee_no == '0':
                        continue
                    
                    time_str = event.get('time', '')
                    if not time_str:
                        continue
                    
                    from dateutil import parser
                    import pytz
                    dt = parser.parse(time_str)
                    if dt.tzinfo:
                        dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                    
                    employee = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
                    if not employee:
                        hik_user = self.env['hikvision.user'].search([('employee_id', '=', employee_no)], limit=1)
                        if hik_user and hik_user.odoo_employee_id:
                            employee = hik_user.odoo_employee_id
                    
                    if not employee:
                        if employee_no not in skipped_no_employee:
                            skipped_no_employee.append(employee_no)
                            _logger.warning(f"SKIPPED: No employee found with barcode/ID '{employee_no}'")
                        continue
                    
                    existing = self.env['hikvision.event.log'].search([
                        ('device_id', '=', self.id),
                        ('employee_id', '=', employee.id),
                        ('timestamp', '=', dt)
                    ], limit=1)
                    
                    if existing:
                        continue
                    
                    self.env['hikvision.event.log'].create({
                        'device_id': self.id,
                        'timestamp': dt,
                        'event_type': 'AccessControllerEvent',
                        'employee_no': employee_no,
                        'employee_id': employee.id,
                        'raw_data': json.dumps(event),
                    })
                    
                    event_date = dt.date()
                    HikAttendance = self.env['hikvision.attendance']
                    day_record = HikAttendance.search([
                        ('employee_id', '=', employee.id),
                        ('date', '=', event_date)
                    ], limit=1)
                    
                    if not day_record:
                        HikAttendance.create({
                            'employee_id': employee.id,
                            'date': event_date,
                            'first_check_in': dt,
                            'status': 'in'
                        })
                    else:
                        if not day_record.last_check_out or dt > day_record.last_check_out:
                            day_record.write({
                                'last_check_out': dt,
                                'status': 'out'
                            })
                    
                    imported_count += 1
                    
                except Exception as e:
                    _logger.error(f"Error importing event: {e}")
                    continue
            
            if skipped_no_employee:
                _logger.warning(f"SUMMARY: Skipped employee IDs (no match in Odoo): {skipped_no_employee}")
            
            message = _('%s events imported from %s to %s.') % (imported_count, start_dt.date(), end_dt.date())
            if skipped_no_employee:
                message += _(' Skipped %s unmatched employee IDs: %s') % (len(skipped_no_employee), ', '.join(skipped_no_employee))
            
            # Ensure all employees have records for the fetched period
            self._ensure_complete_attendance(start_dt.date(), end_dt.date())
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Logs Fetched'),
                    'message': message,
                    'type': 'warning' if skipped_no_employee else 'success',
                    'sticky': bool(skipped_no_employee),
                }
            }
            


    def action_fetch_today_logs(self):
        """Fetch today's attendance logs from the device using the robust by-date approach."""
        self.ensure_one()
        today = fields.Date.today()
        # Use simple string formatting or pass date objects if action_fetch_logs_by_date handles it
        # action_fetch_logs_by_date handles both strings and date objects.
        return self.action_fetch_logs_by_date(today, today)

    def action_fetch_logs_chunked(self, start_date, end_date, chunk_days=7):
        """
        Fetch logs in smaller date range chunks to prevent 401 errors and partial data.
        
        This method automatically splits large date ranges into smaller chunks,
        adds delays between requests, and provides progress feedback.
        
        Args:
            start_date: Start date (date object or string)
            end_date: End date (date object or string)
            chunk_days: Number of days per chunk (default: 7)
        """
        self.ensure_one()
        
        import datetime
        from datetime import timedelta
        
        # Convert to date objects if strings
        if isinstance(start_date, str):
            start_date = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        if isinstance(end_date, str):
            end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        
        # Calculate total days and chunks
        total_days = (end_date - start_date).days + 1
        total_chunks = (total_days + chunk_days - 1) // chunk_days  # Ceiling division
        
        _logger.info(f"Starting chunked fetch: {start_date} to {end_date} ({total_days} days, {total_chunks} chunks)")
        
        current_start = start_date
        chunk_number = 0
        total_imported = 0
        all_skipped_employees = []
        
        while current_start <= end_date:
            chunk_number += 1
            current_end = min(current_start + timedelta(days=chunk_days - 1), end_date)
            
            _logger.info(f"Chunk {chunk_number}/{total_chunks}: Fetching {current_start} to {current_end}")
            
            try:
                # Fetch this chunk with retry logic
                result = self._fetch_single_chunk_with_retry(current_start, current_end, chunk_number, total_chunks)
                
                if result.get('imported_count'):
                    total_imported += result['imported_count']
                
                if result.get('skipped_employees'):
                    all_skipped_employees.extend(result['skipped_employees'])
                
                # Add delay between chunks to prevent device overload
                if current_start < end_date:
                    _logger.info(f"Waiting 3 seconds before next chunk...")
                    time.sleep(3)
                
            except Exception as e:
                _logger.error(f"Chunk {chunk_number} failed: {e}")
                # Continue with next chunk instead of failing completely
            
            # Move to next chunk
            current_start = current_end + timedelta(days=1)
        
        # Remove duplicates from skipped employees
        all_skipped_employees = list(set(all_skipped_employees))
        
        message = _('%s events imported from %s to %s.') % (
            total_imported, start_date, end_date
        )
        
        if all_skipped_employees:
            message += _(' Skipped %s unmatched employee IDs: %s') % (
                len(all_skipped_employees), ', '.join(all_skipped_employees[:10])
            )
        
        # Ensure all employees have records for the entire range
        self._ensure_complete_attendance(start_date, end_date)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Fetch Complete'),
                'message': message,
                'type': 'warning' if all_skipped_employees else 'success',
                'sticky': bool(all_skipped_employees),
            }
        }

    def _fetch_single_chunk_with_retry(self, start_date, end_date, chunk_number, total_chunks):
        """
        Fetch a single date chunk with retry logic for 401 errors.
        
        Returns:
            dict: {'imported_count': int, 'skipped_employees': list}
        """
        self.ensure_one()
        url = self._get_api_url("ISAPI/AccessControl/AcsEvent?format=json")
        
        import datetime
        
        # Convert dates to datetime
        start_dt = datetime.datetime.combine(start_date, datetime.time.min)
        end_dt = datetime.datetime.combine(end_date, datetime.time.max)
        
        max_retries = 3
        retry_count = 0
        success = False
        events = []
        active_strategy = None
        
        # Prepare strategies
        strategies = [
            {
                "name": "UTC Time, Major 0",
                "payload": {
                    "AcsEventCond": {
                        "searchID": f"odoo-chunk-{chunk_number}",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "major": 0, 
                        "minor": 0,
                        "startTime": start_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "endTime": end_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                }
            },
            {
                "name": "Local Time, No Major/Minor",
                "payload": {
                    "AcsEventCond": {
                        "searchID": f"odoo-chunk-{chunk_number}",
                        "searchResultPosition": 0,
                        "maxResults": 1000,
                        "startTime": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                        "endTime": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                }
            },
        ]
        
        last_error = None
        
        # Retry loop for the entire chunk
        while retry_count < max_retries and not success:
            try:
                # Create fresh session for each retry
                with self._get_session() as session:
                    session.headers.update({"Content-Type": "application/json"})
                    
                    # Try strategies
                    for strategy in strategies:
                        _logger.info(f"Chunk {chunk_number}: Trying strategy '{strategy['name']}' (Attempt {retry_count + 1}/{max_retries})")
                        
                        try:
                            response = session.post(
                                url,
                                json=strategy['payload'],
                                timeout=60
                            )
                            
                            if response.status_code == 200:
                                data = response.json()
                                batch = data.get('AcsEvent', {}).get('InfoList', [])
                                events.extend(batch)
                                success = True
                                active_strategy = strategy
                                _logger.info(f"Chunk {chunk_number}: Strategy succeeded! Fetched {len(batch)} events.")
                                break
                            elif response.status_code == 401:
                                _logger.warning(f"Chunk {chunk_number}: 401 error on strategy '{strategy['name']}'")
                                last_error = "401 Unauthorized"
                                time.sleep(2)  # Wait before trying next strategy
                            else:
                                _logger.warning(f"Chunk {chunk_number}: Status {response.status_code}")
                                last_error = f"{response.status_code} {response.text}"
                        
                        except Exception as e:
                            _logger.warning(f"Chunk {chunk_number}: Strategy exception: {e}")
                            last_error = str(e)
                    
                    # Pagination if initial fetch succeeded
                    if success and active_strategy:
                        last_batch_size = len(events)
                        current_position = 0
                        loop_count = 0
                        
                        while last_batch_size > 0 and loop_count < 50:
                            loop_count += 1
                            time.sleep(0.5)
                            
                            current_position += last_batch_size
                            active_strategy['payload']['AcsEventCond']['searchResultPosition'] = current_position
                            
                            try:
                                response = session.post(
                                    url,
                                    json=active_strategy['payload'],
                                    timeout=60
                                )
                                
                                if response.status_code == 200:
                                    data = response.json()
                                    batch = data.get('AcsEvent', {}).get('InfoList', [])
                                    batch_size = len(batch)
                                    
                                    if batch_size > 0:
                                        events.extend(batch)
                                        _logger.info(f"Chunk {chunk_number}: Pagination fetched {batch_size} more. Total: {len(events)}")
                                    
                                    last_batch_size = batch_size
                                    
                                    if batch_size == 0:
                                        break
                                elif response.status_code == 401:
                                    _logger.warning(f"Chunk {chunk_number}: 401 during pagination at position {current_position}")
                                    # Try to re-authenticate by breaking and retrying whole chunk
                                    success = False
                                    break
                                else:
                                    _logger.warning(f"Chunk {chunk_number}: Pagination failed with {response.status_code}")
                                    break
                            
                            except Exception as e:
                                _logger.error(f"Chunk {chunk_number}: Pagination error: {e}")
                                break
                
                # If we got here and success is still False, retry
                if not success:
                    retry_count += 1
                    if retry_count < max_retries:
                        _logger.info(f"Chunk {chunk_number}: Retrying in 5 seconds... ({retry_count}/{max_retries})")
                        time.sleep(5)
                    
            except Exception as e:
                _logger.error(f"Chunk {chunk_number}: Fatal error: {e}")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(5)
        
        if not success:
            raise UserError(_(f"Chunk {chunk_number} failed after {max_retries} retries. Last error: {last_error}"))
        
        # Process events
        _logger.info(f"Chunk {chunk_number}: Processing {len(events)} events...")
        
        imported_count = 0
        skipped_employees = []
        
        for event in events:
            try:
                employee_no = event.get('employeeNoString') or str(event.get('employeeNo', ''))
                if not employee_no or employee_no == '0':
                    continue
                
                time_str = event.get('time', '')
                if not time_str:
                    continue
                
                from dateutil import parser
                import pytz
                dt = parser.parse(time_str)
                if dt.tzinfo:
                    dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
                
                employee = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
                if not employee:
                    hik_user = self.env['hikvision.user'].search([('employee_id', '=', employee_no)], limit=1)
                    if hik_user and hik_user.odoo_employee_id:
                        employee = hik_user.odoo_employee_id
                
                if not employee:
                    if employee_no not in skipped_employees:
                        skipped_employees.append(employee_no)
                    continue
                
                existing = self.env['hikvision.event.log'].search([
                    ('device_id', '=', self.id),
                    ('employee_id', '=', employee.id),
                    ('timestamp', '=', dt)
                ], limit=1)
                
                if existing:
                    continue
                
                self.env['hikvision.event.log'].create({
                    'device_id': self.id,
                    'timestamp': dt,
                    'event_type': 'AccessControllerEvent',
                    'employee_no': employee_no,
                    'employee_id': employee.id,
                    'raw_data': json.dumps(event),
                })
                
                event_date = dt.date()
                HikAttendance = self.env['hikvision.attendance']
                day_record = HikAttendance.search([
                    ('employee_id', '=', employee.id),
                    ('date', '=', event_date)
                ], limit=1)
                
                if not day_record:
                    HikAttendance.create({
                        'employee_id': employee.id,
                        'date': event_date,
                        'first_check_in': dt,
                        'status': 'in'
                    })
                else:
                    if not day_record.last_check_out or dt > day_record.last_check_out:
                        day_record.write({
                            'last_check_out': dt,
                            'status': 'out'
                        })
                
                imported_count += 1
                
            except Exception as e:
                _logger.error(f"Error importing event: {e}")
                continue
        
        _logger.info(f"Chunk {chunk_number}: Imported {imported_count} events")
        
        return {
            'imported_count': imported_count,
            'skipped_employees': skipped_employees
        }

    def action_sync_users(self):
        """Open the sync wizard pre-filled with this device."""
        self.ensure_one()
        return {
            'name': _('Sync Device Users'),
            'type': 'ir.actions.act_window',
            'res_model': 'hikvision.service',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sync_mode': 'auto',
                'default_device_id': self.id,
            }
        }

    def action_assign_badge_ids(self):
        """Assign numeric Badge IDs to employees without valid ones."""
        self.ensure_one()
        
        employees = self.env['hr.employee'].search([])
        updated_count = 0
        
        # Find the highest existing numeric barcode
        max_id = 0
        for emp in employees:
            if emp.barcode and emp.barcode.isdigit():
                max_id = max(max_id, int(emp.barcode))
        
        # Assign IDs to employees without valid numeric barcodes
        for emp in employees:
            if not emp.barcode or not emp.barcode.isdigit():
                max_id += 1
                emp.barcode = str(max_id)
                updated_count += 1
                _logger.info(f"Assigned Badge ID {max_id} to {emp.name}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Badge IDs Assigned'),
                'message': _('%s employees updated with numeric Badge IDs.') % updated_count,
                'type': 'success' if updated_count > 0 else 'info',
            }
        }

    def action_push_employees(self):
        """Push Odoo employees to the Hikvision device."""
        self.ensure_one()
        
        # Find all employees
        employees = self.env['hr.employee'].search([])
        
        if not employees:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Warning'),
                    'message': _('No employees found.'),
                    'type': 'warning',
                }
            }
        
        url = self._get_api_url("ISAPI/AccessControl/UserInfo/Record?format=json")
        success_count = 0
        error_count = 0
        errors = []
        
        session = self._get_session()
        session.headers.update({"Content-Type": "application/json"})
        
        for emp in employees:
            # Use employee database ID as employeeNo (guaranteed numeric)
            employee_no = str(emp.id)
            
            # Also update the employee's barcode to match
            if emp.barcode != employee_no:
                emp.barcode = employee_no
            
            payload = {
                "UserInfo": {
                    "employeeNo": employee_no,
                    "name": emp.name or "Unknown",
                    "userType": "normal",
                    "Valid": {
                        "enable": True,
                        "beginTime": "2020-01-01T00:00:00",
                        "endTime": "2037-12-31T23:59:59"
                    },
                    "doorRight": "1"
                }
            }
            
            try:
                response = session.post(
                    url,
                    json=payload,
                    timeout=10
                )
                
                # Parse response to check for success
                response_data = {}
                try:
                    response_data = response.json()
                except:
                    pass
                
                # Hikvision returns statusCode 1 for success
                status_code = response_data.get("statusCode", 0)
                if response.status_code in [200, 201] and status_code == 1:
                    success_count += 1
                    _logger.info(f"Pushed employee {emp.name} (Badge: {emp.barcode}) to device")
                else:
                    error_count += 1
                    error_msg = response_data.get("subStatusCode", "") or response_data.get("errorMsg", response.text)
                    errors.append(f"{emp.name}: {error_msg}")
                    _logger.warning(f"Failed to push {emp.name}: {response.text}")
                    
            except Exception as e:
                error_count += 1
                errors.append(f"{emp.name}: {str(e)}")
                _logger.error(f"Error pushing {emp.name}: {e}")
        
        message = _('%s employees pushed successfully.') % success_count
        if error_count > 0:
            message += _(' %s failed.') % error_count
            if errors:
                # Show first 3 errors
                message += _(' Errors: %s') % '; '.join(errors[:3])
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Push Complete'),
                'message': message,
                'type': 'success' if error_count == 0 else 'warning',
                'sticky': error_count > 0,  # Keep notification visible if there are errors
            }
        }

    def action_push_selected_employees(self):
        """Open the employee list to select employees to push to the device."""
        self.ensure_one()
        return {
            'name': _('Select Employees to Push'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee',
            'view_mode': 'list',
            'view_id': self.env.ref('hikvision_attendance.view_employee_push_list').id,
            'target': 'current',
            'context': {
                'hikvision_device_id': self.id,
            },
            'help': _('Select employees using checkboxes, then click Action → "Push to Hikvision Device"'),
        }

    def push_employees_by_ids(self, employee_ids):
        """Push specific employees to the device by their IDs."""
        self.ensure_one()
        
        employees = self.env['hr.employee'].browse(employee_ids)
        if not employees:
            raise UserError(_("No employees selected."))
        
        url = self._get_api_url("ISAPI/AccessControl/UserInfo/Record?format=json")
        success_count = 0
        error_count = 0
        errors = []
        
        session = self._get_session()
        session.headers.update({"Content-Type": "application/json"})
        
        for emp in employees:
            # Use existing barcode if available, otherwise use database ID
            if emp.barcode and emp.barcode.strip():
                employee_no = emp.barcode.strip()
            else:
                employee_no = str(emp.id)
                # Update barcode to match
                emp.barcode = employee_no
            
            _logger.info(f"Preparing to push: {emp.name} (employeeNo: {employee_no})")
            
            payload = {
                "UserInfo": {
                    "employeeNo": employee_no,
                    "name": emp.name or "Unknown",
                    "userType": "normal",
                    "Valid": {
                        "enable": True,
                        "beginTime": "2020-01-01T00:00:00",
                        "endTime": "2037-12-31T23:59:59"
                    },
                    "doorRight": "1"
                }
            }
            
            _logger.debug(f"Payload for {emp.name}: {json.dumps(payload, indent=2)}")
            
            try:
                response = session.post(
                    url,
                    json=payload,
                    timeout=10
                )
                
                # Log full response for debugging
                _logger.info(f"Push {emp.name}: HTTP {response.status_code}")
                _logger.debug(f"Response headers: {response.headers}")
                _logger.debug(f"Response body: {response.text}")
                
                response_data = {}
                try:
                    response_data = response.json()
                except:
                    # If JSON parsing fails, log raw text
                    _logger.warning(f"Could not parse JSON response for {emp.name}: {response.text}")
                
                # Hikvision returns statusCode 1 for success
                status_code = response_data.get("statusCode", 0)
                sub_status = response_data.get("subStatusCode", "")
                
                if response.status_code in [200, 201] and status_code == 1:
                    success_count += 1
                    _logger.info(f"✓ Pushed employee {emp.name} (Badge: {emp.barcode}) to device")
                else:
                    error_count += 1
                    # Build detailed error message
                    error_parts = []
                    if response.status_code not in [200, 201]:
                        error_parts.append(f"HTTP {response.status_code}")
                    if status_code != 1:
                        error_parts.append(f"statusCode={status_code}")
                    if sub_status:
                        error_parts.append(f"subStatus={sub_status}")
                    if response_data.get("errorMsg"):
                        error_parts.append(response_data["errorMsg"])
                    
                    # If no specific error, use response text
                    if not error_parts:
                        error_parts.append(response.text[:100] if response.text else "Unknown error")
                    
                    error_msg = ", ".join(error_parts)
                    errors.append(f"{emp.name}: {error_msg}")
                    _logger.warning(f"✗ Failed to push {emp.name} (Badge: {emp.barcode}): {error_msg}")
                    _logger.debug(f"Full response: {response_data}")
                    
            except Exception as e:
                error_count += 1
                errors.append(f"{emp.name}: {str(e)}")
                _logger.error(f"✗ Exception pushing {emp.name}: {e}", exc_info=True)
        
        message = _('%s employees pushed successfully.') % success_count
        if error_count > 0:
            message += _(' %s failed.') % error_count
            if errors:
                message += _(' Errors: %s') % '; '.join(errors[:3])
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Push Complete'),
                'message': message,
                'type': 'success' if error_count == 0 else 'warning',
                'sticky': error_count > 0,
            }
        }

    def _fetch_logs_fallback(self, start_time, end_time):
        """Fallback method using CMS search for devices that don't support AcsEvent"""
        url = self._get_api_url("ISAPI/ContentMgmt/Search")
        
        payload = {
            "CMSearchDescription": {
                "searchID": "odoo-fallback-search",
                "trackIDList": {"trackID": [101]}, # Often needed for access/attendance
                "timeSpanList": [{
                    "startTime": start_time.strftime("%Y-%m-%dT00:00:00Z"),
                    "endTime": end_time.strftime("%Y-%m-%dT23:59:59Z")
                }],
                "maxResults": 1000,
                "searchResultPosition": 0,
                "metadataList": ["recordType"]
            }
        }
        
        try:
            response = requests.post(
                url,
                auth=HTTPDigestAuth(self.username, self.password),
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            # If we get here, the fallback worked! 
            # Note: Parsing CMS results is complex and varies by device. 
            # For now just notify the user that we connected but parsing needs custom logic
            # or try to extract if it looks like standard CMS result.
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _('Fallback search endpoint connected! However, parsing CMS data is not yet fully implemented for this device type. Please inspect the log for raw data.'),
                    'type': 'warning',
                }
            }
            
        except Exception as e:
             _logger.error(f"Fallback search failed: {e}")
             raise UserError(_("Both standard fetch and fallback failed. The device may not support log retrieval via ISAPI. Please use the Live Stream feature."))

    def _stream_listener_thread(self, device_id):
        """
        Threaded method to listen to the stream.
        Note: In a real Odoo environment, we need to be careful with cursors.
        We should create a new cursor for database operations.
        """
        # Wait a bit to ensure the transaction that started this thread is committed
        time.sleep(2)
        
        with self.pool.cursor() as new_cr:
            # Re-browse the record with the new cursor
            device = self.with_env(self.env(cr=new_cr)).browse(device_id)
            
            url = device._get_api_url("ISAPI/Event/notification/alertStream")
            _logger.info(f"Starting stream listener for device {device.name} at {url}")
            
            # Flag to track if we should keep streaming
            keep_streaming = True
            check_counter = 0
            
            try:
                # Use session from device logic to ensure headers/auth are correct
                with device._get_session() as session:
                    # Use stream=True to keep connection open
                    with session.get(
                        url, 
                        stream=True, 
                        timeout=(10, None)  # 10 sec connect timeout, no read timeout
                    ) as response:
                        
                        if response.status_code != 200:
                            _logger.error(f"Stream failed with status {response.status_code}")
                            device.write({'status': 'error', 'is_streaming': False})
                            new_cr.commit()
                            return

                        _logger.info(f"Stream connected successfully for device {device.name}")
                        
                        # Buffer to accumulate JSON content
                        json_buffer = ""
                        
                        for line in response.iter_lines():
                            check_counter += 1
                            
                            # Only check database every 50 iterations to reduce overhead
                            if check_counter >= 50:
                                check_counter = 0
                                try:
                                    new_cr.execute("SELECT is_streaming FROM hikvision_device WHERE id = %s", (device_id,))
                                    result = new_cr.fetchone()
                                    if not result or not result[0]:
                                        _logger.info("Streaming stopped by user")
                                        keep_streaming = False
                                except Exception as e:
                                    _logger.error(f"Error checking stream status: {e}")
                            
                            if not keep_streaming:
                                break
                                
                            if line:
                                decoded_line = line.decode('utf-8', errors='ignore').strip()
                                
                                # Skip boundary and headers
                                if decoded_line.startswith('--boundary') or decoded_line.startswith('Content-'):
                                    continue
                                
                                # Accumulate JSON lines
                                json_buffer += decoded_line
                                
                                # Try to parse complete JSON object
                                if decoded_line == '}' and json_buffer.strip().startswith('{'):
                                    try:
                                        event_data = json.loads(json_buffer)
                                        event_type = event_data.get('eventType', '')
                                        
                                        if event_type == 'AccessControllerEvent':
                                            _logger.info(f"*** ACCESS EVENT RECEIVED ***")
                                            device._process_json_event(event_data)
                                        
                                    except json.JSONDecodeError as e:
                                        _logger.debug(f"JSON parse error (incomplete): {e}")
                                    except Exception as e:
                                        _logger.error(f"Error processing event: {e}")
                                    finally:
                                        json_buffer = ""
                                
                                # Prevent buffer from growing too large
                                if len(json_buffer) > 50000:
                                    json_buffer = ""
                            
            except Exception as e:
                _logger.exception("Stream listener crashed")
                try:
                    # Use a new cursor to write the error status
                    with self.pool.cursor() as err_cr:
                        err_device = self.with_env(self.env(cr=err_cr)).browse(device_id)
                        err_device.write({'status': 'error', 'is_streaming': False})
                        err_cr.commit()
                except:
                    pass
            finally:
                _logger.info("Stream listener stopped")

    def _process_json_event(self, event_data):
        """
        Process JSON event data from the stream.
        """
        try:
            event_type = event_data.get('eventType', '')
            date_time = event_data.get('dateTime', '')
            
            access_event = event_data.get('AccessControllerEvent', {})
            employee_no = access_event.get('employeeNoString') or str(access_event.get('employeeNo', ''))
            
            _logger.info(f"Processing event: type={event_type}, employee={employee_no}, time={date_time}")
            
            if not employee_no or employee_no == '0':
                _logger.warning(f"No valid employee number in event")
                return
            
            # Parse datetime
            from dateutil import parser
            import pytz
            dt = parser.parse(date_time)
            if dt.tzinfo:
                dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
            
            # Find Employee by barcode
            employee = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
            
            if not employee:
                # Try hikvision.user mapping
                hik_user = self.env['hikvision.user'].search([('employee_id', '=', employee_no)], limit=1)
                if hik_user and hik_user.odoo_employee_id:
                    employee = hik_user.odoo_employee_id
            
            if not employee:
                _logger.warning(f"Employee not found for ID: {employee_no}")
                return
            
            _logger.info(f"Found employee: {employee.name}")
            
            # Log the event
            try:
                self.env['hikvision.event.log'].create({
                    'device_id': self.id,
                    'timestamp': dt,
                    'event_type': event_type,
                    'employee_no': employee_no,
                    'employee_id': employee.id,
                    'raw_data': json.dumps(event_data),
                })
                _logger.info(f"Event logged for employee {employee_no}")
            except Exception as e:
                _logger.error(f"Failed to log event: {e}")
            
            # Create attendance
            event_date = dt.date()
            
            # Check/update hr.attendance
            last_attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_out', '=', False)
            ], limit=1)
            
            if last_attendance:
                last_attendance.write({'check_out': dt})
                _logger.info(f"Checked out {employee.name} at {dt}")
            else:
                self.env['hr.attendance'].create({
                    'employee_id': employee.id,
                    'check_in': dt
                })
                _logger.info(f"Checked in {employee.name} at {dt}")
            
            # Create/update hikvision.attendance (daily summary)
            HikAttendance = self.env['hikvision.attendance']
            day_record = HikAttendance.search([
                ('employee_id', '=', employee.id),
                ('date', '=', event_date)
            ], limit=1)
            
            if day_record:
                if last_attendance:
                    day_record.write({'last_check_out': dt, 'status': 'out'})
                else:
                    day_record.write({'status': 'in'})
            else:
                HikAttendance.create({
                    'employee_id': employee.id,
                    'date': event_date,
                    'first_check_in': dt,
                    'status': 'in'
                })
            
            # Commit to persist
            self.env.cr.commit()
            _logger.info(f"Attendance recorded for {employee.name}")
            
        except Exception as e:
            _logger.error(f"Failed to process JSON event: {e}")

    def _process_stream_data(self, data_str):
        """
        Parse the XML data string and create attendance.
        """
        try:
            # Clean up the string if it's mixed with multipart headers
            # Find the start and end of the XML
            start = data_str.find('<EventNotificationAlert')
            end = data_str.find('</EventNotificationAlert>') + len('</EventNotificationAlert>')
            
            if start == -1 or end == -1:
                _logger.warning("Could not find EventNotificationAlert tags in stream data")
                return

            xml_content = data_str[start:end]
            
            # Remove namespace to simplify parsing
            xml_content = xml_content.replace('xmlns="http://www.hikvision.com/ver20/XMLSchema"', '')
            
            root = ET.fromstring(xml_content)
            
            # Helper to find text recursively
            def find_text(elem, tag):
                # Try direct child
                found = elem.find(tag)
                if found is not None:
                    return found.text
                # Try recursive search
                found = elem.find('.//' + tag)
                if found is not None:
                    return found.text
                return None

            event_type = find_text(root, 'eventType')
            _logger.info(f"Received event type: {event_type}")
            
            # Accept various access control event types
            if event_type not in ['AccessControllerEvent', 'attendance', 'AccessControl']:
                _logger.info(f"Ignoring event type: {event_type}")
                return

            # Try multiple paths to find employee info
            event_info = root.find('.//AccessControllerEvent')
            if event_info is None:
                _logger.warning("No AccessControllerEvent found in XML")
                return

            employee_no = find_text(event_info, 'employeeNoString') or find_text(event_info, 'employeeNo')
            time_str = find_text(root, 'dateTime')
            
            if employee_no and time_str:
                # Parse time for logging
                dt_log = fields.Datetime.now()
                try:
                    from dateutil import parser
                    import pytz
                    dt_obj = parser.parse(time_str)
                    if dt_obj.tzinfo:
                        dt_obj = dt_obj.astimezone(pytz.UTC)
                    dt_log = dt_obj.replace(tzinfo=None)
                except Exception:
                    pass

                # Try to find employee for logging (best effort)
                emp_log_id = False
                try:
                    emp = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
                    if not emp:
                        hik_user = self.env['hikvision.user'].search([('employee_id', '=', employee_no)], limit=1)
                        if hik_user and hik_user.odoo_employee_id:
                            emp = hik_user.odoo_employee_id
                    if emp:
                        emp_log_id = emp.id
                except Exception:
                    pass

                # Log the event
                try:
                    self.env['hikvision.event.log'].create({
                        'device_id': self.id,
                        'timestamp': dt_log,
                        'event_type': event_type,
                        'employee_no': employee_no,
                        'employee_id': emp_log_id,
                        'raw_data': data_str,
                    })
                    self.env.cr.commit()  # Commit to persist in background thread
                    _logger.info(f"Event logged for employee {employee_no}")
                except Exception as e:
                    _logger.error(f"Failed to log event: {e}")

                self._create_attendance(employee_no, time_str)

        except Exception as e:
            _logger.error(f"Failed to parse stream data: {e}")

    def _create_attendance(self, employee_no, time_str):
        """
        Create attendance record for the employee.
        """
        # Convert time_str to Odoo datetime
        # Hikvision format: 2023-10-27T10:00:00+08:00
        try:
            # Simple ISO parse
            from dateutil import parser
            dt = parser.parse(time_str)
            # Convert to UTC as Odoo stores in UTC
            import pytz
            if dt.tzinfo:
                dt = dt.astimezone(pytz.UTC)
            else:
                # Assume device is in local time, convert to UTC? 
                # Or assume it's UTC? Let's assume it's naive and convert to UTC based on user timezone?
                # Safer: assume UTC if no tz, or just strip tz if Odoo handles it.
                # Odoo fields.Datetime expects naive UTC datetime.
                dt = dt.replace(tzinfo=None) 
                # TODO: Handle timezone correctly based on device config
        except:
            _logger.error(f"Could not parse time: {time_str}")
            return

        # Find Employee
        # 1. Try to find by barcode (common mapping)
        employee = self.env['hr.employee'].search([('barcode', '=', employee_no)], limit=1)
        
        # 2. If not found, try hikvision.user mapping
        if not employee:
            hik_user = self.env['hikvision.user'].search([('employee_id', '=', employee_no)], limit=1)
            if hik_user and hik_user.odoo_employee_id:
                employee = hik_user.odoo_employee_id
        
        if not employee:
            _logger.warning(f"Employee not found for ID: {employee_no}")
            return

        # Get the date from timestamp
        event_date = dt.date() if hasattr(dt, 'date') else dt.replace(tzinfo=None).date()
        
        # Create/update hr.attendance (Odoo native)
        last_attendance = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_out', '=', False)
        ], limit=1)

        if last_attendance:
            # Check out
            last_attendance.write({'check_out': dt})
            _logger.info(f"Checked out {employee.name} at {dt}")
        else:
            # Check in
            self.env['hr.attendance'].create({
                'employee_id': employee.id,
                'check_in': dt
            })
            _logger.info(f"Checked in {employee.name} at {dt}")
        
        # Create/update hikvision.attendance (daily summary with late/early tracking)
        HikAttendance = self.env['hikvision.attendance']
        day_record = HikAttendance.search([
            ('employee_id', '=', employee.id),
            ('date', '=', event_date)
        ], limit=1)
        
        if day_record:
            # Update existing record
            if last_attendance:
                # This is a check-out
                day_record.write({
                    'last_check_out': dt,
                    'status': 'out'
                })
            else:
                # This is a check-in, but record exists (maybe second check-in)
                day_record.write({'status': 'in'})
        else:
            # Create new daily record
            HikAttendance.create({
                'employee_id': employee.id,
                'date': event_date,
                'first_check_in': dt,
                'status': 'in'
            })
        
        # Commit to persist in background thread
        self.env.cr.commit()

    def _ensure_complete_attendance(self, start_date, end_date):
        """
        Ensure every active employee has a hikvision.attendance record for 
        every day between start_date and end_date.
        Records without check-ins will automatically be marked as 'Absent'.
        """
        import datetime
        from datetime import timedelta
        
        # Get all active employees who belong to a Work Policy (meaning they are tracked)
        employees = self.env['hr.employee'].search([
            ('active', '=', True),
            ('attendance_policy_id', '!=', False)
        ])
        
        if not employees:
            return
            
        HikAttendance = self.env['hikvision.attendance']
        
        # Iterate through date range
        curr_date = start_date
        while curr_date <= end_date:
            # Check for existing records for this date to avoid mass queries
            existing_recs = HikAttendance.search([
                ('date', '=', curr_date),
                ('employee_id', 'in', employees.ids)
            ])
            employees_with_record = existing_recs.mapped('employee_id')
            
            employees_to_create = employees - employees_with_record
            
            if employees_to_create:
                _logger.info(f"Creating {len(employees_to_create)} absentee records for {curr_date}")
                for emp in employees_to_create:
                    HikAttendance.create({
                        'employee_id': emp.id,
                        'date': curr_date,
                        # No check-in/out makes it 'absent'
                    })
            
            curr_date += timedelta(days=1)
