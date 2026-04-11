"""API client test script."""
import jwt
import requests
import json

JWT_SECRET = "90a6db98ac05f0a953e6551ee85502f49f134ee2ee551cd1f2b7de36483f1563"
API_URL = "http://localhost:18792/v1/chat/completions"


def main():
    payload = {"userId": "user1234"}
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    print(f"Token: {token[:50]}...")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Test health check
    r = requests.get("http://localhost:18792/health")
    print(f"Health: {r.json()}")

    # Non-streaming call
    print("\n--- Non-stream ---")
    response = requests.post(
        API_URL,
        headers=headers,
        json={
            "model": "MiniMax-M2.7",
            "messages": [{"role": "user", "content": "你好"}],
            "stream": False,
        },
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")

    # SSE streaming call
    print("\n--- SSE Stream ---")
    with requests.post(
        API_URL,
        headers=headers,
        json={
            "model": "MiniMax-M2.7",
            "messages": [{"role": "user", "content": "明天杭州的天气如何"}],
            "stream": True,
            "session_id": "1234566"
        },
        stream=True,
    ) as r:
        for line in r.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    print(json.dumps(json.loads(data), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
