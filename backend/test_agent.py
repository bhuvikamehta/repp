import requests

payload = {
    "prompt": "Analyze this business strategy document. My email is test@example.com."
}

try:
    print("Sending request...")
    res = requests.post("http://127.0.0.1:8001/agent/run", json=payload)
    print("Status:", res.status_code)
    print("Response:", res.json())
except Exception as e:
    print("Error:", e)
