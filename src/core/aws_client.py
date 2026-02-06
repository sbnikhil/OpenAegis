import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.config import Config as BotoConfig

from src.core.config import get_config
from src.core.logging_setup import get_logger

logger = get_logger(__name__)


class S3Client:    
    def __init__(self, bucket_name: Optional[str] = None, client: Optional[Any] = None):
        config = get_config()
        self.bucket_name = bucket_name or config.S3_BUCKET_NAME

        if not self.bucket_name:
            raise ValueError("S3_BUCKET_NAME must be set in config or passed to constructor")
        
        if client:
            self.client = client
        else:
            boto_config = BotoConfig(
                region_name=config.AWS_REGION,
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'
                }
            )
            self.client = boto3.client('s3', config=boto_config)
        
        logger.info("s3_client_initialized", bucket=self.bucket_name)
    
    def upload_file(self, local_path: str, s3_key: str, progress_callback: Optional[Callable[[int], None]] = None) -> str:
        local_file = Path(local_path)
        
        if not local_file.exists():
            logger.error("file_not_found", path=local_path)
            raise FileNotFoundError(f"File not found: {local_path}")
        
        file_size = local_file.stat().st_size
        
        try:
            logger.info("uploading_file", local_path=local_path, s3_key=s3_key, size_bytes=file_size )
            if progress_callback:
                self.client.upload_file(str(local_file), self.bucket_name, s3_key, Callback=progress_callback)
            else:
                self.client.upload_file(str(local_file), self.bucket_name, s3_key)
            
            s3_uri = f"s3://{self.bucket_name}/{s3_key}"
            logger.info("file_uploaded", s3_uri=s3_uri, size_bytes=file_size)   
            return s3_uri
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error("upload_failed", error_code=error_code, error_message=str(e), s3_key=s3_key)
            raise
    
    def download_file(self, s3_key: str, local_path: str) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            logger.info( "downloading_file", s3_key=s3_key, local_path=local_path)
            self.client.download_file(self.bucket_name, s3_key, local_path)
            file_size = Path(local_path).stat().st_size
            
            logger.info("file_downloaded", s3_key=s3_key, local_path=local_path, size_bytes=file_size)
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'NoSuchKey':
                logger.error("s3_object_not_found", s3_key=s3_key)
                raise FileNotFoundError(f"S3 object not found: {s3_key}")
            
            logger.error("download_failed", error_code=error_code, error_message=str(e), s3_key=s3_key)
            raise
    
    def list_files(self, prefix: str = "") -> List[str]:
        try:
            logger.debug("listing_files", prefix=prefix)
            
            paginator = self.client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix) 
            keys = []
            for page in pages:
                if 'Contents' in page:
                    keys.extend([obj['Key'] for obj in page['Contents']])
            
            logger.info("files_listed", count=len(keys), prefix=prefix)
            return keys
            
        except ClientError as e:
            logger.error("list_failed", error=str(e), prefix=prefix)
            raise
    
    def delete_file(self, s3_key: str) -> None:
        try:
            logger.info("deleting_file", s3_key=s3_key)
            self.client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info("file_deleted", s3_key=s3_key)
            
        except ClientError as e:
            logger.error("delete_failed", error=str(e), s3_key=s3_key)
            raise
    
    def file_exists(self, s3_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == '404':
                return False
            raise


class SecretsManagerClient:
    def __init__(self, client: Optional[Any] = None):
        config = get_config()
        
        if client:
            self.client = client
        else:
            boto_config = BotoConfig(
                region_name=config.AWS_REGION,
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'
                }
            )
            self.client = boto3.client('secretsmanager', config=boto_config)
        
        self._cache: Dict[str, tuple[Dict[str, Any], float]] = {}
        self._cache_ttl = 300
        
        logger.info("secrets_manager_client_initialized")
    
    def get_secret(self, secret_name: str, use_cache: bool = True) -> Dict[str, Any]:
        if use_cache and secret_name in self._cache:
            cached_value, expiry = self._cache[secret_name]
            if time.time() < expiry:
                logger.debug("secret_cache_hit", secret_name=secret_name)
                return cached_value
        
        try:
            logger.info("fetching_secret", secret_name=secret_name) 
            response = self.client.get_secret_value(SecretId=secret_name)    
            secret_string = response['SecretString']
            secret_value = json.loads(secret_string)
            
            self._cache[secret_name] = (
                secret_value,
                time.time() + self._cache_ttl
            )
            
            logger.info("secret_retrieved", secret_name=secret_name) 
            return secret_value
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'ResourceNotFoundException':
                logger.error("secret_not_found", secret_name=secret_name)
                raise ValueError(f"Secret not found: {secret_name}")
            elif error_code == 'AccessDeniedException':
                logger.error("secret_access_denied", secret_name=secret_name)
                raise PermissionError(f"Access denied to secret: {secret_name}")
            
            logger.error("secret_fetch_failed", error_code=error_code, error=str(e), secret_name=secret_name)
            raise
    
    def create_secret(self, secret_name: str, secret_value: Dict[str, Any], description: str = "") -> str:    
        try:
            logger.info("creating_secret", secret_name=secret_name) 
            response = self.client.create_secret(
                Name=secret_name,
                Description=description,
                SecretString=json.dumps(secret_value)
            )
            
            arn = response['ARN']  
            logger.info("secret_created", secret_name=secret_name, arn=arn)  
            return arn
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error("secret_creation_failed", error_code=error_code, error=str(e), secret_name=secret_name)
            raise
    
    def update_secret(self, secret_name: str, secret_value: Dict[str, Any]) -> None:
        try:
            logger.info("updating_secret", secret_name=secret_name) 
            self.client.update_secret(
                SecretId=secret_name,
                SecretString=json.dumps(secret_value)
            )
            
            if secret_name in self._cache:
                del self._cache[secret_name]
            
            logger.info("secret_updated", secret_name=secret_name)
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error("secret_update_failed", error_code=error_code, error=str(e), secret_name=secret_name)
            raise
    
    def clear_cache(self) -> None:
        self._cache.clear()
        logger.debug("secret_cache_cleared")

