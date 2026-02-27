import requests
from requests.auth import HTTPDigestAuth
import getpass

url = "http://192.168.30.138:80/ISAPI/System/deviceInfo"

print(f"Testing connection to {url} using Session + User-Agent")
username = input("Enter Username (default: admin): ") or "admin"
password = getpass.getpass("Enter Password: ")

try:
    with requests.Session() as session:
        session.auth = HTTPDigestAuth(username, password)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*'
        })
        
        print(f"Attempting connection...")
        response = session.get(url, timeout=10)
        
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Success! Connection established.")
            print(response.text[:200])
        elif response.status_code == 401:
            print("Failed: 401 Unauthorized.")
            print("WWW-Authenticate:", response.headers.get('WWW-Authenticate'))
        else:
            print(f"Failed with status {response.status_code}")
            print(response.text)

except Exception as e:
    import traceback
    traceback.print_exc()
