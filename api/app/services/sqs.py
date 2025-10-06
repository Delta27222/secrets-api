import boto3
import json
from ..core.config import SQS_QUEUE_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION_NAME
from ..models.sync import SqsParameters
from datetime import datetime

def send_log_to_sqs(log_data: SqsParameters):
    """Send log data to AWS SQS."""
    print(f"🚀 -> log_data: {log_data}")
    print("🚀 [START] Enviando log a SQS...")

    # 👉 Obtener el dict original desde el modelo
    log_data_dict = log_data.dict()

    # 👉 Inyectar el date DENTRO del objeto de log
    log_data_dict['date'] = datetime.utcnow().isoformat()

    print("📦 [PAYLOAD] Log convertido a JSON:", log_data_dict)

    try:
        sqs = boto3.client(
            'sqs',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION_NAME
        )
        print("✅ [SQS] Cliente SQS creado correctamente")

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

        print("📤 [SENDING] Enviando mensaje a SQS...")
        response = sqs.send_message(
            QueueUrl=SQS_QUEUE_URL,
            DelaySeconds=0,
            MessageAttributes=message_attributes,
            MessageBody=message_body
        )

        message_id = response.get('MessageId')
        print(f"✅ [SUCCESS] Log enviado a SQS correctamente. MessageId: {message_id}")
        return message_id

    except Exception as e:
        print(f"❌ [ERROR] Falló el envío del mensaje a SQS: {e}")
        return None

    finally:
        print("🏁 [END] Finalizado el proceso de envío de log a SQS.")
