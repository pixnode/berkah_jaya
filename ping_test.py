import requests
import time

url = "https://api.globalping.io/v1/measurements"
payload = {"type": "ping", "target": "204.168.229.145", "locations": [{"city": "Helsinki", "limit": 1}]}
try:
    r = requests.post(url, json=payload)
    if r.status_code == 202:
        mid = r.json()["id"]
        for _ in range(15):
            time.sleep(1)
            res = requests.get(f"{url}/{mid}").json()
            if res["status"] in ("finished", "error"):
                for res_node in res.get("results", []):
                    print(f"Location: {res_node['probe']['city']}, {res_node['probe']['country']}")
                    print(res_node["result"]["rawOutput"])
                break
    else:
        print("Error:", r.text)
except Exception as e:
    print(e)
