from time import sleep
from datetime import datetime
import json
import logging
from connections import DatabaseConnections
from kafka.errors import KafkaError, NoBrokersAvailable, NodeNotReadyError
import socket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MessageProcessor:
    def __init__(self, db):
        self.db = db
        self.max_retries = 3
        self.dead_letter_queue = []

    def log_to_elasticsearch(self, message_type, content, status="processed", metadata=None):
        try:
            doc = {
                "message_type": message_type,
                "content": str(content),
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "metadata": metadata or {}
            }
            # Use o mesmo índice que definimos na conexão
            self.db.es_client.index(index="cypher-messages", body=doc)
        except Exception as e:
            logger.error(f"Failed to log to Elasticsearch: {e}")

    def process_with_retry(self, message):
        retry_count = 0
        last_error = None
        
        while retry_count < self.max_retries:
            try:
                self.log_to_elasticsearch(
                    "kafka_message_received",
                    message.value,
                    "processing",
                    {
                        "topic": message.topic,
                        "partition": message.partition,
                        "offset": message.offset,
                        "retry_count": retry_count
                    }
                )
                
                # Process the message
                if message.topic == "user-actions":
                    self.handle_user_action(message.value)
                elif message.topic == "recommendation-requests":
                    self.handle_recommendation_request(message.value)
                
                self.log_to_elasticsearch(
                    "kafka_message_processed",
                    message.value,
                    "completed",
                    {
                        "topic": message.topic,
                        "processing_time_ms": (datetime.now() - message.timestamp).total_seconds() * 1000
                    }
                )
                return True
                
            except Exception as e:
                last_error = e
                retry_count += 1
                logger.error(f"Attempt {retry_count} failed for message {message.offset}: {str(e)}")
                sleep(2 ** retry_count)  # Exponential backoff
        
        # If we get here, all retries failed
        self.handle_failed_message(message, last_error)
        return False

    def handle_failed_message(self, message, error):
        error_data = {
            "original_message": message.value,
            "topic": message.topic,
            "partition": message.partition,
            "offset": message.offset,
            "error": str(error),
            "timestamp": datetime.now().isoformat(),
            "retries_exhausted": True
        }
        
        # Add to dead letter queue
        self.dead_letter_queue.append(error_data)
        
        # Log to Elasticsearch
        self.log_to_elasticsearch(
            "kafka_message_failed",
            message.value,
            "error",
            {
                "error": str(error),
                "retries": self.max_retries,
                "dead_letter": True
            }
        )
        
        # Optionally write to a dead letter topic or file
        try:
            with open("kafka_dead_letter.log", "a") as f:
                f.write(json.dumps(error_data) + "\n")
        except Exception as e:
            logger.error(f"Failed to write to dead letter log: {e}")

    def handle_user_action(self, message_data):
        # Implement proper user action handling
        pass

    def handle_recommendation_request(self, message_data):
        # Implement proper recommendation handling
        pass

def consume_messages():
    db = DatabaseConnections()
    processor = MessageProcessor(db)
    
    retry_count = 0
    max_retries = 5
    base_delay = 5  # segundos
    
    while True:
        consumer = None
        try:
            consumer = db.get_kafka_consumer(["user-actions", "recommendation-requests"])
            if not consumer:
                raise KafkaError("Failed to initialize Kafka consumer")
            
            retry_count = 0  # Resetar contador após conexão bem-sucedida
            
            while True:
                try:
                    messages = consumer.poll(timeout_ms=5000)
                    
                    if not messages:
                        continue
                        
                    for topic_partition, msg_batch in messages.items():
                        for message in msg_batch:
                            success = processor.process_with_retry(message)
                            if success:
                                consumer.commit()
                            else:
                                logger.error(f"Message processing failed permanently: {message.offset}")
                                
                except (KafkaError, socket.timeout) as e:
                    logger.error(f"Erro durante o consumo: {str(e)}")
                    if isinstance(e, (NoBrokersAvailable, NodeNotReadyError)):
                        break  # Reconectar
                    sleep(1)
                    
        except Exception as e:
            logger.error(f"Erro no consumidor principal: {str(e)}")
            retry_count += 1
            
            if retry_count >= max_retries:
                logger.error("Número máximo de tentativas excedido. Encerrando...")
                raise
            
            delay = base_delay * (2 ** retry_count)  # Backoff exponencial
            logger.info(f"Tentando reconectar em {delay} segundos...")
            sleep(delay)
            
        finally:
            if consumer:
                try:
                    consumer.close()
                except:
                    pass

if __name__ == "__main__":
    consume_messages()