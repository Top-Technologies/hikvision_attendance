import requests
from requests.auth import HTTPDigestAuth
import getpass

url = "http://192.168.30.138:80/ISAPI/System/deviceInfo"

print(f"Testing connection to {url}")
username = input("Enter Username (default: admin): ") or "admin"
password = getpass.getpass("Enter Password: ")

try:
    print(f"Attempting connection with user: {username}...")
    response = requests.get(
        url, 
        auth=HTTPDigestAuth(username, password),
        timeout=10
    )
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        print("Success! Connection established.")
        print(response.text[:200])
    elif response.status_code == 401:
        print("Failed: 401 Unauthorized. Wrong username or password.")
        print("Headers:", response.headers)
    else:
        print(f"Failed with status {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"Error: {e}")
