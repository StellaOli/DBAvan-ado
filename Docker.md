Criar arquivo docker-compose.yml

usar comando 'docker-compose up -d'

Testar MONGO

Conecte via MongoDB Compass (GUI) ou linha de comando:
docker exec -it cypher-mongodb-1 mongosh -u stellacorreiaoli -p MCAzOqO95

Crie um banco de teste:
use Cypher
db.songs.insertOne({ title: "Test Song", artist: "Test Artist" })
db.songs.find()

Testar REDIS

Acesse o CLI do Redis:
docker exec -it cypher-redis-1 redis-cli

Teste comandos:
SET recommendations:user1 "Song1,Song2,Song3"
GET recommendations:user1

TESTAR KAFKA

Crie um tópico chamado user-actions:
docker exec -it cypher-kafka-1 kafka-topics --create --topic user-actions --partitions 1 --replication-factor 1 --bootstrap-server localhost:9092

Produza uma mensagem:
docker exec -it cypher-kafka-1 bash -c "echo '{\"user\": \"test\", \"action\": \"play\"}' | kafka-console-producer --topic user-actions --bootstrap-server localhost:9092"

Consuma mensagens:
docker exec -it cypher-kafka-1 kafka-console-consumer --topic user-actions --from-beginning --bootstrap-server localhost:9092


Para desligar tudo:
docker-compose down

Para remover os volumes (cuidado, isso apaga os dados):
docker-compose down -v
