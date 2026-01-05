import sys
import os
# Add current directory to path
sys.path.append(os.getcwd())
try:
    print("Testing Imports...")
    from app.persistence import DynamoManager
    print("DynamoManager Import OK")
    
    import boto3
    print(f"Boto3 Version: {boto3.__version__}")
    
except Exception as e:
    print(f"Import Failed: {e}")
    import traceback
    traceback.print_exc()
