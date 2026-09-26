"""
Serverless Adapters for PyFault framework.
"""

from pyfault.common.serverless.aws import AWSLambdaAdapter, create_lambda_handler
from pyfault.common.serverless.azure import AzureFunctionsAdapter, create_azure_handler
from pyfault.common.serverless.base import (
    ServerlessAdapter,
    ServerlessRequest,
    ServerlessResponse,
)
from pyfault.common.serverless.gcp import GCFAdapter, create_gcf_handler

__all__ = [
    "ServerlessAdapter",
    "ServerlessRequest",
    "ServerlessResponse",
    "AWSLambdaAdapter",
    "create_lambda_handler",
    "GCFAdapter",
    "create_gcf_handler",
    "AzureFunctionsAdapter",
    "create_azure_handler",
]
