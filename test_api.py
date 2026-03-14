import requests
import json

def test_analyze(image_path="test_image.jpg"):
    url = "http://localhost:8002/analyze"
    print(f"Testing {url} with image: {image_path}")
    
    try:
        with open(image_path, "rb") as f:
            files = {"image": (image_path, f, "image/jpeg")}
            response = requests.post(url, files=files)
            
        print(f"Status Code: {response.status_code}")
        
        try:
            print("Response JSON:")
            print(json.dumps(response.json(), indent=2))
        except json.JSONDecodeError:
            print("Response Text:")
            print(response.text)
            
    except FileNotFoundError:
        print(f"Error: {image_path} not found. Please provide a valid image file.")

if __name__ == "__main__":
    import sys
    img_path = sys.argv[1] if len(sys.argv) > 1 else "test_image.jpg"
    test_analyze(img_path)
