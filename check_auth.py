
import requests

url = "http://192.168.30.138:80/ISAPI/System/deviceInfo"

try:
    print(f"Connecting to {url}...")
    # Send a request without auth to see the challenge
    response = requests.get(url, timeout=5)
    print(f"Status Code: {response.status_code}")
    print("Headers:")
    for k, v in response.headers.items():
        print(f"{k}: {v}")
        
    if 'WWW-Authenticate' in response.headers:
        print(f"\nAuth requested: {response.headers['WWW-Authenticate']}")
    else:
        print("\nNo WWW-Authenticate header found.")

except Exception as e:
    print(f"Error: {e}")