class CloudWatchClient:
    def __init__(self, client: Optional[Any] = None):
        config = get_config()
        
        if client:
            self.client = client
        else:
            boto_config = BotoConfig(
                region_name=config.AWS_REGION,
                retries={
                    'max_attempts': 3,
                    'mode': 'adaptive'
                }
            )
            self.client = boto3.client('logs', config=boto_config)
        
        self._sequence_tokens: Dict[str, Optional[str]] = {}
        
        logger.info("cloudwatch_client_initialized")
    
    def create_log_stream(self, log_group: str, log_stream: str) -> None:
        try:
            logger.debug(
                "creating_log_stream",
                log_group=log_group,
                log_stream=log_stream
            )
            
            self.client.create_log_stream(
                logGroupName=log_group,
                logStreamName=log_stream
            )
            
            logger.info(
                "log_stream_created",
                log_group=log_group,
                log_stream=log_stream
            )
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'ResourceAlreadyExistsException':
                logger.debug("log_stream_already_exists", log_stream=log_stream)
            else:
                logger.error(
                    "log_stream_creation_failed",
                    error_code=error_code,
                    error=str(e),
                    log_stream=log_stream
                )
                raise
    
    def put_log_event(self,log_group: str,log_stream: str,message: str) -> None:
        stream_key = f"{log_group}/{log_stream}"
        if stream_key not in self._sequence_tokens:
            try:
                self.create_log_stream(log_group, log_stream)
            except ClientError:
                pass
        
        try:
            params = {
                'logGroupName': log_group,
                'logStreamName': log_stream,
                'logEvents': [
                    {
                        'timestamp': int(time.time() * 1000),
                        'message': message
                    }
                ]
            }
            
            if stream_key in self._sequence_tokens and self._sequence_tokens[stream_key]:
                params['sequenceToken'] = self._sequence_tokens[stream_key]
            
            response = self.client.put_log_events(**params)
            
            self._sequence_tokens[stream_key] = response.get('nextSequenceToken')
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code in ('InvalidSequenceTokenException', 'DataAlreadyAcceptedException'):
                expected_token = e.response['Error'].get('expectedSequenceToken')
                self._sequence_tokens[stream_key] = expected_token
                
                params['sequenceToken'] = expected_token
                response = self.client.put_log_events(**params)
                self._sequence_tokens[stream_key] = response.get('nextSequenceToken')
            else:
                logger.error(
                    "put_log_event_failed",
                    error_code=error_code,
                    error=str(e),
                    log_group=log_group,
                    log_stream=log_stream
                )
                raise
