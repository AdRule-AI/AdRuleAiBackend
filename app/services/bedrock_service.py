import boto3
import json
from app.config import Config
import base64
from app.services.s3_service import S3Service
from app.services.db_service import DBService
from app.models.ad import Ad
from app.models.ad_asset import AdAsset

class BedrockService:
    def __init__(self):
        # Create session with AWS credentials
        self.session = boto3.Session(
            aws_access_key_id=Config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=Config.AWS_SECRET_ACCESS_KEY,
            aws_session_token=Config.AWS_SESSION_TOKEN,
            region_name=Config.AWS_REGION
        )
        
        # Create Bedrock client using the session
        self.bedrock = self.session.client(service_name='bedrock-runtime')
        self.model_id = Config.BEDROCK_MODEL_ID
        self.s3_service = S3Service()
        self.db_service = DBService()

    def get_platform_guidelines(self, platform):
        """Fetch platform-specific guidelines from S3"""
        guideline_path = f"s3://airuleasset/guidelines/{platform.lower()}.txt"
        try:
            return self.s3_service.get_file_content(guideline_path)
        except Exception as e:
            print(f"Error fetching guidelines for {platform}: {str(e)}")
            return ""

    def analyze_ad(self, ad_details, images_data=None, video_data=None, audio_data=None):
        """Analyze ad content using Claude"""
        
        # Convert S3 URLs to base64 if needed
        if images_data and isinstance(images_data, str) and images_data.startswith('s3://'):
            s3_service = S3Service()
            images_data = s3_service.get_base64_image(images_data)
        elif images_data and isinstance(images_data, list):
            s3_service = S3Service()
            processed_images = []
            for image in images_data:
                if isinstance(image, str) and image.startswith('s3://'):
                    processed_images.append(s3_service.get_base64_image(image))
                else:
                    processed_images.append(image)
            images_data = processed_images

        # Get platform guidelines
        platform = ad_details['platform'] if 'platform' in ad_details else 'facebook' # Default to Facebook if not specified
        guidelines = self.get_platform_guidelines(platform)

        messages = self._construct_analysis_messages(ad_details, guidelines, images_data, video_data, audio_data)
        
        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": messages
                })
            )
            
            response_body = json.loads(response.get('body').read())
            analysis_result = json.loads(response_body['content'][0]['text'])
                        
            return analysis_result
            
        except Exception as e:
            print("Error analyzing ad with Bedrock:", str(e))
            raise Exception(f"Error analyzing ad with Bedrock: {str(e)}")

    def _construct_analysis_messages(self, ad_details, guidelines, images_data=None, video_data=None, audio_data=None):
        """Construct the messages array for ad analysis"""
        message_content = []
        
        # Add images if present
        if images_data:
            print("Processing images data...")
            images_list = images_data if isinstance(images_data, list) else [images_data]
            for image_data in images_list:
                print(f"Image data type: {type(image_data)}")
                print(f"Image data length: {len(image_data) if image_data else 'None'}")
                
                # Ensure the base64 string doesn't include any header
                if isinstance(image_data, str) and 'base64,' in image_data:
                    image_data = image_data.split('base64,')[1]
                
                message_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }
                })
                print("Added image to message content")

        # Add the main prompt text
        prompt_text = f"""Please analyze this advertisement against platform policies and provide a detailed report in JSON format.

Ad Details:
{ad_details}

Your task is to analyze all ad components (text, images, video, audio) for policy compliance and return a JSON response in the following format:

{{
    "ad_details": {{
        "name": "string",
        "description": "string",
        "category": "string",
        "targeting": "string",
        "message": "string"
    }},
    "analysis": {{
        "image_analysis": {{
            "description": "string",
            "concerns": ["string"],
            "compliant": boolean
        }},
        "text_analysis": {{
            "description": "string",
            "concerns": ["string"],
            "compliant": boolean
        }}
    }},
    "compliance": {{
        "status": "compliant|non_compliant|needs_review",
        "issues": [
            {{
                "type": "string",
                "description": "string",
                "severity": "high|medium|low"
            }}
        ],
        "recommendations": [
            {{
                "type": "fix|change|alternative",
                "description": "string"
            }}
        ]
    }},
    "overall_status": {{
        "is_approved": boolean,
        "confidence_score": float,
        "review_needed": boolean,
        "rejection_reasons": ["string"]
    }}
}}

Please ensure:
1. All JSON fields are properly formatted
2. Boolean values are true/false (not strings)
3. Numbers are numeric (not strings)
4. Arrays are used for multiple items
5. Nested objects are used for structured data

Focus your analysis on:
- Platform policy compliance
- Content appropriateness
- Target audience alignment
- Brand safety
- Regulatory compliance

Return only valid JSON without any additional text or explanation."""

        message_content.append({
            "type": "text",
            "text": prompt_text
        })

        # Print the final message content for debugging
        print("Final message content structure:", json.dumps(message_content, indent=2))

        return [{
            "role": "user",
            "content": message_content
        }]

    def fix_ad(self, original_analysis, ad_content):
        """Fix non-compliant ads based on the original analysis"""
        message_content = {
            "type": "text",
            "text": f"""Based on the following analysis, please fix this advertisement to make it compliant:

Original Analysis:
{original_analysis}

Ad Content to Fix:
{ad_content}

Please provide:
1. Specific changes made
2. New ad content
3. Analysis of the fixed ad
"""
        }

        try:
            response = self.bedrock.invoke_model(
                modelId=self.model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 4096,
                    "messages": [{
                        "role": "user",
                        "content": [message_content]
                    }]
                })
            )
            
            response_body = json.loads(response.get('body').read())
            print("Response body:", response_body)
            return response_body['content'][0]['text']
        
        except Exception as e:
            print("Error fixing ad with Bedrock:", str(e))
            raise Exception(f"Error fixing ad with Bedrock: {str(e)}")

    def create_batch_job(self, batch_data, job_name):
        """
        Create a batch processing job in Bedrock
        """
        try:
            # Create JSONL content for batch processing
            jsonl_content = self._prepare_batch_jsonl(batch_data)
            
            # Upload JSONL to S3
            input_s3_key = f"batch-inputs/{job_name}.jsonl"
            self.s3_service.upload_string_to_s3(jsonl_content, input_s3_key)
            
            input_data_config = {
                "s3InputDataConfig": {
                    "s3Uri": f"s3://{self.s3_service.bucket}/{input_s3_key}"
                }
            }
            
            output_data_config = {
                "s3OutputDataConfig": {
                    "s3Uri": f"s3://{self.s3_service.bucket}/batch-outputs/{job_name}/"
                }
            }
            
            response = self.bedrock_client.create_model_invocation_job(
                roleArn=Config.BEDROCK_BATCH_ROLE_ARN,
                modelId="anthropic.claude-3-haiku-20240307-v1:0",
                jobName=job_name,
                inputDataConfig=input_data_config,
                outputDataConfig=output_data_config
            )
            
            return response.get('jobArn')
            
        except Exception as e:
            print(f"Error creating batch job: {str(e)}")
            raise Exception(f"Error creating batch job: {str(e)}")

    def _prepare_batch_jsonl(self, batch_data):
        """
        Prepare JSONL content for batch processing
        """
        jsonl_lines = []
        for folder_data in batch_data:
            prompt = self._create_analysis_prompt(
                ad_details=folder_data['ad_details'],
                images_data=folder_data['images_data']
            )
            jsonl_lines.append(json.dumps({
                "prompt": prompt,
                "folder": folder_data['folder'],
                "ad_id": folder_data['ad_id']
            }))
        
        return '\n'.join(jsonl_lines)

    def get_batch_job_status(self, job_arn):
        """
        Get the status of a batch processing job
        """
        try:
            response = self.bedrock_client.get_model_invocation_job(
                jobIdentifier=job_arn
            )
            return {
                'status': response['status'],
                'startTime': response.get('startTime'),
                'endTime': response.get('endTime'),
                'failureReason': response.get('failureReason')
            }
        except Exception as e:
            print(f"Error getting batch job status: {str(e)}")
            raise Exception(f"Error getting batch job status: {str(e)}")

    def get_batch_results(self, job_name):
        """
        Get results from a completed batch job
        """
        try:
            output_prefix = f"batch-outputs/{job_name}/"
            results = self.s3_service.list_and_read_s3_files(output_prefix)
            
            processed_results = []
            for result in results:
                try:
                    result_data = json.loads(result)
                    processed_results.append({
                        'folder': result_data.get('folder'),
                        'ad_id': result_data.get('ad_id'),
                        'analysis': result_data.get('analysis')
                    })
                except json.JSONDecodeError:
                    continue
                
            return processed_results
            
        except Exception as e:
            print(f"Error getting batch results: {str(e)}")
            raise Exception(f"Error getting batch results: {str(e)}")