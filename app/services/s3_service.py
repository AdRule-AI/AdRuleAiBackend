import boto3
from app.config import Config
import zipfile
import io
import os

class S3Service:
    def __init__(self):
        # Create a session with AWS credentials
        self.session = boto3.Session(
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
            aws_session_token=Config.AWS_SESSION_TOKEN,  # Add session token support
            region_name=Config.AWS_REGION
        )
        
        # Create S3 client using the session
        self.s3_client = self.session.client('s3')
        self.bucket = Config.S3_BUCKET

    def upload_file(self, file_obj, filename):
        """Upload a file to S3"""
        try:
            print(f"Uploading file to S3: {filename}")
            self.s3_client.upload_fileobj(file_obj, self.bucket, filename)
            return f"s3://{self.bucket}/{filename}"
        except Exception as e:
            print(f"Error uploading file to S3: {str(e)}")
            raise Exception(f"Error uploading file to S3: {str(e)}")

    def extract_zip_contents(self, zip_file_obj):
        """Extract contents from zip file and upload to S3"""
        try:
            files_data = {}
            with zipfile.ZipFile(zip_file_obj) as zip_ref:
                print("Zip file contents:", zip_ref.namelist())
                for file_name in zip_ref.namelist():
                    # Skip macOS system files and directories
                    if (file_name.startswith('__MACOSX') or 
                        file_name.startswith('._') or 
                        file_name.endswith('/')):
                        continue
                    
                    with zip_ref.open(file_name) as file:
                        content = file.read()
                        # Upload to S3 and store the S3 URL
                        file_obj = io.BytesIO(content)
                        s3_url = self.upload_file(file_obj, file_name)
                        files_data[file_name] = {
                            's3_url': s3_url,
                            'content': content
                        }
            return files_data
        except Exception as e:
            raise Exception(f"Error extracting zip contents: {str(e)}") 
        
    def get_guidelines_file_url_list(self):
        """Get the URL list of the guidelines file"""
        return ["s3://airuleasset/guidelines/facebook.txt", "s3://airuleasset/guidelines/instagram.txt", "s3://airuleasset/guidelines/youtube.txt"]