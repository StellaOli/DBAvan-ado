import os
import certifi
import os
os.environ['SSL_CERT_FILE'] = certifi.where()
import json
from pymongo import MongoClient
import redis
import psycopg2
from kafka import KafkaAdminClient, KafkaProducer, KafkaConsumer
from ssl import create_default_context
from dotenv import load_dotenv
import logging
from tempfile import NamedTemporaryFile
import ssl 
from elasticsearch import Elasticsearch
from datetime import datetime


load_dotenv()
class DatabaseConnections:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.pg_conn = self._init_cockroachdb()
        self.mongo_db = self._init_mongodb()
        self.redis_pool = None  # Adicionar pool de conexões
        self.redis_client = self._init_redis()
        self.kafka_producer, self.kafka_ssl_context = self._init_kafka()
        self.es_client = self._init_elasticsearch() 

    def _init_cockroachdb(self):
        try:
            # Verifica se o arquivo do certificado existe
            if not os.path.exists("cockroach_root.crt"):
                self.logger.error("Arquivo cockroach_root.crt não encontrado")
                return None

            # Conexão com CockroachDB usando o arquivo existente
            conn = psycopg2.connect(
                host="hard-beast-11738.6wr.aws-us-west-2.cockroachlabs.cloud",
                port=26257,
                user="luiis",
                password="xs11uj4puYYfmtzVIsl-3Q",
                database="defaultdb",  # Ajuste para o nome do seu banco de dados se necessário
                sslmode="verify-full",
                sslrootcert="cockroach_root.crt",
                options="--cluster=hard-beast-11738"  # Apenas o nome do cluster
            )

            # Cria a tabela se não existir
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id TEXT PRIMARY KEY,
                        name TEXT,
                        email TEXT,
                        preferences JSONB,
                        spotify_id TEXT
                    )
                """)
                conn.commit()

            self.logger.info("Conexão com CockroachDB estabelecida com sucesso")
            return conn

        except Exception as e:
            self.logger.error(f"Erro ao conectar ao CockroachDB: {e}")
            return None

    def _init_mongodb(self):
        try:
            uri = "mongodb+srv://luisaugustomarimm:m22knSrBHhcs2F5M@cypher.fhbebhg.mongodb.net/?retryWrites=true&w=majority&appName=Cypher"
            
            client = MongoClient(
                uri,
                tls=True,
                tlsAllowInvalidCertificates=False,
                connectTimeoutMS=30000,
                socketTimeoutMS=30000,
                tlsCAFile=certifi.where()  # Certificado CA do certifi
            )
            # Teste de conexão simplificado
            client.server_info()
            db = client["Cypher"]
            self.logger.info("Conexão com MongoDB estabelecida com sucesso")
            if 'likes' not in db.list_collection_names():
                db.create_collection('likes')
                db.likes.create_index([('user_id', 1), ('spotify_id', 1)], unique=True)
            return db
        except Exception as e:
            self.logger.error(f"Erro detalhado ao conectar ao MongoDB: {str(e)}")
            return None

    def _init_redis(self):
        try:
            if not self.redis_pool:
                self.redis_pool = redis.ConnectionPool.from_url(
                    "rediss://default:AVNS_DElxpCJjHVx4fEwJLrD@valkey-3ffe0aca-luisaugustomarimm-b810.b.aivencloud.com:18485",
                    max_connections=10,
                    socket_timeout=5,
                    ssl_cert_reqs=None  # Necessário para conexões SSL sem verificação estrita
                )
            
            client = redis.Redis(connection_pool=self.redis_pool)
            client.ping()  # Testa a conexão
            self.logger.info("Conexão com Valkey estabelecida com sucesso!")
            return client
            
        except redis.AuthenticationError:
            self.logger.error("Erro de autenticação: senha ou usuário incorreto.")
        except redis.ConnectionError as e:
            self.logger.error(f"Falha na conexão: {str(e)}")
        except Exception as e:
            self.logger.error(f"Erro inesperado: {str(e)}")
        return None

    def _init_kafka(self):
        try:
            config = {
                'bootstrap_servers': "kafka-1a4e4c5b-luisaugustomarimm-b810.l.aivencloud.com:18486",
                'security_protocol': "SSL",
                'ssl_cafile': "ca.pem",
                'ssl_certfile': "service.cert",
                'ssl_keyfile': "service.key",
                'api_version': (2, 0, 2),
                'request_timeout_ms': 10000  # Substitui socket_timeout_ms por request_timeout_ms
            }

            # Teste com AdminClient primeiro
            try:
                admin = KafkaAdminClient(**config)
                admin.list_topics()
                admin.close()
            except Exception as e:
                self.logger.error(f"Falha no teste AdminClient: {str(e)}")
                return None, None

            # Configuração do Producer
            producer_config = {
                **config,
                'value_serializer': lambda v: json.dumps(v).encode('utf-8'),
                'max_block_ms': 10000,
                'retries': 3,
                'retry_backoff_ms': 1000
            }

            producer = KafkaProducer(**producer_config)
            self.logger.info("✅ Kafka Producer criado com sucesso")
            return producer, None

        except Exception as e:
            self.logger.error(f"Erro fatal ao conectar ao Kafka: {str(e)}")
            return None, None
        
    def create_kafka_topics(self):
        from kafka.admin import KafkaAdminClient, NewTopic
        from kafka.errors import TopicAlreadyExistsError
        
        try:
            # Configuração do admin client com segurança SSL
            admin = KafkaAdminClient(
                bootstrap_servers="kafka-1a4e4c5b-luisaugustomarimm-b810.l.aivencloud.com:18486",
                security_protocol="SSL",
                ssl_cafile="ca.pem",
                ssl_certfile="service.cert",
                ssl_keyfile="service.key"
            )
            
            # Lista de tópicos necessários
            required_topics = [
                NewTopic(name="user-actions", num_partitions=1, replication_factor=1),
                NewTopic(name="recommendation-requests", num_partitions=1, replication_factor=1)
            ]
            
            # Verificar tópicos existentes
            existing_topics = admin.list_topics()
            
            # Filtrar apenas tópicos que precisam ser criados
            topics_to_create = [
                topic for topic in required_topics 
                if topic.name not in existing_topics
            ]
            
            if topics_to_create:
                admin.create_topics(new_topics=topics_to_create, validate_only=False)
                print(f"Tópicos criados: {[t.name for t in topics_to_create]}")
            else:
                print("Todos os tópicos necessários já existem")
                
        except TopicAlreadyExistsError:
            print("Aviso: Tentativa de criar tópicos que já existem")
        except Exception as e:
            print(f"Erro ao configurar tópicos Kafka: {str(e)}")
            raise  # Re-lança a exceção para tratamento externo se necessário
        finally:
            # Fechar conexão do admin client
            if 'admin' in locals():
                admin.close()

    def get_kafka_consumer(self, topics):
        try:
            consumer_config = {
                'bootstrap_servers': "kafka-1a4e4c5b-luisaugustomarimm-b810.l.aivencloud.com:18486",
                'group_id': 'cypher-consumer-group',
                'client_id': 'cypher-client',
                'security_protocol': "SSL",
                'ssl_cafile': "ca.pem",
                'ssl_certfile': "service.cert",
                'ssl_keyfile': "service.key",
                'value_deserializer': lambda v: json.loads(v.decode('utf-8')),
                'auto_offset_reset': 'earliest',
                'enable_auto_commit': False,
                'session_timeout_ms': 10000,
                'heartbeat_interval_ms': 3000,
                'max_poll_interval_ms': 300000,
                'request_timeout_ms': 30000  
            }
            
            consumer = KafkaConsumer(*topics, **consumer_config)
            
            # Teste rápido de conexão
            try:
                consumer.topics()  # Lista tópicos para verificar conexão
                self.logger.info("✅ Consumidor Kafka configurado com sucesso")
                return consumer
            except Exception as e:
                consumer.close()
                self.logger.error(f"❌ Falha no teste do consumidor: {str(e)}")
                return None
                
        except Exception as e:
            self.logger.error(f"Erro ao criar consumidor: {str(e)}", exc_info=True)
            return None
        
    def _init_elasticsearch(self):
        try:
            client = Elasticsearch(
                "https://33d3fcfc36ef4d6697264188f674aca3.southamerica-east1.gcp.elastic-cloud.com:443",
                api_key="QjFRQzBaWUJVZ2NobXdVVl8tZW06V1NFRzBQZ0lkWW5MZk9iZlRRMWRUZw=="
            )
            
            # Verificação mais robusta da conexão
            if not client.ping():
                raise ValueError("Conexão com Elasticsearch falhou")
                
            # Criar índice se não existir
            index_name = "cypher-messages"
            if not client.indices.exists(index=index_name):
                mappings = {
                    "mappings": {
                        "properties": {
                            "message_type": {"type": "keyword"},
                            "content": {"type": "text"},
                            "timestamp": {"type": "date"},
                            "status": {"type": "keyword"},
                            "metadata": {"type": "object"}
                        }
                    }
                }
                client.indices.create(index=index_name, body=mappings)
            
            self.logger.info("Conexão com Elasticsearch estabelecida com sucesso")
            return client
        except Exception as e:
            self.logger.error(f"Erro ao conectar ao Elasticsearch: {e}")
            return None
        

    def cache_user_session(self, user_id, session_data, ttl=3600):
        """Cache user session data in Redis with expiration"""
        try:
            if not self.redis_client:
                return False
                
            key = f"session:{user_id}"
            with self.redis_client.pipeline() as pipe:
                pipe.hmset(key, session_data)
                pipe.expire(key, ttl)
                pipe.execute()
            return True
        except Exception as e:
            self.logger.error(f"Error caching user session: {e}")
            return False

    def get_cached_session(self, user_id):
        """Get cached user session data from Redis"""
        try:
            if not self.redis_client:
                return None
                
            key = f"session:{user_id}"
            return self.redis_client.hgetall(key)
        except Exception as e:
            self.logger.error(f"Error getting cached session: {e}")
            return None

    def cache_recommendations(self, user_id, recommendations, ttl=3600):
        """Enhanced recommendation caching with metadata"""
        try:
            if not self.redis_client:
                return False
                
            cache_data = {
                'recommendations': json.dumps(recommendations),
                'generated_at': datetime.now().isoformat(),
                'source': 'recommendation_engine'
            }
            
            key = f"recs:{user_id}"
            self.redis_client.hset(key, cache_data)
            self.redis_client.expire(key, ttl)
            return True
        except Exception as e:
            self.logger.error(f"Error caching recommendations: {e}")
            return False

    def get_cached_recommendations(self, user_id):
        """Get cached recommendations with metadata"""
        try:
            if not self.redis_client:
                return None
                
            key = f"recs:{user_id}"
            data = self.redis_client.hgetall(key)
            if not data:
                return None
                
            return {
                'recommendations': json.loads(data[b'recommendations']),
                'generated_at': data[b'generated_at'].decode(),
                'source': data[b'source'].decode()
            }
        except Exception as e:
            self.logger.error(f"Error getting cached recommendations: {e}")
            return None
        
    def close_connections(self):
        """Fecha todas as conexões ativas"""
        try:
            if self.pg_conn:
                self.pg_conn.close()
            if self.redis_client:
                self.redis_client.close()
            if self.kafka_producer:
                self.kafka_producer.close()
            if self.es_client:
                self.es_client.close()
        except Exception as e:
            self.logger.error(f"Erro ao fechar conexões: {e}")


