import boto3
import json
import logging
from ..core.config import SQS_QUEUE_URL, AWS_REGION_NAME
from ..models.sync import SqsParameters
from datetime import datetime

logger = logging.getLogger(__name__)

_sqs_client = None

def _get_sqs_client():
    """Singleton para el cliente SQS.

    Sin credenciales explícitas: boto3 usa su cadena de credenciales default,
    que en ECS toma el IAM Task Role automáticamente vía metadata. Pasar
    AWS_ACCESS_KEY_ID/SECRET a mano (código viejo de Render) rompe esto en AWS.
    """
    global _sqs_client
    if _sqs_client is None and SQS_QUEUE_URL:
        _sqs_client = boto3.client('sqs', region_name=AWS_REGION_NAME)
    return _sqs_client

def send_log_to_sqs(log_data: SqsParameters):
    """Send log data to AWS SQS."""
    sqs = _get_sqs_client()

    if not sqs:
        logger.warning("SQS no configurado. Credenciales faltantes.")
        return None

    try:
        log_data_dict = log_data.dict()
        log_data_dict['date'] = datetime.utcnow().isoformat()

        message_body = json.dumps(log_data_dict, ensure_ascii=False)
        message_attributes = {
            'EventType': {
                'DataType': 'String',
                'StringValue': log_data_dict.get('action', 'UNKNOWN')
            },
            'SourceService': {
                'DataType': 'String',
                'StringValue': 'BackendService'
            }
        }

        response = sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            DelaySeconds=0,
            MessageAttributes=message_attributes,
            MessageBody=message_body
        )

        message_id = response.get('MessageId')
        logger.debug(f"Log enviado a SQS. MessageId: {message_id}")
        return message_id

    except Exception as e:
        logger.error(f"Error al enviar log a SQS: {e}")
        return None
