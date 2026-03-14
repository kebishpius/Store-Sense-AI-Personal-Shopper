try:
    print("Testing imports...")
    import google.auth
    print("google.auth OK")
    from google import genai
    print("from google import genai OK")
    from google.genai import types
    print("from google.genai import types OK")
    import fastai.vision.all # just testing, not needed
except ImportError as e:
    print(f"IMPORT ERROR: {e}")
except Exception as e:
    print(f"ERROR: {e}")
