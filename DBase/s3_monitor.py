from kafka import KafkaAdminClient
from connections import DatabaseConnections
import logging
from time import sleep
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ServiceMonitor:
    def __init__(self, db):
        self.db = db
        self.last_status = {}
        self.status_window = []
        self.MAX_WINDOW_SIZE = 10  # Keep last 10 status checks


    def check_elasticsearch_logs(self, last_minutes=5):
        try:
            if not self.db.es_client:
                return {"status": "elasticsearch_not_available", "logs": []}
                
            # Consulta os logs dos últimos X minutos
            query = {
                "query": {
                    "range": {
                        "timestamp": {
                            "gte": f"now-{last_minutes}m",
                            "lte": "now"
                        }
                    }
                },
                "sort": [{"timestamp": {"order": "desc"}}],
                "size": 50
            }
            
            response = self.db.es_client.search(index="cypher-messages", body=query)
            logs = [hit["_source"] for hit in response["hits"]["hits"]]
            
            return {
                "status": "success",
                "logs": logs,
                "total": response["hits"]["total"]["value"]
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "logs": []
            }

    def check_postgresql(self):
        try:
            start_time = datetime.now()
            with self.db.pg_conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                latency = (datetime.now() - start_time).total_seconds() * 1000
                return {
                    'status': 'healthy' if result[0] == 1 else '    ',
                    'latency_ms': round(latency, 2),
                    'error': None
                }
        except Exception as e:
            return {
                'status': 'down',
                'latency_ms': None,
                'error': str(e)
            }

    def check_mongodb(self):
        try:
            start_time = datetime.now()
            result = self.db.mongo_db.command('ping')
            latency = (datetime.now() - start_time).total_seconds() * 1000
            return {
                'status': 'healthy' if result['ok'] == 1 else 'degraded',
                'latency_ms': round(latency, 2),
                'error': None
            }
        except Exception as e:
            return {
                'status': 'down',
                'latency_ms': None,
                'error': str(e)
            }

    def check_redis(self):
        try:
            start_time = datetime.now()
            result = self.db.redis_client.ping()
            latency = (datetime.now() - start_time).total_seconds() * 1000
            return {
                'status': 'healthy' if result else 'degraded',
                'latency_ms': round(latency, 2),
                'error': None
            }
        except Exception as e:
            return {
                'status': 'down',
                'latency_ms': None,
                'error': str(e)
            }

    def check_elasticsearch(self):
        try:
            start_time = datetime.now()
            health = self.db.es_client.cluster.health()
            latency = (datetime.now() - start_time).total_seconds() * 1000
            return {
                'status': health['status'],
                'latency_ms': round(latency, 2),
                'error': None,
                'details': {
                    'cluster_name': health['cluster_name'],
                    'number_of_nodes': health['number_of_nodes'],
                    'active_shards': health['active_shards']
                }
            }
        except Exception as e:
            return {
                'status': 'down',
                'latency_ms': None,
                'error': str(e)
            }

    def check_kafka(self):
        try:
            start_time = datetime.now()
            
            config = {
                'bootstrap_servers': "kafka-1a4e4c5b-luisaugustomarimm-b810.l.aivencloud.com:18486",
                'security_protocol': "SSL",
                'ssl_cafile': "ca.pem",
                'ssl_certfile': "service.cert",
                'ssl_keyfile': "service.key",
                'request_timeout_ms': 10000
            }
            
            # Teste de conexão básica
            admin = KafkaAdminClient(**config)
            topics = admin.list_topics()
            admin.close()
            
            latency = (datetime.now() - start_time).total_seconds() * 1000
            
            return {
                'status': 'healthy',
                'latency_ms': round(latency, 2),
                'error': None,
                'details': {
                    'topics': topics,
                    'broker_version': admin._client.check_version()
                }
            }
            
        except Exception as e:
            return {
                'status': 'down',
                'latency_ms': None,
                'error': str(e),
                'details': {
                    'suggestion': 'Verifique os certificados SSL e a conexão de rede'
                }
            }

    def check_all_services(self):
        services = {
            'PostgreSQL': self.check_postgresql,
            'MongoDB': self.check_mongodb,
            'Redis': self.check_redis,
            'Elasticsearch': self.check_elasticsearch,
            'Kafka': self.check_kafka
        }
        
        current_status = {}
        for name, check_func in services.items():
            current_status[name] = check_func()
        
        # Store in window for trend analysis
        self.status_window.append({
            'timestamp': datetime.now(),
            'status': current_status
        })
        if len(self.status_window) > self.MAX_WINDOW_SIZE:
            self.status_window.pop(0)
        
        self.last_status = current_status
        return current_status

    def detect_anomalies(self):
        if len(self.status_window) < 3:  # Need at least 3 data points
            return []
        
        anomalies = []
        latest = self.status_window[-1]['status']
        
        # Check for service degradation patterns
        for service_name, service_status in latest.items():
            # Check if service is down
            if service_status['status'] == 'down':
                anomalies.append(f"Service {service_name} is DOWN")
                continue
                
            # Check for latency spikes
            latencies = [
                status['status'].get(service_name, {}).get('latency_ms', 0) 
                for status in self.status_window[-3:]
                if service_name in status['status']
            ]
            
            if len(latencies) >= 3:
                avg_latency = sum(latencies) / len(latencies)
                if service_status['latency_ms'] > avg_latency * 2:  # Latency doubled
                    anomalies.append(
                        f"High latency detected for {service_name}: "
                        f"{service_status['latency_ms']}ms (avg: {avg_latency:.2f}ms)"
                    )
        
        return anomalies

    def log_status_to_elasticsearch(self, status):
        if not self.db.es_client:
            logger.warning("Elasticsearch not available for status logging")
            return
        
        try:
            doc = {
                "monitor_type": "service_status",
                "timestamp": datetime.now(),
                "status": status,
                "anomalies": self.detect_anomalies(),
                "metadata": {
                    "source": "cypher-monitor",
                    "version": "2.0"
                }
            }
            
            response = self.db.es_client.index(
                index="cypher-monitor",
                body=doc
            )
            logger.info(f"Status logged to Elasticsearch with ID: {response['_id']}")
        except Exception as e:
            logger.error(f"Error logging status to Elasticsearch: {e}")

def run_monitoring():
    db = DatabaseConnections()
    monitor = ServiceMonitor(db)
    
    # Create Elasticsearch index if it doesn't exist
    try:
        if db.es_client and not db.es_client.indices.exists(index="cypher-monitor"):
            mappings = {
                "properties": {
                    "monitor_type": {"type": "keyword"},
                    "timestamp": {"type": "date"},
                    "status": {"type": "object", "enabled": True},
                    "anomalies": {"type": "text"},
                    "metadata": {"type": "object"}
                }
            }
            db.es_client.indices.create(index="cypher-monitor", body={"mappings": mappings})
    except Exception as e:
        logger.error(f"Error creating monitor index: {e}")

    while True:
        try:
            status = monitor.check_all_services()
            logger.info("Service status: %s", {
                service: f"{info['status']} ({info.get('latency_ms', '?')}ms)"
                for service, info in status.items()
            })
            
            anomalies = monitor.detect_anomalies()
            if anomalies:
                logger.warning("Anomalies detected:\n%s", "\n".join(anomalies))
            
            monitor.log_status_to_elasticsearch(status)
            
        except Exception as e:
            logger.error(f"Monitoring cycle failed: {e}")
        
        sleep(30)

if __name__ == "__main__":
    run_monitoring()