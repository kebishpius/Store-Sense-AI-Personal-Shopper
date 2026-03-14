import requests
import json
import os
import sys

def main():
    url = "http://localhost:8000/analyze"
    # Fallback to test_image.jpg which we downloaded earlier
    image_path = "test_image.jpg"
    
    if not os.path.exists(image_path):
        print(f"Error: {image_path} not found.")
        print("Please place a test image named 'test_image.jpg' in the current directory.")
        sys.exit(1)

    print(f"Sending {image_path} to {url}...")
    
    try:
        with open(image_path, "rb") as f:
            files = {"image": (image_path, f, "image/jpeg")}
            response = requests.post(url, files=files)
            
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            try:
                data = response.json()
                print("\nSuccess! Vertex AI returned the following JSON:\n")
                print(json.dumps(data, indent=2))
                
                # Check for the specific keys requested
                print("\n--- Key Extraction Check ---")
                print(f"Product Name:  {data.get('product_name', 'MISSING')}")
                print(f"Brand:         {data.get('brand', 'MISSING')}")
                print(f"Estimated Price: {data.get('estimated_price', 'MISSING')}")
                print(f"Inventory Status: {data.get('inventory_status', 'MISSING')}")
                
            except json.JSONDecodeError:
                print("Failed to parse JSON response:")
                print(response.text)
        else:
            print(f"Request failed with status code {response.status_code}")
            print(response.text)
            print("\nIf you see a 500 error, please check the local uvicorn server logs ")
            print("for Vertex AI API permission issues related to 'hackathons-461900'.")
            
    except requests.exceptions.ConnectionError:
        print("Could not connect to the server.")
        print("Ensure the FastAPI server is running with: uvicorn server:app --reload")

if __name__ == "__main__":
    main()
