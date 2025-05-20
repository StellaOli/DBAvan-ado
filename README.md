# CYPHER

## Desenvolvimento de um projeto de banco de dados com APIs

O projeto Cypher propõe um sistema capaz de fazer recomendações de músicas para os usuários baseado em suas escolhas do que ouvir. </br>
Ele possui:
* 1 banco relacional: POSTGRESQL
* 2 bancos não relacionais: REDIS/MONGODB
* 1 mensageria: APACHE KAFKA
  - Teremos a implementação do KAFKA CONSUMER API para ler as mensagens que o S1 vai gerar e receber, e buscar dados que o S3 armazenou no Elasticsearch dessas mensagens.
  - O Elasticsearch é um serviço de gerenciamento do armazenamento de dados não estruturados.
 
## Mapa do Projeto </br>
![Mapa Mental com as informações base da estrutura do projeto.](https://github.com/StellaOli/DBAvan-ado/blob/main/Diagrama.png)

