import requests
import json
import time

def run_test():
    url = "http://localhost:8001/analyze"
    print(f"Testing {url} with test_image.jpg...")
    
    try:
        with open("test_image.jpg", "rb") as f:
            files = {"image": ("test_image.jpg", f, "image/jpeg")}
            start_time = time.time()
            response = requests.post(url, files=files, timeout=60)
            end_time = time.time()
            
        print(f"Status Code: {response.status_code}")
        print(f"Time Taken: {end_time - start_time:.2f}s")
        
        if response.status_code == 200:
            print("Success! JSON Response:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Error Response: {response.text}")
            
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    run_test()
